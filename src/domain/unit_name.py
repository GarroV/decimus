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

#: Сколько знаков в названии точки принимают бот и веб-админка.
#:
#: Число замерено, а не выбрано на вкус. Имя файла отчёта движок собирает как
#: «Аудит <точка> - <аудитор> - <дата>.pdf»; кириллица в UTF-8 — два байта на
#: знак, а предел имени файла на ext4 (площадка продукта, D053) — 255 байт.
#: С аудитором в 40 знаков на название остаётся около шестидесяти. Проверено
#: фактическим прогоном: на 300 знаках сборка отчёта падает с «File name too
#: long», и узнаёт об этом аудитор в конце проверки, когда переснимать поздно.
UNIT_NAME_LIMIT = 60

#: Тот же предел, но БАЙТАМИ (T128, переоткрытая часть, issue #103): в знаках
#: он не ловит тяжёлые символы — 60 эмодзи это те же 60 знаков (в предел выше
#: укладываются), но уже 240 байт, то есть одно название съедает больше, чем
#: весь бюджет имени файла. Число — часть общего бюджета: постоянная часть
#: формулы имени файла (слово, два разделителя, дата, «.pdf») занимает 31 байт
#: (замерено, см. комментарий у `AUDITOR_NAME_BYTE_LIMIT` в `../auditor.py`),
#: остаётся 224 байта на название точки и имя аудитора вместе. Точке — 120
#: байт (ровно 60 кириллических знаков — старым живым названиям запрет не
#: мешает, старое поведение не меняется), аудитору — 100.
UNIT_NAME_BYTE_LIMIT = 120

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


#: Турецкие буквы: İ после `casefold` даёт «i» с точкой-знаком, ı не раскладывается вовсе.
_FOLD_LETTERS = str.maketrans(
    {"İ": "I", "ı": "i", "Ş": "S", "ş": "s", "Ğ": "G", "ğ": "g", "Ç": "C", "ç": "c"}
    | {"Ö": "O", "ö": "o", "Ü": "U", "ü": "u"}
)


def fold_unit_name(name: str) -> str:
    """Ключ сверки имени точки: «İzmir-4», «Izmır-4», «izmir-4» — одна пиццерия.

    Турецкие буквы сводятся к латинским, диакритика снимается, пробелы схлопываются,
    регистр — `casefold`. Номер точки не трогается: «Izmir-4» ≠ «İzmir-5».
    """
    разложено = unicodedata.normalize("NFKD", name.translate(_FOLD_LETTERS))
    bare = "".join(c for c in разложено if not unicodedata.combining(c))
    return " ".join(bare.split()).casefold()


#: Написания, которыми одну и ту же букву передают по-разному («Могилёв» — Mogilev и
#: Mogilyov, «Харьков» — Kharkov и Harkov); порядок важен: длинные раньше коротких.
_VARIANTS = (
    ("shch", "sh"), ("tch", "ch"), ("yo", "e"), ("ye", "e"), ("yu", "u"), ("ya", "a"),
    ("kh", "h"), ("ts", "c"), ("y", "i"), ("j", "i"), ("w", "v"),
)  # fmt: skip


def unit_name_skeleton(name: str) -> str:
    """Ключ поиска имени точки на другом алфавите: «Новополоцк-1» и «Novopolotsk-1» сходятся.

    Кириллица читается латиницей, разночтения («yo»/«e», «kh»/«h») сводятся к одному
    виду, остаются буквы и цифры. Ключ грубее `fold_unit_name` и годится только для
    поиска в справочнике, где совпавший вторым ходом id перепроверяется на однозначность;
    номер точки в нём сохраняется, поэтому «-1» не становится «-2».
    """
    text = fold_unit_name(name).translate(_CYRILLIC)
    for variant, short in _VARIANTS:
        text = text.replace(variant, short)
    return "".join(c for c in text if c.isalnum())


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


#: Почему написанное не годится названием точки. Значения совпадают с хвостом
#: ключей текстов бота (`start.<проблема>`): бот и мини-апп (D392) отказывают
#: одними и теми же словами, а проверка — одна, здесь.
PROBLEM_EMPTY = "unit_empty"
PROBLEM_TOO_LONG = "unit_too_long"
PROBLEM_TOO_LONG_BYTES = "unit_too_long_bytes"
PROBLEM_NEED_NUMBER = "unit_need_number"


@dataclass(frozen=True)
class UnitCheck:
    """Итог проверки написанного: каноничное имя или причина отказа (`PROBLEM_*`)."""

    name: UnitName | None
    problem: str = ""


def check_unit_name(typed: str) -> UnitCheck:
    """Пределы и каноничность названия — те же, что у мастера бота и у мини-аппа.

    Отказ здесь, а не отказом сборки отчёта в конце проверки: там аудитор уже
    уехал с точки, и переименовать пиццерию ему нечем. Пределы проверяются
    дважды — по написанному и по сведённому имени: латиница бывает длиннее
    («Щ» → «shch»), а 60 эмодзи проходят предел в знаках, но не в байтах (T128).
    """
    unit = typed.strip()
    if not unit:
        return UnitCheck(None, PROBLEM_EMPTY)
    if len(unit) > UNIT_NAME_LIMIT:
        return UnitCheck(None, PROBLEM_TOO_LONG)
    if len(unit.encode("utf-8")) > UNIT_NAME_BYTE_LIMIT:
        return UnitCheck(None, PROBLEM_TOO_LONG_BYTES)
    # Имя точки — город по-английски и номер, как бы его ни написали (D233).
    имя = canonical_unit(unit)
    if имя is None:
        return UnitCheck(None, PROBLEM_NEED_NUMBER)
    if len(имя.name) > UNIT_NAME_LIMIT:
        return UnitCheck(None, PROBLEM_TOO_LONG)
    if len(имя.name.encode("utf-8")) > UNIT_NAME_BYTE_LIMIT:
        return UnitCheck(None, PROBLEM_TOO_LONG_BYTES)
    return UnitCheck(имя)
