"""«Где нужно проверить» на экране «Календарь» (D399; с «Главной» в D418, оттуда в D462).

Точки справочника охвата, у которых нет проверок за выбранный период: не
проверявшиеся ни разу — первыми, затем те, что ждут дольше всех. Строится от
справочника, а не от проверок: точка без единой проверки в реестре не
появится вовсе. Охват вошедшего держит запрос (`queries.unit_last_inspections`):
партнёр чужих точек не получает.

Ряд ограничен `TO_CHECK_TOP`, остаток — числом. Отказ базы не роняет реестр:
блок говорит об отказе сам, а не пропадает тишиной.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from src.db import queries
from src.db.errors import DbError
from src.db.reach import Reach

log = logging.getLogger(__name__)

#: Сколько точек показывать в блоке; остальные — числом «и ещё N».
TO_CHECK_TOP = 5


@dataclass(frozen=True)
class ToCheck:
    """Точка, которую за период не проверяли: когда проверяли в последний раз."""

    unit: str
    unit_id: str
    country: str
    city: str
    #: Последняя проверка за всё время; `None` — не проверяли ни разу.
    last: date | None


@dataclass(frozen=True)
class Block:
    """Что показывает блок: ряд точек, остаток числом и признак отказа базы."""

    units: tuple[ToCheck, ...] = ()
    more: int = 0
    failed: bool = False

    @property
    def total(self) -> int:
        return len(self.units) + self.more

    @property
    def shown(self) -> bool:
        """Пустой блок не показывается («всё сделано» ни о чём не говорит); отказ — показывается."""
        return self.failed or bool(self.units)


def pick_units(
    rows: list[tuple[str, str, date | None, int]],
    *,
    geo: dict[str, tuple[str, str]],
    ids: dict[str, str],
    country: str = "",
    city: str = "",
    query: str = "",
) -> tuple[tuple[ToCheck, ...], int]:
    """Точки без проверок за период: не проверявшиеся ни разу, затем давнее всех."""
    ждут = []
    for имя, _, последняя, за_период in rows:
        страна, город = geo.get(имя, ("", ""))
        if за_период or (country and страна != country) or (city and город != city):
            continue
        if query and query.casefold() not in имя.casefold():
            continue
        ждут.append(ToCheck(имя, ids.get(имя, ""), страна, город, последняя))
    ждут.sort(key=lambda т: (т.last is not None, т.last or date.min, т.unit))
    return tuple(ждут[:TO_CHECK_TOP]), max(len(ждут) - TO_CHECK_TOP, 0)


def load(
    *,
    reach: Reach,
    date_from: date | None,
    date_to: date | None,
    country: str = "",
    city: str = "",
    query: str = "",
) -> Block:
    """Блок за период реестра в охвате вошедшего; отбор страны и города — реестра."""
    try:
        geo = queries.unit_geography(reach=reach)
        ids = queries.unit_ids(reach=reach)
        rows = queries.unit_last_inspections(reach=reach, date_from=date_from, date_to=date_to)
    except DbError as exc:
        log.warning("проверки: «где нужно проверить» не прочитано (%s)", exc.__class__.__name__)
        return Block(failed=True)
    units, more = pick_units(rows, geo=geo, ids=ids, country=country, city=city, query=query)
    return Block(units=units, more=more)
