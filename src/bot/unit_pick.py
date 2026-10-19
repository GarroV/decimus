"""Пиццерия проверки — из справочника, а не из написанного (D196).

До D196 любое незнакомое написание заводило при сливе новую точку: на площадке
24.09.2026 рядом лежали «Тбилиси-1» и «Тбилиси -1», две истории у одной
пиццерии. Теперь название сверяется со справочником ещё на старте проверки:
совпало с названием или синонимом — берётся каноничное имя точки; не совпало —
бот предлагает ближайшие точки справочника, и аудитор выбирает. Предлагает, а
не подставляет: «модель предлагает, фиксирует человек».

Справочник недоступен (база не настроена или лежит) — аудитор не встаёт на
точке: название принимается как написано, причина уходит в лог. Отказать в
обходе из-за недоступного справочника значило бы сорвать проверку, ради
которой человек приехал.
"""

from __future__ import annotations

import difflib
import logging
import re
from dataclasses import dataclass
from typing import Any

from src.db import directory, unit_profiles
from src.db.errors import DbError
from src.db.reach import reach_of
from src.domain.geo import COUNTRIES
from src.domain.tenants import may_add_units as may_add_units
from src.domain.unit_name import UnitName
from src.domain.unit_resolve import DirUnit, find_unit, with_reference

logger = logging.getLogger(__name__)

#: Сколько вариантов показывать кнопками. Больше пяти — уже не подсказка, а
#: список, в котором ищут глазами.
SUGGESTIONS_LIMIT = 5

#: Порог похожести `difflib`: ниже — вариант скорее путает, чем помогает.
SIMILARITY_CUTOFF = 0.5

_DASHES = re.compile(r"[-‐-―−]")
_SPACES = re.compile(r"\s+")

#: Кириллица → латиница для ключа сравнения. Справочник сети загружен
#: латиницей («Tbilisi-1»), а аудитор пишет по-русски («Тбилиси-1»): 24.09.2026
#: так бот завёл шесть дублей точек, которые в справочнике уже были.
_TRANSLIT = str.maketrans(
    {
        "а": "a",
        "б": "b",
        "в": "v",
        "г": "g",
        "д": "d",
        "е": "e",
        "ё": "e",
        "ж": "zh",
        "з": "z",
        "и": "i",
        "й": "i",
        "к": "k",
        "л": "l",
        "м": "m",
        "н": "n",
        "о": "o",
        "п": "p",
        "р": "r",
        "с": "s",
        "т": "t",
        "у": "u",
        "ф": "f",
        "х": "h",
        "ц": "c",
        "ч": "ch",
        "ш": "sh",
        "щ": "sch",
        "ъ": "",
        "ы": "y",
        "ь": "",
        "э": "e",
        "ю": "yu",
        "я": "ya",
    }
)


def _key(name: str) -> str:
    """Ключ для сравнения: регистр, виды тире и пробелы не различаются.

    Строже, чем `normalize_unit_name`: там пробелы только схлопываются, и
    «Тбилиси -1» с «Тбилиси-1» — разные ключи. Здесь пробелы и тире убираются вовсе, а
    кириллица читается латиницей: ключ служит поиску, а не хранению.
    """
    return _SPACES.sub("", _DASHES.sub("", name)).casefold().translate(_TRANSLIT)


@dataclass(frozen=True)
class UnitMatch:
    """Итог сверки названия со справочником.

    `name` — каноничное имя точки, когда нашлась; `suggestions` — ближайшие
    имена, когда не нашлась; `checked` — удалось ли вообще свериться.
    """

    name: str | None
    suggestions: tuple[str, ...]
    checked: bool


def match_unit(typed: str, *also: str, tenant: str) -> UnitMatch:
    """Сверить написанное со справочником стран пространства. Отказа не бывает — см. шапку.

    `also` — другие написания того же ввода (каноническое имя разбора): первое давшее
    ответ решает, подсказки строятся по `typed`.
    """
    try:
        # Справочник один (D284): у партнёра — точки его стран, у УК — все.
        # Страны читаются из базы, и её отказ — тот же `DbError`, что ниже.
        units = directory.list_units(reach=reach_of(tenant))
    except DbError as exc:
        logger.warning("справочник точек недоступен, название принято как написано: %s", exc)
        return UnitMatch(name=None, suggestions=(), checked=False)
    return match_in(typed, [(u.name, u.aliases, u.country is not None) for u in units], *also)


def match_in(typed: str, units: list[tuple[str, tuple[str, ...], bool]], *also: str) -> UnitMatch:
    """Сверка по готовому справочнику: `[(имя, синонимы, из базы)]`. Без базы — ради проверки.

    Точное совпадение решает общий поиск (`unit_resolve.find_unit`, D538) — тот же, что у
    MCP, админки и слива. «Из базы» — точка загружена справочником сети (у неё есть
    страна), а не заведена ботом по первому написанию: при совпадении побеждает точка
    базы, иначе старый дубль, заведённый до D196, продолжал бы собирать проверки мимо
    настоящей. Подсказки ближайших — ключом `_key`, он же у клиента мини-аппа.
    """
    if not units:
        # Пустой справочник — сверять не с чем, и это не повод не пускать.
        return UnitMatch(name=None, suggestions=(), checked=False)
    found = find_unit(
        [
            DirUnit(id=имя, name=имя, aliases=синонимы, anchored=база)
            for имя, синонимы, база in units
        ],
        typed,
        *also,
    ).unit
    if found is not None:
        return UnitMatch(name=found.name, suggestions=(), checked=True)
    по_ключу: dict[str, str] = {}
    for имя, синонимы, _ in sorted(units, key=lambda u: not u[2]):
        for написание in (имя, *синонимы):
            по_ключу.setdefault(_key(написание), имя)
    ключ = _key(typed)
    близкие = difflib.get_close_matches(
        ключ, list(по_ключу), n=SUGGESTIONS_LIMIT * 2, cutoff=SIMILARITY_CUTOFF
    )
    варианты: list[str] = []
    for найденный in близкие:
        имя = по_ключу[найденный]
        if имя not in варианты:
            варианты.append(имя)
    return UnitMatch(name=None, suggestions=tuple(варианты[:SUGGESTIONS_LIMIT]), checked=True)


#: Что делать с названием после сверки (`resolve_unit`).
UNIT_KNOWN = "known"
UNIT_NEW = "new"
UNIT_PARTNER_REFUSED = "partner_refused"


@dataclass(frozen=True)
class UnitResolution:
    """Решение по названию: взять `name`, спросить «Новая пиццерия?» или отказать партнёру."""

    status: str
    name: str


def resolve_unit(имя: UnitName, сверка: UnitMatch, space: str) -> UnitResolution:
    """Что делать с названием, сведённым к каноничному, после сверки со справочником.

    Одно решение на бота и на мини-апп (D392). Совпало со справочником — или
    справочник недоступен, и тогда не повод держать аудитора на точке: имя уже
    каноническое. Незнакомое: УК заводит точку («Новая пиццерия?»), партнёр —
    нет, его справочник ведёт УК.
    """
    if сверка.name is not None or not сверка.checked:
        return UnitResolution(UNIT_KNOWN, сверка.name or имя.name)
    if not may_add_units(space):
        return UnitResolution(UNIT_PARTNER_REFUSED, имя.name)
    return UnitResolution(UNIT_NEW, имя.name)


def new_unit_name(имя: UnitName, typed: str) -> UnitName:
    """Имя новой пиццерии по справочнику пиццерий, а не по разбору написанного (D538).

    Строку справочника знают — имя и код Dodo оттуда: «Белград-1» заводится как
    «Belgrade-1», а не как то, во что его превратил словарь городов. Справочник не
    прочитался или строки нет — имя разбора (D233): аудитора это не держит.
    """
    try:
        refs = unit_profiles.refs()
    except DbError as exc:
        logger.warning("справочник пиццерий недоступен, имя новой точки — по разбору: %s", exc)
        return имя
    return with_reference(имя, typed, refs)


def where_suffix(имя: UnitName, lang: str) -> str:
    """Страна точки словом для вопроса «Новая пиццерия?»; незнакомая — пусто."""
    if имя.country is None:
        return ""
    names = COUNTRIES.get(имя.country, {})
    return f" ({names.get(lang) or names.get('en') or имя.country})"


def suggest_index(*, tenant: str) -> dict[str, Any]:
    """Справочник для подсказок на стороне клиента (мини-апп, D414).

    Подсказки по вхождению считаются в телефоне без запроса на каждую букву:
    точки приходят один раз вместе с формой, с уже готовыми ключами `_key`, а
    `dashes` и `translit` позволяют клиенту привести набранное к тому же ключу.
    Ближайшие по написанию (`match_in`) остаются на сервере — их клиент
    спрашивает, только когда вхождений нет. База молчит — точек нет, и клиент
    спрашивает сервер, как раньше.
    """
    try:
        units = directory.list_units(reach=reach_of(tenant))
    except DbError:
        logger.warning("справочник точек недоступен, подсказки с сервера", exc_info=True)
        units = []
    return {
        "units": [
            {"name": u.name, "keys": sorted({_key(n) for n in (u.name, *u.aliases)})} for u in units
        ],
        "limit": SUGGESTIONS_LIMIT,
        "dashes": _DASHES.pattern,
        "translit": {chr(code): value for code, value in _TRANSLIT.items()},
    }


def suggest_units(typed: str, *, tenant: str) -> list[str]:
    """Подсказки к полю названия по мере набора: точки справочника, в которых оно встречается.

    Набранное «bel» находит «Belgrade-1», хотя названием ещё не является, —
    поэтому не `match_unit`, которому нужно полное имя. Нет вхождений — ближайшие
    по написанию (`match_in`). База молчит — подсказок нет, ввод от этого не
    страдает: название проверяется отдельно.
    """
    ключ = _key(typed)
    if not ключ:
        return []
    try:
        units = directory.list_units(reach=reach_of(tenant))
    except DbError:
        logger.warning("справочник точек недоступен, подсказок нет", exc_info=True)
        return []
    found = [
        u.name for u in units if any(ключ in _key(написание) for написание in (u.name, *u.aliases))
    ]
    if found:
        return sorted(found)[:SUGGESTIONS_LIMIT]
    return list(
        match_in(typed, [(u.name, u.aliases, u.country is not None) for u in units]).suggestions
    )
