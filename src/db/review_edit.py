"""Правка проверки на приёмке сверх исправления записи: новая запись и кадры (D465).

Владелец 13.10.2026: на приёмке «поменять фотографию, добавить пункт» — прямо в
панели проверки. Исправление существующей записи уже есть (`revise.py`, D200);
здесь три недостающих действия: добавить запись, приложить кадр к записи, снять
кадр с записи.

Снять запись (#1164) — четвёртое: ошибочно занесённое на вычитке убирается, а не
правится. Номера остальных записей не сдвигаются (как у черновика загрузки,
`imports.remove_finding`); оценку пересчитывает тот же движок вызывающего по
проверке без этой записи, всё — одной транзакцией со строкой журнала правок.

Всё идёт тем же замком, что правка и подтверждение (`revise._LOCK_SQL`):
проверка СВОЕГО пространства, `status = 'draft'`, не отклонена. Принятая
отвечает отказом из базы, а не из этого модуля — политиками `0004`.

Запись добавляется (и снимается) вместе с пересчётом: оценку считает движок вызывающего
(`score_of`, обычно `src/report/rescore.py`) по проверке, уже содержащей новую
запись, и обе вещи ложатся одной транзакцией — как у правки. Кадры оценку не
трогают и пересчёта не вызывают.

Кадр кладётся в хранилище ДО строки, как у загрузки (`imports.add_photo`): в
хранилище уходит только сжатая копия (D219, D250, D253) — тот же `make_preview`,
не второй конвейер. Хранилище не приняло — строки нет; строку не приняла база —
объект остаётся сиротой, его находит сверка хранилища (`storage_reconcile`). Снятый
кадр: строка уходит транзакцией, объект убирается после неё; отказ уборки — в
журнал, а не откат.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace

import psycopg

from ..domain.models import Score
from .config import check_environment
from .errors import ReviseError, StorageError
from .imports import MAX_FINDINGS, MAX_PHOTOS_PER_FINDING, MAX_PHOTOS_PER_INSPECTION, forget_objects
from .inspection_edits import (
    Editor,
    finding_changes,
    finding_removal,
    record_edit,
    score_changes,
)
from .models import ORIGIN_LEGACY, FindingRow, InspectionDetail
from .pool import connection
from .previews import PREVIEW_CONTENT_TYPE, make_preview
from .push import _INSERT_TRANSLATION_SQL
from .queries import _read_detail, _require_inspection_id, _require_tenant
from .reach import own_reach
from .revise import _LOCK_SQL, _PAIR_TAKEN_SQL, _refuse_lock, _write_score
from .storage import PhotoStorage, object_key

#: Ссылка кадра, приложенного в вебе: `web:<id кадра>`. Колонка `telegram_file_id`
#: обязательна (схема 0001), а телеграма у такого кадра нет; префикс отличает его
#: от кадров бота и загрузки (`import:`), и дозагрузка бота его не ищет — у него
#: `storage_path` заполнен сразу.
PHOTO_PREFIX = "web:"

_NIL = "00000000-0000-0000-0000-000000000000"

_NEXT_N_SQL = "select coalesce(max(n), 0) + 1 from findings where inspection_id = %s"

_INSERT_FINDING_SQL = """
insert into findings (inspection_id, n, code, level, zone, zone_unusual, source)
values (%(id)s, %(n)s, %(code)s, %(level)s, %(zone)s, %(zone_unusual)s, 'comment')
returning id
"""

_COUNT_PHOTOS_SQL = """
select count(*) filter (where finding_id = %s), count(*) from photos where inspection_id = %s
"""

_FINDING_EXISTS_SQL = "select 1 from findings where id = %s and inspection_id = %s"

_INSERT_PHOTO_SQL = """
insert into photos (
    id, finding_id, inspection_id, telegram_file_id, storage_path, preview_path, uploaded_at
) values (%s, %s, %s, %s, %s, %s, now())
"""

_PHOTO_PATH_SQL = """
select storage_path, preview_path from photos
where id = %s and inspection_id = %s and finding_id is not null
"""

_DELETE_PHOTO_SQL = "delete from photos where id = %s and inspection_id = %s"

_PHOTOS_OF_FINDING_SQL = """
select storage_path, preview_path from photos where finding_id = %s and inspection_id = %s
"""

_DELETE_TRANSLATIONS_SQL = """
delete from translations where entity_type = 'finding' and entity_id = %s
"""

_DELETE_FINDING_SQL = "delete from findings where id = %(finding)s and inspection_id = %(id)s"


@dataclass(frozen=True)
class Addition:
    """Новая запись так, как её хочет видеть вычитывающий."""

    code: str
    level: str
    zone: str
    zone_unusual: bool
    text: str


def _fail(exc: psycopg.Error, what: str) -> ReviseError:
    return ReviseError(
        f"{what} не удалось ({type(exc).__name__}). Ничего не изменилось — "
        f"всё пишется одной транзакцией"
    )


def add_finding(
    inspection_id: str,
    *,
    tenant: str,
    addition: Addition,
    editor: Editor,
    score_of: Callable[[InspectionDetail], Score],
) -> str:
    """Добавить запись в ждущую проверку и положить оценку, посчитанную после замка.

    `editor` — кто добавляет: в той же транзакции правка ложится в журнал правок
    (`inspection_edits`, `0081`) — значения новой записи и оценка до и после.

    Возвращает идентификатор новой записи. Отказ — `ReviseError`: проверки нет,
    она принята, отклонена или историческая (D332), пара «пункт + зона» уже
    занята, записей уже слишком много.
    """
    ident = _require_inspection_id(inspection_id)
    tenant_code = _require_tenant(tenant)
    слова = addition.text.strip()
    if not слова:
        raise ReviseError(
            "Формулировка записи пуста — запись без слов в отчёт не идёт", code="revise_text_empty"
        )
    try:
        with connection(check_environment().dsn) as conn, conn.cursor() as cur:
            cur.execute(_LOCK_SQL, {"id": ident, "tenant": tenant_code})
            замок = cur.fetchone()
            if замок is None:
                raise _refuse_lock(cur, ident, tenant_code)
            язык_речи, происхождение = замок
            if происхождение == ORIGIN_LEGACY:
                raise ReviseError(
                    "Проверка историческая: оценка перенесена из старого отчёта как есть и "
                    "движком не пересчитывается (D332) — записи в неё добавляют инструментами "
                    "загрузки",
                    code="revise_legacy",
                )
            detail = _read_detail(
                cur, reach=own_reach(tenant_code), ident=ident, include_on_review=True
            )
            if detail is None:
                raise ReviseError(
                    f"Проверки {ident} у арендатора {tenant_code} нет", code="inspection_not_found"
                )
            if len(detail.findings) >= MAX_FINDINGS:
                raise ReviseError(
                    f"В проверке уже {MAX_FINDINGS} записей — больше не принимается",
                    code="revise_findings_limit",
                    params={"max": MAX_FINDINGS},
                )
            cur.execute(_NEXT_N_SQL, (ident,))
            row = cur.fetchone()
            n = int(row[0]) if row else 1
            new = FindingRow(
                id=_NIL,
                inspection_id=ident,
                unit_name=detail.inspection.unit_name,
                inspection_date=detail.inspection.inspection_date,
                n=n,
                code=addition.code,
                level=addition.level,
                zone=addition.zone,
                zone_unusual=addition.zone_unusual,
                source="comment",
                lang=str(язык_речи),
                text=слова,
                comment=None,
            )
            score = score_of(replace(detail, findings=(*detail.findings, new)))
            cur.execute(
                _PAIR_TAKEN_SQL,
                {"id": ident, "code": addition.code, "zone": addition.zone, "finding": _NIL},
            )
            занята = cur.fetchone()
            if занята is not None:
                raise ReviseError(
                    f"Пункт {addition.code} в этой зоне уже записан — запись {занята[0]}. "
                    f"Одна пара «пункт + зона» — одна запись",
                    code="revise_pair_taken",
                    params={"code": addition.code},
                )
            cur.execute(
                _INSERT_FINDING_SQL,
                {
                    "id": ident,
                    "n": n,
                    "code": addition.code,
                    "level": addition.level,
                    "zone": addition.zone,
                    "zone_unusual": addition.zone_unusual,
                },
            )
            inserted = cur.fetchone()
            if inserted is None:
                raise ReviseError("База не вернула строку новой записи — ничего не записано")
            finding_id = str(inserted[0])
            cur.execute(_INSERT_TRANSLATION_SQL, ("finding", finding_id, "text", язык_речи, слова))
            _write_score(cur, ident, tenant_code, score)
            record_edit(
                cur,
                inspection_id=ident,
                finding_id=finding_id,
                tenant=tenant_code,
                editor=editor,
                kind="add",
                changes={
                    **finding_changes(
                        None,
                        {
                            "code": addition.code,
                            "level": addition.level,
                            "zone": addition.zone,
                            "zone_unusual": addition.zone_unusual,
                            "text": слова,
                        },
                    ),
                    **score_changes(detail, score),
                },
            )
            conn.commit()
            return finding_id
    except ReviseError:
        raise
    except psycopg.Error as exc:
        raise _fail(exc, "Добавить запись") from exc


def delete_finding(
    inspection_id: str,
    finding_id: str,
    *,
    tenant: str,
    editor: Editor,
    score_of: Callable[[InspectionDetail], Score],
    storage: PhotoStorage,
) -> None:
    """Снять запись ждущей проверки и положить оценку, посчитанную после замка (#1164).

    Уходят строка записи, её формулировки и кадры (строки кадров — каскадом); номера
    других записей не меняются. `score_of` получает проверку БЕЗ этой записи. В той же
    транзакции в журнал правок (`inspection_edits`, `0089`) ложится вид `delete`:
    прежние значения полей записи и оценка до и после. Объекты кадров убираются из
    хранилища после коммита; отказ уборки — в журнал, а не откат (`forget_objects`).

    Отказ — `ReviseError`: проверки нет, она принята, отклонена или историческая
    (D332), такой записи в ней нет.
    """
    ident = _require_inspection_id(inspection_id)
    запись = _require_inspection_id(finding_id)
    tenant_code = _require_tenant(tenant)
    try:
        with connection(check_environment().dsn) as conn, conn.cursor() as cur:
            cur.execute(_LOCK_SQL, {"id": ident, "tenant": tenant_code})
            замок = cur.fetchone()
            if замок is None:
                raise _refuse_lock(cur, ident, tenant_code)
            if замок[1] == ORIGIN_LEGACY:
                raise ReviseError(
                    "Проверка историческая: оценка перенесена из старого отчёта как есть и "
                    "движком не пересчитывается (D332) — записи из неё снимают инструментами "
                    "загрузки",
                    code="revise_legacy",
                )
            detail = _read_detail(
                cur, reach=own_reach(tenant_code), ident=ident, include_on_review=True
            )
            if detail is None:
                raise ReviseError(
                    f"Проверки {ident} у арендатора {tenant_code} нет", code="inspection_not_found"
                )
            прежняя = next((f for f in detail.findings if f.id == запись), None)
            if прежняя is None:
                raise ReviseError("Такой записи в этой проверке нет", code="revise_no_finding")
            score = score_of(
                replace(detail, findings=tuple(f for f in detail.findings if f.id != запись))
            )
            cur.execute(_PHOTOS_OF_FINDING_SQL, (запись, ident))
            объекты = sorted({str(p) for r in cur.fetchall() for p in r if p})
            cur.execute(_DELETE_TRANSLATIONS_SQL, (запись,))
            cur.execute(_DELETE_FINDING_SQL, {"id": ident, "finding": запись})
            if cur.rowcount != 1:
                raise ReviseError(
                    "Запись не снята: проверка уже подтверждена или записи больше нет. "
                    "Ни запись, ни оценка не изменились",
                    code="revise_stale",
                )
            _write_score(cur, ident, tenant_code, score)
            record_edit(
                cur,
                inspection_id=ident,
                finding_id=запись,
                tenant=tenant_code,
                editor=editor,
                kind="delete",
                changes={**finding_removal(прежняя), **score_changes(detail, score)},
            )
            conn.commit()
    except ReviseError:
        raise
    except psycopg.Error as exc:
        raise _fail(exc, "Снять запись") from exc
    forget_objects(storage, объекты)


def attach_photo(
    inspection_id: str,
    finding_id: str,
    *,
    tenant: str,
    data: bytes,
    storage: PhotoStorage,
) -> str:
    """Приложить кадр к записи ждущей проверки; вернуть идентификатор кадра.

    Байты, которые не читаются как изображение, — отказ: оригинал не хранится,
    и «положить как есть» значило бы хранить то, что никто не покажет.
    """
    ident = _require_inspection_id(inspection_id)
    запись = _require_inspection_id(finding_id)
    tenant_code = _require_tenant(tenant)
    try:
        копия = make_preview(data)
    except StorageError as exc:
        raise ReviseError(
            "Кадр не читается как изображение (ожидается JPEG, PNG или WebP) — не приложен",
            code="photo_unreadable",
        ) from exc
    try:
        with connection(check_environment().dsn) as conn, conn.cursor() as cur:
            cur.execute(_LOCK_SQL, {"id": ident, "tenant": tenant_code})
            if cur.fetchone() is None:
                raise _refuse_lock(cur, ident, tenant_code)
            cur.execute(_FINDING_EXISTS_SQL, (запись, ident))
            if cur.fetchone() is None:
                raise ReviseError("Такой записи в этой проверке нет", code="revise_no_finding")
            cur.execute(_COUNT_PHOTOS_SQL, (запись, ident))
            row = cur.fetchone()
            у_записи, у_проверки = (int(row[0]), int(row[1])) if row else (0, 0)
            if у_записи >= MAX_PHOTOS_PER_FINDING:
                raise ReviseError(
                    f"У записи уже {MAX_PHOTOS_PER_FINDING} кадров — больше нельзя",
                    code="photo_limit_finding",
                    params={"max": MAX_PHOTOS_PER_FINDING},
                )
            if у_проверки >= MAX_PHOTOS_PER_INSPECTION:
                raise ReviseError(
                    f"У проверки уже {MAX_PHOTOS_PER_INSPECTION} кадров — больше нельзя",
                    code="photo_limit_inspection",
                    params={"max": MAX_PHOTOS_PER_INSPECTION},
                )
            кадр = str(uuid.uuid4())
            try:
                uri = storage.put(object_key(ident, кадр), копия, content_type=PREVIEW_CONTENT_TYPE)
            except StorageError as exc:
                raise ReviseError(
                    f"Хранилище кадров не приняло кадр ({type(exc).__name__}) — не приложен; "
                    f"повторите позже",
                    code="photo_storage",
                ) from exc
            cur.execute(_INSERT_PHOTO_SQL, (кадр, запись, ident, PHOTO_PREFIX + кадр, uri, uri))
            conn.commit()
            return кадр
    except ReviseError:
        raise
    except psycopg.Error as exc:
        raise _fail(exc, "Приложить кадр") from exc


def detach_photo(inspection_id: str, photo_id: str, *, tenant: str, storage: PhotoStorage) -> None:
    """Снять кадр с записи ждущей проверки: строка уходит, потом — объект в хранилище."""
    ident = _require_inspection_id(inspection_id)
    кадр = _require_inspection_id(photo_id)
    tenant_code = _require_tenant(tenant)
    try:
        with connection(check_environment().dsn) as conn, conn.cursor() as cur:
            cur.execute(_LOCK_SQL, {"id": ident, "tenant": tenant_code})
            if cur.fetchone() is None:
                raise _refuse_lock(cur, ident, tenant_code)
            cur.execute(_PHOTO_PATH_SQL, (кадр, ident))
            найден = cur.fetchone()
            if найден is None:
                raise ReviseError("Такого кадра у записей этой проверки нет", code="photo_no_photo")
            cur.execute(_DELETE_PHOTO_SQL, (кадр, ident))
            if cur.rowcount != 1:
                raise ReviseError(
                    "Кадр не снят — проверка перестала ждать приёмки", code="revise_stale"
                )
            conn.commit()
    except ReviseError:
        raise
    except psycopg.Error as exc:
        raise _fail(exc, "Снять кадр") from exc
    forget_objects(storage, sorted({str(p) for p in найден if p}))
