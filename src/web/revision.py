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

from src.db import queries, revise
from src.db.errors import ReviseError
from src.db.reach import reach_of
from src.domain.tenants import canonical_tenant
from src.report.letters import LetterError
from src.report.letters import sources as letter_sources
from src.report.rescore import rescore

from .errors import MethodologyRefused
from .review import VIOLATION, checklist_of

logger = logging.getLogger(__name__)

#: Порог слов в формулировке: запись печатается в отчёте партнёру строкой.
MAX_TEXT = 1000


def _levels(item: Mapping[str, str]) -> tuple[str, ...]:
    сырые = (item.get("levels") or "").replace(";", ",").split(",")
    return tuple(x.strip().upper() for x in сырые if x.strip())


def _zones(item: Mapping[str, str]) -> tuple[str, ...]:
    return tuple(z.strip() for z in (item.get("zones") or "").split(",") if z.strip())


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
    прежняя = next((f for f in detail.findings if f.id == finding_id), None)
    if прежняя is None:
        raise ReviseError("Такой записи в этой проверке нет")
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
