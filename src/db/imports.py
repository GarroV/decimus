"""Загрузка исторической проверки поштучно: черновик, записи, кадры (D305–D310).

Коллега с Claude разбирает старый отчёт (Битрикс, PDF, таблица) и вносит его
через MCP: заводит черновик, добавляет, правит и снимает записи, сверяет
посчитанную оценку с напечатанной в старом отчёте и подтверждает сам (D308).
Подтверждение — общее (`accept.py`): загруженная после него обычная проверка
своей версии методики (D306), а запрос экшн-плана не открывается (D310).

**Оценку считает движок, правила записи — тоже движок.** Этот модуль чисел не
считает и правил записи не знает: вызывающий передаёт `apply` — функцию, которая
применяет команду движка к проверке, прочитанной ПОСЛЕ замка, и возвращает
оценку и записи, как их увидел движок (`src/report/rescore.apply_command`).
Здесь кладётся ровно то, что движок вернул: номер новой записи, пометка
необычной зоны (D206), класс, приведённый к верхнему регистру.

**Правки одного черновика идут по очереди** — тот же замок строки, что у правки
на приёмке (`revise.py`) и у подтверждения (`accept.py`), и запись с оценкой
ложатся одной транзакцией. Порознь они разошлись бы при первом обрыве.

**Правится только загруженный черновик своего пространства.** Условие стоит в
самом замке: `tenant_code`, `origin = 'import'`, `status = 'draft'`, не
отклонена. Проверка обхода (`origin = 'field'`) этими дверями не правится и не
удаляется никогда — у неё своя приёмка в вебе; принятую не правит никто
(политики `0004`). Чужое пространство отвечает тем же «нет», что несуществующая.

Ходит под ролью приложения: правка и удаление черновика ей разрешены политиками
`0004` ровно потому, что он ещё `draft`.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol

import psycopg

from ..domain.models import Score
from ..domain.tenants import HQ_TENANT
from .config import check_environment
from .directory import resolve_unit_id
from .errors import HistoryImportError, StorageError
from .models import ORIGIN_IMPORT, InspectionDetail
from .previews import PREVIEW_CONTENT_TYPE, make_preview
from .push import _INSERT_TRANSLATION_SQL
from .queries import _read_detail, _require_inspection_id, _require_tenant
from .reach import own_reach
from .revise import _write_score
from .storage import PhotoStorage, object_key

logger = logging.getLogger(__name__)

#: Чата у загрузки нет (0038): ноль однозначно значит «не из бота».
IMPORT_CHAT_ID = 0

#: Префикс ссылки кадра, принесённого загрузкой. Колонка называется
#: `telegram_file_id` по истории, а значит «откуда кадр»: `walk:` — обход в
#: мини-аппе (`domain.uploads`), `import:` — загрузка. По sha256 байтов — тот
#: же кадр дважды к одной записи не ляжет.
PHOTO_PREFIX = "import:"


class Applied(Protocol):
    """Итог команды движка: оценка и записи после команды в форме движка.

    Протокол, а не свой класс: итог отдаёт `src/report/rescore.apply_command`,
    и вторая копия той же пары здесь разошлась бы с ней молча.
    """

    @property
    def score(self) -> Score: ...

    @property
    def findings(self) -> tuple[dict[str, Any], ...]: ...


#: Применить команду движка к проверке, прочитанной после замка.
Apply = Callable[[InspectionDetail], Applied]


@dataclass(frozen=True)
class NewDraft:
    """Шапка загружаемой проверки — то, что напечатано в старом отчёте."""

    tenant: str
    unit: str
    inspection_date: date
    kind: str
    checklist_code: str
    checklist_version: str
    auditor: str
    report_lang: str
    #: Язык, на котором записаны формулировки (язык речи, D025) — у загрузки
    #: это язык исходного документа.
    speech_lang: str
    reported_pct: float | None = None
    reported_grade: str | None = None
    source_ref: str | None = None


@dataclass(frozen=True)
class DraftRow:
    """Черновик загрузки в перечне."""

    id: str
    unit_name: str
    inspection_date: date
    checklist_code: str
    checklist_version: str
    pct: float
    grade: str
    reported_pct: float | None
    reported_grade: str | None
    source_ref: str | None
    findings_count: int
    pushed_at: str


@dataclass(frozen=True)
class ImportHead:
    """Поля проверки, которых нет в общем чтении: происхождение и сверка (0038)."""

    origin: str
    status: str
    retracted: bool
    reported_pct: float | None
    reported_grade: str | None
    source_ref: str | None


# Вставка черновика. Оценка-заглушка живёт ровно до конца этой же транзакции:
# следом движок считает проверку по её версии, и `_write_score` кладёт его
# итог. Отказ движка откатывает вставку целиком — черновика без оценки движка
# не бывает.
_INSERT_DRAFT_SQL = """
insert into inspections (
    tenant_code, unit_id, chat_id, kind, inspection_date, report_lang,
    ui_lang, speech_lang, checklist_version, checklist_code, auditor,
    pct, grade, source_fingerprint, status, origin,
    reported_pct, reported_grade, source_ref
) values (
    %(tenant_code)s, %(unit_id)s, %(chat_id)s, %(kind)s, %(inspection_date)s, %(report_lang)s,
    %(speech_lang)s, %(speech_lang)s, %(checklist_version)s, %(checklist_code)s, %(auditor)s,
    0, '', %(fingerprint)s, 'draft', 'import',
    %(reported_pct)s, %(reported_grade)s, %(source_ref)s
)
returning id
"""

# Замок загруженного черновика своего пространства — первое действие каждой
# правки. Всё, что не загруженный черновик этого пространства, замка не
# получает, а почему — объясняет `_refuse_lock` вторым, обычным запросом.
_LOCK_SQL = """
select i.speech_lang
from inspections i
where i.id = %(id)s and i.tenant_code = %(tenant)s and i.origin = 'import'
  and i.status = 'draft' and i.retracted_at is null
for update
"""

_SELECT_HEAD_SQL = """
select i.origin, i.status, i.retracted_at is not null,
       i.reported_pct, i.reported_grade, i.source_ref
from inspections i
where i.id = %(id)s and i.tenant_code = %(tenant)s
"""

_INSERT_FINDING_SQL = """
insert into findings (inspection_id, n, code, level, zone, zone_unusual, repeat)
values (%(id)s, %(n)s, %(code)s, %(level)s, %(zone)s, %(zone_unusual)s, %(repeat)s)
returning id
"""

_UPDATE_FINDING_SQL = """
update findings
set code = %(code)s, level = %(level)s, zone = %(zone)s,
    zone_unusual = %(zone_unusual)s, repeat = %(repeat)s
where id = %(finding)s and inspection_id = %(id)s
"""

_DELETE_TRANSLATION_SQL = """
delete from translations where entity_type = %s and entity_id = %s and field = %s
"""

_DELETE_FINDING_SQL = "delete from findings where id = %(finding)s and inspection_id = %(id)s"

_PHOTOS_OF_FINDING_SQL = """
select storage_path from photos where finding_id = %s and storage_path is not null
"""

_PHOTOS_OF_INSPECTION_SQL = """
select storage_path from photos where inspection_id = %s and storage_path is not null
"""

_DELETE_TRANSLATIONS_OF_INSPECTION_SQL = """
delete from translations
where (entity_type = 'inspection' and entity_id = %(id)s)
   or (entity_type = 'finding'
       and entity_id in (select f.id from findings f where f.inspection_id = %(id)s))
"""

_DELETE_DRAFT_SQL = """
delete from inspections
where id = %(id)s and tenant_code = %(tenant)s and origin = 'import'
  and status = 'draft' and retracted_at is null
"""

_PHOTO_TAKEN_SQL = "select 1 from photos where finding_id = %s and telegram_file_id = %s"

_INSERT_PHOTO_SQL = """
insert into photos (
    id, finding_id, inspection_id, telegram_file_id, storage_path, preview_path, uploaded_at
) values (%s, %s, %s, %s, %s, %s, now())
"""

_LIST_DRAFTS_SQL = """
select i.id, u.name, i.inspection_date, i.checklist_code, i.checklist_version,
       i.pct, i.grade, i.reported_pct, i.reported_grade, i.source_ref,
       (select count(*) from findings f where f.inspection_id = i.id),
       i.pushed_at
from inspections i
join units u on u.id = i.unit_id
where i.tenant_code = %(tenant)s and i.origin = 'import'
  and i.status = 'draft' and i.retracted_at is null
order by i.pushed_at desc
limit %(limit)s
"""

#: Предел перечня черновиков и он же — предел НЕподтверждённых черновиков
#: пространства. Коллега грузит поштучно: сотня ждущих — уже сигнал, что
#: что-то не подтверждается, а не рабочая очередь. Без предела на заведение
#: зациклившийся агент наплодил бы строк без счёта.
MAX_DRAFTS = 200

#: Пределы содержимого черновика (D305, ресурсы). Живая проверка — до ~140
#: пунктов методики, плюс D0 и рекомендации, которые пару не занимают: 300
#: записей с запасом покрывают любой настоящий отчёт и отсекают цикл агента.
MAX_FINDINGS = 300
#: Кадры: к записи — как в боте по смыслу «несколько ракурсов», к проверке —
#: потолок места в хранилище на один черновик (сжатая копия ~100–200 КБ).
MAX_PHOTOS_PER_FINDING = 10
MAX_PHOTOS_PER_INSPECTION = 300
#: Длина формулировки, комментария, имени аудитора и ссылки на источник —
#: держится и здесь, а не только в обработчике MCP: слой базы зовут не только
#: из MCP. Формулировка — тот же порог, что у правки на приёмке.
MAX_WORDING = 1000
MAX_AUDITOR = 200
MAX_SOURCE_REF = 1000

_COUNT_OPEN_DRAFTS_SQL = """
select count(*) from inspections
where tenant_code = %s and origin = 'import' and status = 'draft' and retracted_at is null
"""

#: Счёт черновиков и вставка нового — под замком пространства на транзакцию,
#: иначе параллельные заведения проскочили бы предел все разом.
_DRAFTS_LOCK_SQL = "select pg_advisory_xact_lock(hashtext('import-drafts:' || %s))"

_COUNT_PHOTOS_SQL = """
select count(*) filter (where finding_id = %s), count(*) from photos where inspection_id = %s
"""


def _connect() -> psycopg.Connection[Any]:
    return psycopg.connect(check_environment().dsn)


def _refused(exc: psycopg.Error, что: str) -> HistoryImportError:
    """Отказ базы — тип, а не текст драйвера: в тексте бывает адрес базы."""
    return HistoryImportError(
        f"{что} не удалось ({type(exc).__name__}). Ни запись, ни оценка не изменились — "
        f"они пишутся одной транзакцией"
    )


# --- черновик -----------------------------------------------------------------


def create_draft(spec: NewDraft, *, apply_score: Callable[[InspectionDetail], Score]) -> str:
    """Завести черновик загрузки без записей и с оценкой движка; вернуть его id.

    Точка берётся только из справочника УК (с картой синонимов, T092):
    загрузка точек не заводит. Опечатка в названии иначе завела бы вторую
    пиццерию, и история одной точки разошлась бы на две (D035, D234). Страну
    точки сверяет сторож схемы (0030) — точка чужой страны даёт отказ.
    """
    tenant = _require_tenant(spec.tenant)
    _check_length(spec.auditor, field="auditor", limit=MAX_AUDITOR)
    _check_length(spec.source_ref, field="source_ref", limit=MAX_SOURCE_REF)
    try:
        with _connect() as conn:
            _check_open_drafts(conn, tenant)
            ident = _insert_draft(conn, spec, tenant)
            with conn.cursor() as cur:
                detail = _locked_detail(cur, ident, tenant)
                _write_score(cur, ident, tenant, apply_score(detail))
            conn.commit()
            return ident
    except HistoryImportError:
        raise
    except psycopg.Error as exc:
        raise _refused(exc, "Завести черновик") from exc


def _check_length(value: str | None, *, field: str, limit: int) -> None:
    if value is not None and len(value) > limit:
        raise HistoryImportError(f"Поле {field} длиннее {limit} знаков — ничего не записано")


def _check_wording(wording: Wording) -> None:
    _check_length(wording.text, field="text", limit=MAX_WORDING)
    _check_length(wording.comment, field="comment", limit=MAX_WORDING)


def _check_open_drafts(conn: psycopg.Connection[Any], tenant: str) -> None:
    with conn.cursor() as cur:
        cur.execute(_DRAFTS_LOCK_SQL, (tenant,))
        cur.execute(_COUNT_OPEN_DRAFTS_SQL, (tenant,))
        row = cur.fetchone()
    if row is not None and int(row[0]) >= MAX_DRAFTS:
        raise HistoryImportError(
            f"В пространстве уже {MAX_DRAFTS} неподтверждённых черновиков загрузки — новый "
            f"не заведён. Подтвердите или удалите ждущие (import_list_drafts)"
        )


def _insert_draft(conn: psycopg.Connection[Any], spec: NewDraft, tenant: str) -> str:
    with conn.cursor() as cur:
        unit_id = resolve_unit_id(conn, spec.unit, tenant=HQ_TENANT)
        if unit_id is None:
            raise _unit_refused(spec.unit, tenant)
        try:
            cur.execute(
                _INSERT_DRAFT_SQL,
                {
                    "tenant_code": tenant,
                    "unit_id": unit_id,
                    "chat_id": IMPORT_CHAT_ID,
                    "kind": spec.kind,
                    "inspection_date": spec.inspection_date,
                    "report_lang": spec.report_lang,
                    "speech_lang": spec.speech_lang,
                    "checklist_version": spec.checklist_version,
                    "checklist_code": spec.checklist_code,
                    "auditor": spec.auditor,
                    # По одному на черновик: у загрузки нет повторного слива,
                    # от которого отпечаток по содержимому защищает (0038).
                    "fingerprint": f"import:{uuid.uuid4().hex}",
                    "reported_pct": spec.reported_pct,
                    "reported_grade": spec.reported_grade,
                    "source_ref": spec.source_ref,
                },
            )
        except psycopg.errors.RaiseException as exc:
            # На вставке так отказывает только сторож точки (0030): точка не из
            # стран пространства. Ответ тот же, что у точки вне справочника.
            raise _unit_refused(spec.unit, tenant) from exc
        row = cur.fetchone()
        if row is None:
            raise HistoryImportError("Postgres не вернул строку черновика после вставки")
        return str(row[0])


def _unit_refused(unit: str, tenant: str) -> HistoryImportError:
    """Один отказ на «точки нет» и «точка чужой страны» — как у слива (ревью #340, п.10)."""
    return HistoryImportError(
        f"Пиццерии «{unit}» нет в справочнике стран пространства {tenant}. Загрузка точек "
        f"не заводит: назовите точку так, как она записана в справочнике (список точек — "
        f"в вебе, раздел пиццерий); новую пиццерию заводит только УК (D234)"
    )


def _locked_detail(cur: Any, ident: str, tenant: str) -> InspectionDetail:
    """Замок загруженного черновика своего пространства — и проверка, прочитанная после него.

    Всё, что читается и считается ниже, читается после замка: соседняя правка
    того же черновика уже записана целиком или ещё не началась.
    """
    cur.execute(_LOCK_SQL, {"id": ident, "tenant": tenant})
    if cur.fetchone() is None:
        raise _refuse_lock(cur, ident, tenant)
    detail = _read_detail(cur, reach=own_reach(tenant), ident=ident, include_on_review=True)
    if detail is None:
        raise HistoryImportError(f"Проверки {ident} у этого доступа нет")
    return detail


def _refuse_lock(cur: Any, ident: str, tenant: str) -> HistoryImportError:
    """Почему замок не дали — словами, которые объясняют, что делать."""
    cur.execute(_SELECT_HEAD_SQL, {"id": ident, "tenant": tenant})
    шапка = cur.fetchone()
    if шапка is None:
        return HistoryImportError(
            f"Проверки {ident} у этого доступа нет: её не существует или она чужого "
            f"пространства. Черновики загрузки перечисляет import_list_drafts"
        )
    происхождение, статус, отклонена = шапка[0], шапка[1], шапка[2]
    if происхождение != ORIGIN_IMPORT:
        return HistoryImportError(
            f"Проверка {ident} — проверка обхода из бота, а не загруженная. Инструменты "
            f"загрузки правят и удаляют только загруженные черновики; обойдённую правят "
            f"на приёмке в вебе (D200)"
        )
    if отклонена:
        return HistoryImportError(f"Проверка {ident} отклонена — её записи не правятся")
    if статус != "draft":
        return HistoryImportError(
            f"Проверка {ident} уже подтверждена — принятая не правится и не удаляется "
            f"(D200). Неверную принятую отклоняют и загружают заново"
        )
    return HistoryImportError(f"Проверка {ident} сейчас не правится")


def import_head(inspection_id: str, *, tenant: str) -> ImportHead | None:
    """Происхождение и оценка из старого отчёта. `None` — проверки у пространства нет."""
    ident = _require_inspection_id(inspection_id)
    tenant_code = _require_tenant(tenant)
    try:
        with _connect() as conn, conn.cursor() as cur:
            cur.execute(_SELECT_HEAD_SQL, {"id": ident, "tenant": tenant_code})
            row = cur.fetchone()
    except psycopg.Error as exc:
        raise HistoryImportError(
            f"Шапку проверки {ident} прочитать не удалось ({type(exc).__name__})"
        ) from exc
    if row is None:
        return None
    return ImportHead(
        origin=str(row[0]),
        status=str(row[1]),
        retracted=bool(row[2]),
        reported_pct=None if row[3] is None else float(row[3]),
        reported_grade=row[4],
        source_ref=row[5],
    )


def list_drafts(*, tenant: str, limit: int = MAX_DRAFTS) -> list[DraftRow]:
    """Загруженные черновики пространства, свежие первыми."""
    tenant_code = _require_tenant(tenant)
    предел = min(max(int(limit), 1), MAX_DRAFTS)
    try:
        with _connect() as conn, conn.cursor() as cur:
            cur.execute(_LIST_DRAFTS_SQL, {"tenant": tenant_code, "limit": предел})
            rows = cur.fetchall()
    except psycopg.Error as exc:
        raise HistoryImportError(
            f"Черновики загрузки прочитать не удалось ({type(exc).__name__})"
        ) from exc
    return [
        DraftRow(
            id=str(r[0]),
            unit_name=str(r[1]),
            inspection_date=r[2],
            checklist_code=str(r[3]),
            checklist_version=str(r[4]),
            pct=float(r[5]),
            grade=str(r[6]),
            reported_pct=None if r[7] is None else float(r[7]),
            reported_grade=r[8],
            source_ref=r[9],
            findings_count=int(r[10]),
            pushed_at=r[11].isoformat(),
        )
        for r in rows
    ]


def discard_draft(inspection_id: str, *, tenant: str) -> tuple[str, ...]:
    """Удалить загруженный черновик целиком; вернуть ссылки кадров, которые убрать из хранилища.

    Только `origin = 'import'` и только `draft` — условие стоит и в замке, и в
    самом удалении. Записи, кадры, сведения уходят каскадом (`0001`, `0009`);
    формулировки ссылок на строку не держат и удаляются явно.
    """
    ident = _require_inspection_id(inspection_id)
    tenant_code = _require_tenant(tenant)
    try:
        with _connect() as conn, conn.cursor() as cur:
            _locked_detail(cur, ident, tenant_code)
            cur.execute(_PHOTOS_OF_INSPECTION_SQL, (ident,))
            кадры = tuple(str(r[0]) for r in cur.fetchall())
            cur.execute(_DELETE_TRANSLATIONS_OF_INSPECTION_SQL, {"id": ident})
            cur.execute(_DELETE_DRAFT_SQL, {"id": ident, "tenant": tenant_code})
            if cur.rowcount != 1:
                raise HistoryImportError(
                    f"Черновик {ident} не удалён: удалено строк — {cur.rowcount}, ожидалась одна"
                )
            conn.commit()
            return кадры
    except HistoryImportError:
        raise
    except psycopg.Error as exc:
        raise HistoryImportError(
            f"Удалить черновик {ident} не удалось ({type(exc).__name__}). Он остался как был"
        ) from exc


# --- записи -------------------------------------------------------------------


@dataclass(frozen=True)
class Wording:
    """Формулировка и комментарий записи. `None` — не трогать; пусто у комментария — снять."""

    text: str | None
    comment: str | None


def add_finding(
    inspection_id: str, *, tenant: str, wording: Wording, apply: Apply
) -> tuple[int, Applied]:
    """Добавить запись в загруженный черновик; вернуть её номер и итог движка."""
    ident = _require_inspection_id(inspection_id)
    tenant_code = _require_tenant(tenant)
    if not (wording.text or "").strip():
        raise HistoryImportError("Формулировка записи пуста — запись без слов в отчёт не идёт")
    _check_wording(wording)
    try:
        with _connect() as conn, conn.cursor() as cur:
            detail = _locked_detail(cur, ident, tenant_code)
            if len(detail.findings) >= MAX_FINDINGS:
                raise HistoryImportError(
                    f"В черновике уже {MAX_FINDINGS} записей — больше не принимается. "
                    f"Настоящий отчёт столько не содержит: проверьте, не повторяются ли записи"
                )
            итог = apply(detail)
            были = {f.n for f in detail.findings}
            новые = [f for f in итог.findings if int(f.get("n", 0)) not in были]
            if len(новые) != 1:
                raise HistoryImportError(
                    f"Движок вернул {len(новые)} новых записей вместо одной — ничего не записано"
                )
            запись = новые[0]
            cur.execute(_INSERT_FINDING_SQL, {"id": ident, **_engine_fields(запись)})
            row = cur.fetchone()
            if row is None:
                raise HistoryImportError("Postgres не вернул строку записи после вставки")
            _write_wording(cur, str(row[0]), ident, wording)
            _write_score(cur, ident, tenant_code, итог.score)
            conn.commit()
            return int(запись["n"]), итог
    except HistoryImportError:
        raise
    except psycopg.Error as exc:
        raise _refused(exc, "Добавить запись") from exc


def edit_finding(
    inspection_id: str, n: int, *, tenant: str, wording: Wording, apply: Apply
) -> Applied:
    """Исправить запись загруженного черновика по номеру; оценку пересчитывает движок."""
    ident = _require_inspection_id(inspection_id)
    tenant_code = _require_tenant(tenant)
    if wording.text is not None and not wording.text.strip():
        raise HistoryImportError("Формулировка записи пуста — запись без слов в отчёт не идёт")
    _check_wording(wording)
    try:
        with _connect() as conn, conn.cursor() as cur:
            detail = _locked_detail(cur, ident, tenant_code)
            прежняя = _finding_by_n(detail, n)
            итог = apply(detail)
            запись = next((f for f in итог.findings if int(f.get("n", 0)) == n), None)
            if запись is None:
                raise HistoryImportError(f"Движок потерял запись #{n} — ничего не записано")
            cur.execute(
                _UPDATE_FINDING_SQL, {"id": ident, "finding": прежняя, **_engine_fields(запись)}
            )
            if cur.rowcount != 1:
                raise HistoryImportError(f"Запись #{n} не исправлена — ничего не записано")
            _write_wording(cur, прежняя, ident, wording)
            _write_score(cur, ident, tenant_code, итог.score)
            conn.commit()
            return итог
    except HistoryImportError:
        raise
    except psycopg.Error as exc:
        raise _refused(exc, "Исправить запись") from exc


def remove_finding(
    inspection_id: str, n: int, *, tenant: str, apply: Apply
) -> tuple[Applied, tuple[str, ...]]:
    """Снять запись с черновика вместе с её формулировками и кадрами.

    Возвращает итог движка и ссылки кадров записи — убрать их из хранилища
    вызывающий обязан после этой транзакции: строки кадров уходят каскадом.
    """
    ident = _require_inspection_id(inspection_id)
    tenant_code = _require_tenant(tenant)
    try:
        with _connect() as conn, conn.cursor() as cur:
            detail = _locked_detail(cur, ident, tenant_code)
            запись = _finding_by_n(detail, n)
            итог = apply(detail)
            if any(int(f.get("n", 0)) == n for f in итог.findings):
                raise HistoryImportError(f"Движок не снял запись #{n} — ничего не записано")
            cur.execute(_PHOTOS_OF_FINDING_SQL, (запись,))
            кадры = tuple(str(r[0]) for r in cur.fetchall())
            for поле in ("text", "comment"):
                cur.execute(_DELETE_TRANSLATION_SQL, ("finding", запись, поле))
            cur.execute(_DELETE_FINDING_SQL, {"id": ident, "finding": запись})
            if cur.rowcount != 1:
                raise HistoryImportError(f"Запись #{n} не снята — ничего не записано")
            _write_score(cur, ident, tenant_code, итог.score)
            conn.commit()
            return итог, кадры
    except HistoryImportError:
        raise
    except psycopg.Error as exc:
        raise _refused(exc, "Снять запись") from exc


def _finding_by_n(detail: InspectionDetail, n: int) -> str:
    for f in detail.findings:
        if f.n == n:
            return f.id
    есть = ", ".join(f"#{f.n}" for f in detail.findings) or "ни одной"
    raise HistoryImportError(f"Записи #{n} в этом черновике нет. Есть: {есть}")


def _engine_fields(запись: dict[str, Any]) -> dict[str, object]:
    """Поля записи так, как их положил движок, — в колонки `findings`."""
    return {
        "n": int(запись["n"]),
        "code": str(запись["qid"]),
        "level": str(запись["level"]),
        "zone": str(запись["zone"]),
        "zone_unusual": bool(запись.get("zone_unusual", False)),
        "repeat": bool(запись.get("repeat", False)),
    }


def _write_wording(cur: Any, finding_id: str, ident: str, wording: Wording) -> None:
    """Формулировка и комментарий — строками переводов на языке речи проверки (D025)."""
    язык = _speech_lang(cur, ident)
    for поле, значение in (("text", wording.text), ("comment", wording.comment)):
        if значение is None:
            continue
        if значение.strip():
            cur.execute(
                _INSERT_TRANSLATION_SQL, ("finding", finding_id, поле, язык, значение.strip())
            )
        else:
            cur.execute(_DELETE_TRANSLATION_SQL, ("finding", finding_id, поле))


def _speech_lang(cur: Any, ident: str) -> str:
    cur.execute("select speech_lang from inspections where id = %s", (ident,))
    row = cur.fetchone()
    if row is None:
        raise HistoryImportError(f"Проверки {ident} больше нет")
    return str(row[0])


# --- кадры (D309) -------------------------------------------------------------


def photo_ref(data: bytes) -> str:
    """Ссылка кадра загрузки: `import:<sha256>` — один и тот же кадр опознаётся."""
    return PHOTO_PREFIX + hashlib.sha256(data).hexdigest()


def add_photo(
    inspection_id: str, n: int, *, tenant: str, data: bytes, storage: PhotoStorage
) -> str:
    """Приложить кадр к записи черновика и сразу положить его в хранилище.

    Кадр загрузки не ждёт дозагрузки: байты уже в руках, поэтому объект кладётся
    в хранилище ДО строки, а строка ложится сразу со ссылкой. Хранилище не
    приняло — строки нет, отказ; строку не приняла база — объект остаётся
    сиротой, и его находит сверка хранилища (`storage_reconcile`). Дозагрузка
    бота (`pending_photo_uploads`) такой кадр не увидит никогда: качать его из
    телеграма было бы неоткуда.

    В хранилище ложится сжатая копия (D250, D253), как у кадров обхода. Байты,
    которые не читаются как изображение, — отказ: оригинал не хранится, и
    «положить как есть» значило бы хранить то, что никто не покажет.
    """
    ident = _require_inspection_id(inspection_id)
    tenant_code = _require_tenant(tenant)
    try:
        копия = make_preview(data)
    except StorageError as exc:
        raise HistoryImportError(
            "Кадр не читается как изображение (ожидается JPEG, PNG или WebP) — не приложен"
        ) from exc
    ссылка = photo_ref(data)
    try:
        with _connect() as conn, conn.cursor() as cur:
            detail = _locked_detail(cur, ident, tenant_code)
            запись = _finding_by_n(detail, n)
            _check_photo_room(cur, запись, ident, n)
            cur.execute(_PHOTO_TAKEN_SQL, (запись, ссылка))
            if cur.fetchone() is not None:
                raise HistoryImportError(f"Этот кадр уже приложен к записи #{n}")
            кадр = str(uuid.uuid4())
            try:
                uri = storage.put(object_key(ident, кадр), копия, content_type=PREVIEW_CONTENT_TYPE)
            except StorageError as exc:
                raise HistoryImportError(
                    f"Хранилище кадров не приняло кадр ({type(exc).__name__}) — не приложен; "
                    f"повторите позже"
                ) from exc
            cur.execute(_INSERT_PHOTO_SQL, (кадр, запись, ident, ссылка, uri, uri))
            conn.commit()
            return кадр
    except HistoryImportError:
        raise
    except psycopg.Error as exc:
        raise _refused(exc, "Приложить кадр") from exc


def _check_photo_room(cur: Any, finding_id: str, ident: str, n: int) -> None:
    """Предел кадров записи и черновика — под тем же замком, что и вставка."""
    cur.execute(_COUNT_PHOTOS_SQL, (finding_id, ident))
    row = cur.fetchone()
    у_записи, у_проверки = (int(row[0]), int(row[1])) if row is not None else (0, 0)
    if у_записи >= MAX_PHOTOS_PER_FINDING:
        raise HistoryImportError(
            f"У записи #{n} уже {MAX_PHOTOS_PER_FINDING} кадров — больше не прикладывается"
        )
    if у_проверки >= MAX_PHOTOS_PER_INSPECTION:
        raise HistoryImportError(
            f"У черновика уже {MAX_PHOTOS_PER_INSPECTION} кадров — больше не прикладывается"
        )


def forget_objects(storage: PhotoStorage, paths: Sequence[str]) -> int:
    """Убрать объекты снятых кадров из хранилища; вернуть, сколько не удалось.

    Строки уже удалены своей транзакцией, поэтому отказ здесь — не откат, а
    сирота в хранилище: он уходит в журнал, и его находит сверка хранилища.
    """
    from .storage import key_of_uri

    не_убрано = 0
    for path in paths:
        try:
            storage.delete(key_of_uri(path))
        except (StorageError, ValueError) as exc:
            не_убрано += 1
            logger.warning("объект снятого кадра загрузки не убран: %r", exc)
    return не_убрано
