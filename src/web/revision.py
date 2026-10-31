"""Правка записи на приёмке с пересчётом отчёта (D200).

Аудитор записал «грязный пол в горячем цехе» вместо «в зале» — вычитывающий
чинит это на экране приёмки, а не снятием проверки. Путь один и короткий:

1. исправление сверяется с чек-листом ТОЙ версии, по которой проверку
   считали: пункт есть и это пункт нарушения, класс для него допустим, зона
   есть в справочнике версии;
2. проверка с исправленной записью пересчитывается движком
   (`src/report/rescore.py`) — второй арифметики нет;
3. запись и новая оценка кладутся одной транзакцией (`src/db/revise.py`).

Зона вне списка пункта принимается с пометкой «необычная» — так же, как в
боте, когда зону назвал человек (D206): зона — там, где продукт.

Правит только своё пространство (D283): проверка читается охватом «только
свои» пространства вошедшего, и чужая — даже та, что вошедшему видна на
чтение, — отвечает «такой проверки нет». Тот же заслон стоит и в запросе
записи (`src/db/revise.py`).
"""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping, Sequence

from src.db import queries, review_edit, revise
from src.db.config import load_storage_settings
from src.db.errors import ReviseError, StorageError
from src.db.inspection_edits import Editor
from src.db.models import FindingRow, InspectionDetail
from src.db.previews import make_preview
from src.db.reach import reach_of
from src.db.storage import PhotoStorage, S3PhotoStorage
from src.domain import item_label
from src.domain.models import READING_MAX_C, READING_MIN_C
from src.domain.tenants import canonical_tenant
from src.report.letters import LetterError
from src.report.letters import sources as letter_sources
from src.report.rescore import rescore

from .errors import MethodologyRefused
from .review import VIOLATION, checklist_of
from .texts import t

logger = logging.getLogger(__name__)

#: Порог слов в формулировке: запись печатается в отчёте партнёру строкой.
MAX_TEXT = 1000


def _levels(item: Mapping[str, str]) -> tuple[str, ...]:
    сырые = (item.get("levels") or "").replace(";", ",").split(",")
    return tuple(x.strip().upper() for x in сырые if x.strip())


def _zones(item: Mapping[str, str]) -> tuple[str, ...]:
    return tuple(z.strip() for z in (item.get("zones") or "").split(",") if z.strip())


def _checked_entry(
    detail: InspectionDetail,
    inspection_id: str,
    *,
    lang: str,
    code: str,
    level: str,
    zone: str,
    text: str,
) -> tuple[str, str, str, str, bool]:
    """Сверить запись с чек-листом версии проверки: общее для правки и добавления.

    Возвращает `(код, класс, зона, слова, необычная_зона)`; отказ — `ReviseError`.
    """
    код, класс, зона, слова = code.strip(), level.strip().upper(), zone.strip(), text.strip()
    if not слова:
        raise ReviseError(
            "Формулировка записи пуста — запись без слов в отчёт не идёт", code="revise_text_empty"
        )
    if len(слова) > MAX_TEXT:
        raise ReviseError(
            f"Формулировка длиннее {MAX_TEXT} знаков",
            code="revise_text_long",
            params={"max": MAX_TEXT},
        )
    try:
        состав = checklist_of(detail.inspection, lang=lang)
    except MethodologyRefused as exc:
        # Подробность (имена переменных окружения, пути хранилища) — в журнал
        # сервера, не на экран: человеку она ничего не даёт, а устройство стенда выдаёт.
        logger.warning("правка записи: чек-лист проверки %s не прочитан: %s", inspection_id, exc)
        raise ReviseError(
            "Чек-лист этой проверки не прочитан, сверять не с чем", code="revise_checklist"
        ) from exc
    пункт = next((i for i in состав.items if str(i.get("id", "")) == код), None)
    # Человеку пункт называется меткой («Порядок 13»), не кодом (20.10.2026).
    метка = item_label.label(код, item_label.from_csv(состав.items), lang)
    if пункт is None or (пункт.get("kind") or VIOLATION).strip() != VIOLATION:
        raise ReviseError(
            f"Пункта нарушения {код} в чек-листе версии этой проверки нет",
            code="revise_no_item",
            params={"item": метка},
        )
    if класс not in _levels(пункт):
        raise ReviseError(
            f"Класс {класс} для пункта {код} не предусмотрен — допустимы: "
            f"{', '.join(_levels(пункт)) or 'никакие'}",
            code="revise_bad_level",
            params={"level": класс, "item": метка, "allowed": ", ".join(_levels(пункт)) or "—"},
        )
    зоны_версии = {str(z.get("code", "")) for z in состав.zones}
    if зона not in зоны_версии:
        raise ReviseError(
            f"Зоны {зона} в чек-листе версии этой проверки нет",
            code="revise_no_zone",
            params={"zone": зона},
        )
    свои = _zones(пункт)
    необычная = bool(свои) and свои != ("*",) and зона not in свои
    return код, класс, зона, слова, необычная


def _pair_taken_labelled(exc: ReviseError, detail: InspectionDetail, lang: str) -> ReviseError:
    """Отказ «пара пункт + зона занята» из базы несёт код пункта; человеку — его метка.

    База метками не владеет (методика — не её данные), поэтому подмена на границе веба.
    Остальные отказы проходят как есть.
    """
    if exc.code != "revise_pair_taken":
        return exc
    try:
        тексты = item_label.from_csv(checklist_of(detail.inspection, lang=lang).items)
    except MethodologyRefused:
        return exc
    код = str(exc.params.get("code", ""))
    return ReviseError(
        str(exc),
        code=exc.code,
        params={**exc.params, "code": item_label.label(код, тексты, lang)},
    )


def _editable(inspection_id: str, *, tenant: str, lang: str) -> InspectionDetail:
    """Проверка своего пространства, ждущая приёмки и не историческая — или `ReviseError`."""
    detail = queries.get_inspection(inspection_id, reach=reach_of(tenant), include_on_review=True)
    if detail is None:
        raise ReviseError("Такой проверки нет", code="inspection_not_found")
    if canonical_tenant(detail.inspection.tenant_code) != canonical_tenant(tenant):
        # Охват отдаёт и чужие проверки на чтение (D289); исправлять — только своё.
        raise ReviseError(
            "Исправлять можно только проверки своего пространства", code="revise_foreign"
        )
    if not detail.inspection.on_review:
        raise ReviseError(
            "Проверка уже принята — записи принятой не исправляются (D200). "
            "Поправить можно только шапку, под журналом",
            code="revise_accepted",
        )
    if detail.inspection.is_legacy:
        # Историческая (D332): чек-листа её методики в хранилище нет и не
        # будет, а оценку движок не пересчитывает никогда — сверять запись не
        # с чем, и это не поломка, а свойство проверки.
        raise ReviseError(t("revise.legacy", lang), code="revise_legacy")
    return detail


def editable(inspection_id: str, *, tenant: str, lang: str) -> InspectionDetail:
    """Та же проверка «можно ли править», для тех, кто готовит правку (D535)."""
    return _editable(inspection_id, tenant=tenant, lang=lang)


def is_unchanged(
    finding: FindingRow, *, code: str, level: str, zone: str, text: str, reading: str = ""
) -> bool:
    """Совпадает ли форма правки с записью как есть.

    Форма правки записи ещё и меняет кадры; когда исправлять в записи нечего,
    пересчёт и строка в истории правок не нужны (D535). Показание — число или
    пусто, как в `reading_of`; нечитаемое — отказ, а не «не изменилось».
    """
    return (
        finding.code == code.strip()
        and finding.level == level.strip().upper()
        and (finding.zone or "") == zone.strip()
        and (finding.text or "").strip() == text.strip()
        and finding.reading_c == reading_of(reading)
    )


def reading_of(raw: str) -> float | None:
    """Показание термометра из формы вычитки (#855, D495): пусто — замера нет.

    Запятая принимается как десятичный знак — так число пишут на точке. Не
    число или вне пределов термометра — отказ, а не тихое «замера нет»:
    вычитывающий правит факт, и молча потерянная правка хуже отказа.
    """
    text = raw.strip().replace(",", ".")
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        value = math.nan
    if not math.isfinite(value) or not READING_MIN_C <= value <= READING_MAX_C:
        raise ReviseError(f"Показание «{raw}» не похоже на температуру", code="revise_reading")
    return value


def revise_card(
    inspection_id: str,
    finding_id: str,
    *,
    tenant: str,
    lang: str,
    editor: Editor,
    code: str,
    level: str,
    zone: str,
    text: str,
    reading: str = "",
    code_text_reviewed: bool = False,
) -> None:
    """Исправить запись ждущей проверки и пересчитать её. Отказ — `ReviseError`.

    `editor` — кто правит: правка пишется в журнал правок (F-134), УК и партнёр одинаково."""
    показание = reading_of(reading)
    detail = _editable(inspection_id, tenant=tenant, lang=lang)
    прежняя = next((f for f in detail.findings if f.id == finding_id), None)
    if прежняя is None:
        raise ReviseError("Такой записи в этой проверке нет", code="revise_no_finding")
    код, класс, зона, слова, необычная = _checked_entry(
        detail, inspection_id, lang=lang, code=code, level=level, zone=zone, text=text
    )

    if (
        прежняя.code != code.strip()
        and (прежняя.text or "").strip()
        and (прежняя.text or "").strip() == text.strip()
        and not code_text_reviewed
    ):
        raise ReviseError(t("proofread.review_required", lang), code="revise_text_review")

    бумаги = letter_sources()
    try:
        revise.revise_finding(
            inspection_id,
            finding_id,
            tenant=tenant,
            editor=editor,
            revision=revise.Revision(
                code=код,
                level=класс,
                zone=зона,
                zone_unusual=необычная,
                text=слова,
                reading_c=показание,
            ),
            # Движок считает ВНУТРИ транзакции правки, после замка проверки:
            # соседняя правка той же проверки уже учтена (`src/db/revise.py`).
            score_of=lambda current: rescore(current, papers=бумаги),
        )
    except LetterError as exc:
        raise ReviseError(
            "Пересчитать проверку не удалось, запись не тронута", code="revise_recalc"
        ) from exc
    except ReviseError as exc:
        raise _pair_taken_labelled(exc, detail, lang) from exc


def add_card(
    inspection_id: str,
    *,
    tenant: str,
    lang: str,
    editor: Editor,
    code: str,
    level: str,
    zone: str,
    text: str,
    photo: bytes | None = None,
    more_photos: Sequence[bytes] = (),
    storage: PhotoStorage | None = None,
) -> str:
    """Добавить запись в ждущую проверку и пересчитать её (D465). Отказ — `ReviseError`.

    Сверка с чек-листом и пересчёт — те же, что у правки (`_checked_entry`,
    `rescore`): второй арифметики и второго свода правил нет. Кадр (необязателен)
    проверяется ДО записи — не читается как изображение, запись не заводится;
    приложен он после неё отдельной операцией, и её отказ не откатывает уже
    посчитанную запись (`ReviseError` тогда несёт, что запись добавлена).
    """
    detail = _editable(inspection_id, tenant=tenant, lang=lang)
    код, класс, зона, слова, необычная = _checked_entry(
        detail, inspection_id, lang=lang, code=code, level=level, zone=zone, text=text
    )
    кадры = [x for x in (photo, *more_photos) if x is not None]
    for кадр in кадры:
        try:
            make_preview(кадр)
        except StorageError as exc:
            raise ReviseError(t("photo.unreadable", lang), code="photo_unreadable") from exc
    бумаги = letter_sources()
    try:
        finding_id = review_edit.add_finding(
            inspection_id,
            tenant=tenant,
            editor=editor,
            addition=review_edit.Addition(
                code=код, level=класс, zone=зона, zone_unusual=необычная, text=слова
            ),
            score_of=lambda current: rescore(current, papers=бумаги),
        )
    except LetterError as exc:
        raise ReviseError(
            "Пересчитать проверку не удалось, запись не добавлена", code="revise_recalc"
        ) from exc
    except ReviseError as exc:
        raise _pair_taken_labelled(exc, detail, lang) from exc
    for кадр in кадры:
        try:
            attach_photo(inspection_id, finding_id, tenant=tenant, data=кадр, storage=storage)
        except ReviseError as exc:
            raise ReviseError(
                t("add.photo_failed", lang, reason=str(exc)),
                code="add_photo_failed",
                params={"reason": exc},
            ) from exc
    return finding_id


def delete_card(
    inspection_id: str,
    finding_id: str,
    *,
    tenant: str,
    lang: str,
    editor: Editor,
    storage: PhotoStorage | None = None,
) -> None:
    """Снять ошибочно занесённую запись ждущей проверки и пересчитать её (#1164).

    Права и пересчёт те же, что у правки: `_editable` и `rescore` — второй арифметики
    нет. Номера остальных записей не сдвигаются. Отказ — `ReviseError`."""
    _editable(inspection_id, tenant=tenant, lang=lang)
    бумаги = letter_sources()
    try:
        review_edit.delete_finding(
            inspection_id,
            finding_id,
            tenant=tenant,
            editor=editor,
            score_of=lambda current: rescore(current, papers=бумаги),
            storage=_store(storage),
        )
    except LetterError as exc:
        raise ReviseError(
            "Пересчитать проверку не удалось, запись не снята", code="revise_recalc"
        ) from exc


def _store(storage: PhotoStorage | None) -> PhotoStorage:
    return storage if storage is not None else S3PhotoStorage(load_storage_settings())


def attach_photo(
    inspection_id: str,
    finding_id: str,
    *,
    tenant: str,
    data: bytes,
    storage: PhotoStorage | None = None,
) -> str:
    """Приложить кадр к записи ждущей проверки (D465). Отказ — `ReviseError`."""
    return review_edit.attach_photo(
        inspection_id, finding_id, tenant=tenant, data=data, storage=_store(storage)
    )


def detach_photo(
    inspection_id: str, photo_id: str, *, tenant: str, storage: PhotoStorage | None = None
) -> None:
    """Снять кадр с записи ждущей проверки (D465). Отказ — `ReviseError`."""
    review_edit.detach_photo(inspection_id, photo_id, tenant=tenant, storage=_store(storage))


def replace_photo(
    inspection_id: str,
    finding_id: str,
    photo_id: str,
    *,
    tenant: str,
    data: bytes,
    storage: PhotoStorage | None = None,
) -> None:
    """Заменить кадр: новый прикладывается ПЕРВЫМ, старый снимается после.

    Не вышло приложить — старый на месте; не вышло снять старый — у записи оба,
    и это видно, а не потеряно: доказательство важнее аккуратности.
    """
    store = _store(storage)
    attach_photo(inspection_id, finding_id, tenant=tenant, data=data, storage=store)
    detach_photo(inspection_id, photo_id, tenant=tenant, storage=store)


def change_photos(
    inspection_id: str,
    finding_id: str,
    *,
    tenant: str,
    add: Sequence[bytes] = (),
    remove: Sequence[str] = (),
    storage: PhotoStorage | None = None,
) -> None:
    """Кадры записи одним заходом: сначала приложить новые, потом снять убранные (D535).

    Порядок тот же, что у `replace_photo`: не вышло приложить — старые на
    месте, доказательство важнее аккуратности. Первый отказ прекращает работу;
    что успело лечь — осталось, и вызывающий говорит об этом словами.
    """
    store = _store(storage)
    for data in add:
        attach_photo(inspection_id, finding_id, tenant=tenant, data=data, storage=store)
    for photo_id in remove:
        detach_photo(inspection_id, photo_id, tenant=tenant, storage=store)
