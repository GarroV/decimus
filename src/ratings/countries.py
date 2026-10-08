"""Страны выгрузок рейтинга → код ISO. Охват — IMF без РФ, КЗ и УЗ (D318).

Выгрузки пишут страну то по-русски («Беларусь»), то по-английски («Turkey»).
Карта — справочник сети (`src.domain.geo.COUNTRIES`) плюс страны, которых в
справочнике Decimus нет, и встреченные написания.
"""

from __future__ import annotations

from src.domain.geo import COUNTRIES

#: Не IMF (D318): строки с ними отбрасываются по стране, а не по «Конвейеру» —
#: у части стран IMF конвейер в выгрузке пустой.
EXCLUDED = frozenset({"RU", "KZ", "UZ"})

_EXTRA: dict[str, dict[str, str]] = {
    "BY": {"ru": "Беларусь", "en": "Belarus"},
    "RU": {"ru": "Россия", "en": "Russia"},
    "KZ": {"ru": "Казахстан", "en": "Kazakhstan"},
    "UZ": {"ru": "Узбекистан", "en": "Uzbekistan"},
}

#: Написания из выгрузок сверх русского и английского названий справочника.
_ALIASES = {
    "turkey": "TR",
    "turkiye": "TR",
    "белоруссия": "BY",
    "kyrgyz republic": "KG",
    "united arab emirates": "AE",
}

NAMES: dict[str, dict[str, str]] = {**COUNTRIES, **_EXTRA}


def _key(name: str) -> str:
    return " ".join(name.split()).casefold()


_BY_NAME: dict[str, str] = {
    **{_key(title): code for code, titles in NAMES.items() for title in titles.values()},
    **_ALIASES,
}


def country_code(name: str) -> str | None:
    """Код ISO по названию на любом из двух языков; незнакомое — `None`."""
    return _BY_NAME.get(_key(name))


def country_names(code: str) -> tuple[str, str]:
    """Название по-русски и по-английски; незнакомый код — сам код."""
    titles = NAMES.get(code, {})
    return titles.get("ru", code), titles.get("en", code)


def is_excluded(code: str) -> bool:
    return code in EXCLUDED
