"""Имя пиццерии «Город-N» по-английски — из написанного как угодно (D233).

Внутри компании точки называются городом и номером: `Yerevan-1`, `Novi Sad-3`,
`Belgrade-5`. Проверяющий пишет как придётся — «ереван 2», «Beograd 5»,
«Подгорца-2», «Երևան 1» — и всё это обязано лечь одной и той же точкой, иначе
история точки рассыпается по написаниям.

Разбор: номер — число в конце, город — всё, что перед ним. Город сверяется со
всеми известными написаниями (`domain.geo`) без регистра, диакритики, пробелов
и тире; не совпал точно — ищется ближайший с запасом на опечатку. Незнакомый
город не отказ: он пишется латиницей, а страну у такой точки узнать неоткуда.
Без номера имени нет — «Земун» или «Yerevan» не называют точку.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass

from .geo import CITIES, CITY_COUNTRY, CITY_SPELLINGS

#: Насколько написание города может разойтись с известным и ещё считаться
#: опечаткой. Замерено на тестах: «Еревна»/«ереван» — 0.83, «Бари»/«бар» — 0.86,
#: поэтому короткие названия сверяются строже (`SHORT_CUTOFF`).
SIMILARITY_CUTOFF = 0.8
#: Для городов до четырёх букв: одна буква там — уже другой город (Бар, Бали).
SHORT_CUTOFF = 0.95
SHORT_NAME = 4

_NUMBER = re.compile(r"^(?P<city>.*?\D)[\s\-–—_#№.,:/]*0*(?P<n>\d{1,3})\s*$")

#: Буквы, которые NFKD не раскладывает на основу и знак.
_LETTERS = str.maketrans({"ı": "i", "ł": "l", "đ": "d", "ø": "o", "ß": "ss", "ə": "e"})

_CYRILLIC = str.maketrans(
    {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
        "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
        "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
        "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
        "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    }
)  # fmt: skip


@dataclass(frozen=True)
class UnitName:
    """Каноническое имя точки и то, что о ней из него известно."""

    name: str
    city: str | None
    country: str | None


def _ascii(text: str) -> str:
    разложено = unicodedata.normalize("NFKD", text.translate(_LETTERS))
    return "".join(c for c in разложено if not unicodedata.combining(c))


def _key(text: str) -> str:
    """Ключ сверки: без регистра, диакритики и всего, что не буква."""
    return "".join(c for c in _ascii(text.casefold()) if c.isalpha())


def _spellings() -> dict[str, str]:
    ключи: dict[str, str] = {}
    for code, names in CITIES.items():
        for написание in (code, *names.values(), *CITY_SPELLINGS.get(code, ())):
            ключи.setdefault(_key(написание), code)
    return ключи


_BY_KEY = _spellings()


def _city(raw: str) -> str | None:
    ключ = _key(raw)
    if not ключ:
        return None
    if ключ in _BY_KEY:
        return _BY_KEY[ключ]
    порог = SHORT_CUTOFF if len(ключ) <= SHORT_NAME else SIMILARITY_CUTOFF
    близкие = difflib.get_close_matches(ключ, list(_BY_KEY), n=1, cutoff=порог)
    return _BY_KEY[близкие[0]] if близкие else None


def _latin(raw: str) -> str:
    """Незнакомый город латиницей: «Кутаиси» → «Kutaisi»."""
    слова = _ascii(raw.casefold().translate(_CYRILLIC)).split()
    return " ".join(w[:1].upper() + w[1:] for w in слова)


def canonical_unit(typed: str) -> UnitName | None:
    """`City-N` по-английски из написанного; `None` — в написанном нет города с номером."""
    найдено = _NUMBER.match(typed.strip())
    if найдено is None:
        return None
    сырой_город = найдено["city"].strip(" -–—_#№.,:/")
    номер = int(найдено["n"])
    if not _key(сырой_город) or номер == 0:
        return None
    код = _city(сырой_город)
    if код is None:
        return UnitName(name=f"{_latin(сырой_город)}-{номер}", city=None, country=None)
    город = _ascii(CITIES[код]["en"])
    return UnitName(name=f"{город}-{номер}", city=код, country=CITY_COUNTRY.get(код))
