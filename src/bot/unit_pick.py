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

from src.db import directory
from src.db.errors import DbError

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


def match_unit(typed: str, *, tenant: str = directory.DEFAULT_TENANT) -> UnitMatch:
    """Сверить написанное со справочником. Отказа не бывает — см. шапку модуля."""
    try:
        units = directory.list_units(tenant=tenant)
    except DbError as exc:
        logger.warning("справочник точек недоступен, название принято как написано: %s", exc)
        return UnitMatch(name=None, suggestions=(), checked=False)
    return match_in(typed, [(u.name, u.aliases, u.country is not None) for u in units])


def match_in(typed: str, units: list[tuple[str, tuple[str, ...], bool]]) -> UnitMatch:
    """Сверка по готовому справочнику: `[(имя, синонимы, из базы)]`. Без базы — ради проверки.

    «Из базы» — точка загружена справочником сети (у неё есть страна), а не
    заведена ботом по первому написанию. При совпадении ключей побеждает точка
    базы: иначе старый дубль, заведённый до D196, продолжал бы собирать
    проверки мимо настоящей точки.
    """
    if not units:
        # Пустой справочник — сверять не с чем, и это не повод не пускать.
        return UnitMatch(name=None, suggestions=(), checked=False)
    по_ключу: dict[str, str] = {}
    # Сначала точки базы, потом заведённые ботом: `setdefault` оставляет первую.
    for имя, синонимы, _ in sorted(units, key=lambda u: not u[2]):
        for написание in (имя, *синонимы):
            по_ключу.setdefault(_key(написание), имя)
    ключ = _key(typed)
    if ключ in по_ключу:
        return UnitMatch(name=по_ключу[ключ], suggestions=(), checked=True)
    близкие = difflib.get_close_matches(
        ключ, list(по_ключу), n=SUGGESTIONS_LIMIT * 2, cutoff=SIMILARITY_CUTOFF
    )
    варианты: list[str] = []
    for найденный in близкие:
        имя = по_ключу[найденный]
        if имя not in варианты:
            варианты.append(имя)
    return UnitMatch(name=None, suggestions=tuple(варианты[:SUGGESTIONS_LIMIT]), checked=True)
