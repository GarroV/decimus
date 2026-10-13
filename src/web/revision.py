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
from collections.abc import Mapping

from src.db import queries, review_edit, revise
from src.db.config import load_storage_settings
from src.db.errors import ReviseError, StorageError
from src.db.models import InspectionDetail
from src.db.previews import make_preview
from src.db.reach import reach_of
from src.db.storage import PhotoStorage, S3PhotoStorage
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
        raise ReviseError("Формулировка записи пуста — запись без слов в отчёт не идёт")
    if len(слова) > MAX_TEXT:
        raise ReviseError(f"Формулировка длиннее {MAX_TEXT} знаков")
    try:
        состав = checklist_of(detail.inspection, lang=lang)
    except MethodologyRefused as exc:
        # Подробность (имена переменных окружения, пути хранилища) — в журнал
        # сервера, не на экран: человеку она ничего не даёт, а устройство стенда выдаёт.
        logger.warning("правка записи: чек-лист проверки %s не прочитан: %s", inspection_id, exc)
        raise ReviseError("Чек-лист этой проверки не прочитан, сверять не с чем") from exc
    пункт = next((i for i in состав.items if str(i.get("id", "")) == код), None)
    if пункт is None or (пункт.get("kind") or VIOLATION).strip() != VIOLATION:
        raise ReviseError(f"Пункта нарушения {код} в чек-листе версии этой проверки нет")
    if класс not in _levels(пункт):
        raise ReviseError(
            f"Класс {класс} для пункта {код} не предусмотрен — допустимы: "
            f"{', '.join(_levels(пункт)) or 'никакие'}"
        )
    зоны_версии = {str(z.get("code", "")) for z in состав.zones}
    if зона not in зоны_версии:
        raise ReviseError(f"Зоны {зона} в чек-листе версии этой проверки нет")
    свои = _zones(пункт)
    необычная = bool(свои) and свои != ("*",) and зона not in свои
    return код, класс, зона, слова, необычная


def _editable(inspection_id: str, *, tenant: str, lang: str) -> InspectionDetail:
    """Проверка своего пространства, ждущая приёмки и не историческая — или `ReviseError`."""
    detail = queries.get_inspection(inspection_id, reach=reach_of(tenant), include_on_review=True)
    if detail is None:
        raise ReviseError("Такой проверки нет")
    if canonical_tenant(detail.inspection.tenant_code) != canonical_tenant(tenant):
        # Охват отдаёт и чужие проверки на чтение (D289); исправлять — только своё.
        raise ReviseError("Исправлять можно только проверки своего пространства")
    if not detail.inspection.on_review:
        raise ReviseError(
            "Проверка уже принята — записи принятой не исправляются (D200). "
            "Поправить можно только шапку, под журналом"
        )
    if detail.inspection.is_legacy:
        # Историческая (D332): чек-листа её методики в хранилище нет и не
        # будет, а оценку движок не пересчитывает никогда — сверять запись не
        # с чем, и это не поломка, а свойство проверки.
        raise ReviseError(t("revise.legacy", lang))
    return detail


def revise_card(
    inspection_id: str,
    finding_id: str,
    *,
    tenant: str,
    lang: str,
    code: str,
    level: str,
    zone: str,
    text: str,
) -> None:
    """Исправить запись ждущей проверки и пересчитать её. Отказ — `ReviseError`."""
    detail = _editable(inspection_id, tenant=tenant, lang=lang)
    прежняя = next((f for f in detail.findings if f.id == finding_id), None)
    if прежняя is None:
        raise ReviseError("Такой записи в этой проверке нет")
    код, класс, зона, слова, необычная = _checked_entry(
        detail, inspection_id, lang=lang, code=code, level=level, zone=zone, text=text
    )

    бумаги = letter_sources()
    try:
        revise.revise_finding(
            inspection_id,
            finding_id,
            tenant=tenant,
            revision=revise.Revision(
                code=код, level=класс, zone=зона, zone_unusual=необычная, text=слова
            ),
            # Движок считает ВНУТРИ транзакции правки, после замка проверки:
            # соседняя правка той же проверки уже учтена (`src/db/revise.py`).
            score_of=lambda current: rescore(current, papers=бумаги),
        )
    except LetterError as exc:
        raise ReviseError(f"Пересчитать проверку не удалось, запись не тронута: {exc}") from exc


def add_card(
    inspection_id: str,
    *,
    tenant: str,
    lang: str,
    code: str,
    level: str,
    zone: str,
    text: str,
    photo: bytes | None = None,
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
    if photo is not None:
        try:
            make_preview(photo)
        except StorageError as exc:
            raise ReviseError(t("photo.unreadable", lang)) from exc
    бумаги = letter_sources()
    try:
        finding_id = review_edit.add_finding(
            inspection_id,
            tenant=tenant,
            addition=review_edit.Addition(
                code=код, level=класс, zone=зона, zone_unusual=необычная, text=слова
            ),
            score_of=lambda current: rescore(current, papers=бумаги),
        )
    except LetterError as exc:
        raise ReviseError(f"Пересчитать проверку не удалось, запись не добавлена: {exc}") from exc
    if photo is not None:
        try:
            attach_photo(inspection_id, finding_id, tenant=tenant, data=photo, storage=storage)
        except ReviseError as exc:
            raise ReviseError(t("add.photo_failed", lang, reason=str(exc))) from exc
    return finding_id


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
