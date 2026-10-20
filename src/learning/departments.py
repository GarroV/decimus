"""Дерево подразделений iSpring → страны, пиццерии, офисы; сопоставление с рейтингами.

Дерево: `Dodo Brands` → `Dodo Pizza` → страна `Dodo Pizza - Romania` → подразделение
пиццерии `Brasov-1: Brasov - Dodo Pizza` (иногда без `: …`, например `Vagharshapat-1`).
Офисы (`Kontor: Tallinn - Dodo Pizza`, `Antalya Office`) лежат на том же уровне, что и
пиццерии: пиццерия — та, чья короткая часть до `:` оканчивается номером точки.

Первая версия — только ветка `Dodo Pizza` (остальные бренды и партнёры вне объёма).
Подразделение глубже пиццерии не встречается; если появится, оно не учитывается и
попадает в счётчик `ignored` загрузки — молча не теряется.

Сопоставление с пиццерией рейтингов — по короткой части и стране (`ratings.matching`);
несопоставленная остаётся пиццерией без `unit_dodo_id` и выходит на экран отдельным списком.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from src.ratings.countries import country_code
from src.ratings.matching import KnownUnit, match_unit

from .ispring import Department

BRAND = "Dodo Pizza"
COUNTRY_PREFIX = "Dodo Pizza - "
#: Страны, которых нет в справочнике сети (`ratings.countries`), но есть в iSpring: без
#: записи подразделение страны и все её пиццерии выпали бы из загрузки.
_EXTRA_COUNTRIES = {"Moldova": "MD"}
_POINT_NUMBER = re.compile(r"-\s*\d+$")

KIND_COUNTRY = "country"
KIND_PIZZERIA = "pizzeria"
KIND_OFFICE = "office"


@dataclass(frozen=True)
class Mapped:
    """Подразделение, как оно ляжет в `learning.departments`."""

    id: str
    title: str
    kind: str
    country_code: str | None
    parent_id: str | None
    unit_dodo_id: str | None = None


def short_name(name: str) -> str:
    """Часть названия до первого `:` — `Brasov-1` из `Brasov-1: Brasov - Dodo Pizza`."""
    return name.split(":", 1)[0].strip()


def is_pizzeria_name(name: str) -> bool:
    return bool(_POINT_NUMBER.search(short_name(name)))


def _path(dept: Department, by_id: dict[str, Department]) -> list[Department]:
    chain: list[Department] = []
    seen: set[str] = set()
    node: Department | None = dept
    while node is not None and node.id not in seen:
        seen.add(node.id)
        chain.append(node)
        node = by_id.get(node.parent_id) if node.parent_id else None
    return chain[::-1]


def map_departments(
    departments: Sequence[Department], known: Sequence[KnownUnit]
) -> tuple[list[Mapped], int]:
    """Страны, пиццерии и офисы ветки `Dodo Pizza`; второе — сколько подразделений вне разбора."""
    by_id = {d.id: d for d in departments}
    countries: dict[str, str] = {}
    mapped: list[Mapped] = []
    ignored = 0
    ordered = sorted(departments, key=lambda d: len(_path(d, by_id)))
    for dept in ordered:
        path = _path(dept, by_id)
        if len(path) < 3 or path[1].name != BRAND:
            continue
        if len(path) == 3:
            title = dept.name.removeprefix(COUNTRY_PREFIX)
            code = country_code(title) or _EXTRA_COUNTRIES.get(title)
            if code is None:
                ignored += 1
                continue
            countries[dept.id] = code
            mapped.append(Mapped(dept.id, dept.name, KIND_COUNTRY, code, dept.parent_id))
        elif len(path) == 4 and path[2].id in countries:
            code = countries[path[2].id]
            if is_pizzeria_name(dept.name):
                title = short_name(dept.name)
                unit = match_unit(title, code, known)
                mapped.append(Mapped(dept.id, title, KIND_PIZZERIA, code, dept.parent_id, unit))
            else:
                mapped.append(
                    Mapped(dept.id, short_name(dept.name), KIND_OFFICE, code, dept.parent_id)
                )
        else:
            ignored += 1
    return mapped, ignored
