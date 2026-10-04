"""Экран «Страна»: снимок одной страны и история выбранной пиццерии (D260, D262).

НИЧЕГО НЕ СЧИТАЕТ САМ. Страна — это «Обзор» с отбором по стране: те же
запросы, те же цифры движка. Отдельный подсчёт здесь дал бы второй источник
одних и тех же чисел, и они разошлись бы с «Обзором» при первой правке.

История точки берётся из того же снимка, а не отдельным походом в базу:
снимок уже сужен периодом и отбором, и история обязана жить в том же срезе.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date

from src.db import queries
from src.db.models import InspectionRow

from . import overview
from .overview import Overview, Selection

#: Код страны справочника — две латинские буквы (`GE`, `RS`).
_CODE = re.compile(r"[A-Z]{2}")

#: Снимок страны, которой нет: ни проверок, ни точек, ни потерь.
_EMPTY = Overview(
    units_total=0,
    inspections=(),
    grades=(),
    average=None,
    comparable=True,
    zone_losses=(),
    systemic=(),
    attention=(),
)


@dataclass(frozen=True)
class CountryView:
    """Всё, что показывает экран страны, одним снимком."""

    code: str
    snapshot: Overview
    #: Раскрытая точка. Пусто — ничего не раскрыто.
    unit_id: str = ""
    unit_name: str = ""
    #: Проверки раскрытой точки в срезе, свежие сверху.
    history: tuple[InspectionRow, ...] = ()


def normalize_code(raw: str) -> str:
    """Код страны из адреса. Непонятное — пустая строка, а не отказ."""
    code = raw.strip().upper()
    return code if _CODE.fullmatch(code) else ""


def load(
    *,
    tenant: str,
    limit: int,
    code: str,
    selection: Selection,
    unit_id: str = "",
    today: date | None = None,
) -> CountryView:
    """Снимок страны и, если попросили, история одной её точки.

    Непонятный код (`normalize_code` вернул пусто) — пустой снимок без похода
    в базу. Пустая страна в отборе «Обзора» значит «не сужать», и экран
    страны показал бы под видом страновых цифры всей сети.
    """
    if not code:
        return CountryView(code="", snapshot=_EMPTY)
    snapshot = overview.load(
        tenant=tenant, limit=limit, selection=replace(selection, country=code), today=today
    )
    имя = next((name for name, uid in snapshot.unit_ids.items() if uid == unit_id and unit_id), "")
    history = tuple(row for row in snapshot.inspections if имя and row.unit_name == имя)
    if not history:
        return CountryView(code=code, snapshot=snapshot)
    return CountryView(
        code=code, snapshot=snapshot, unit_id=unit_id, unit_name=имя, history=history
    )


def countries(*, tenant: str) -> tuple[tuple[str, int], ...]:
    """Страны справочника с числом точек, крупные сверху. Точка без страны не считается."""
    счёт: dict[str, int] = {}
    for country, _city in queries.unit_geography(tenant=tenant).values():
        if country:
            счёт[country] = счёт.get(country, 0) + 1
    return tuple(sorted(счёт.items(), key=lambda пара: (-пара[1], пара[0])))
