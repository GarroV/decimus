"""Страны выгрузок рейтинга → код ISO. Охват — IMF без РФ, КЗ и УЗ (D318).

Выгрузки пишут страну то по-русски («Беларусь»), то по-английски («Turkey»).
Карта — справочник сети (`src.domain.geo.COUNTRIES`) плюс страны, которых в
справочнике Decimus нет, и встреченные написания.
"""

from __future__ import annotations

import unicodedata

from src.domain.geo import COUNTRIES

#: Не IMF (D318): строки с ними отбрасываются по стране, а не по «Конвейеру» —
#: у части стран IMF конвейер в выгрузке пустой.
EXCLUDED = frozenset({"RU", "KZ", "UZ"})

_EXTRA: dict[str, dict[str, str]] = {
    "BY": {"ru": "Беларусь", "en": "Belarus"},
    "RU": {"ru": "Россия", "en": "Russia"},
    "KZ": {"ru": "Казахстан", "en": "Kazakhstan"},
    "UZ": {"ru": "Узбекистан", "en": "Uzbekistan"},
    # Есть в листе РКО «Качество по пиццериям», в справочнике Decimus нет.
    "MX": {"ru": "Мексика", "en": "Mexico"},
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


#: Флаг 🇳🇬 — пара символов категории `So`; эмодзи — `So` с селектором
#: вариантов (`Mn` U+FE0F) и склейкой (`Cf` U+200D). Лист контроля пишет страну
#: с флагом: «🇳🇬 Nigeria».
_EMOJI_PARTS = frozenset({"So", "Cf"})
_VARIATION_SELECTOR = "\ufe0f"


def _key(name: str) -> str:
    bare = "".join(
        ch
        for ch in name
        if ch != _VARIATION_SELECTOR and unicodedata.category(ch) not in _EMOJI_PARTS
    )
    return " ".join(bare.split()).casefold()


_BY_NAME: dict[str, str] = {
    **{_key(title): code for code, titles in NAMES.items() for title in titles.values()},
    **_ALIASES,
}


def country_code(name: str) -> str | None:
    """Код ISO по названию на любом из двух языков; флаг и эмодзи не мешают.

    Незнакомое — `None`.
    """
    return _BY_NAME.get(_key(name))


def country_names(code: str) -> tuple[str, str]:
    """Название по-русски и по-английски; незнакомый код — сам код."""
    titles = NAMES.get(code, {})
    return titles.get("ru", code), titles.get("en", code)


def is_excluded(code: str) -> bool:
    return code in EXCLUDED
