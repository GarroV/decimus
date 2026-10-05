"""Одной ли ценой посчитаны проверки — признак рядов админки (#405, D187).

Обзор сети и карточка точки усредняют и сравнивают оценки только внутри
одного ряда. До #405 ряд рвался на любой смене издания методики, а имя
издания выводится из ВСЕГО содержимого методики (D050): правка формулировки
давала новое издание той же цены, и обзор отказывался считать среднюю по
проверкам, посчитанным одинаково (прод, 28.09: семь проверок на трёх изданиях
с одними ставками).

Ключ ряда — «код чек-листа + пункты и веса издания» (`domain.shape`, D218), то же
правило, что у агента (`src/mcp/comparability.py`). Каталог издания ищется тем
же `pinned`, которым собирается письмо: хранилище версий, боевая методика или
полка снимков бота.

**Незнание за совпадение не выдаётся.** Издания нет на машине — ключом
становится само имя издания, то есть прежнее строгое правило: такая проверка
складывается в ряд только с проверками ровно того же издания.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache

from src.db.models import InspectionRow
from src.domain.errors import ConfigError
from src.domain.shape import scoring_shape
from src.domain.version import published
from src.report.letters import LetterError, pinned, sources

#: Читатель цены издания: имя издания → отпечаток или `None`. Подменяется в
#: проверках экрана, которым незачем класть на диск методику.
ShapeReader = Callable[[str], "str | None"]


@lru_cache(maxsize=256)
def _shape(version: str) -> str | None:
    """Отпечаток цены издания. Кэш безопасен: имя издания — отпечаток его
    содержимого (D050), и одно имя не может сменить цену."""
    try:
        найдено = pinned(version, sources())
    except LetterError:
        return None
    if найдено is None:
        return None
    return scoring_shape(найдено[0])


_reader: ShapeReader = _shape


def use_reader(reader: ShapeReader | None) -> None:
    """Подменить читателя цены (`None` — вернуть настоящего)."""
    global _reader
    _reader = _shape if reader is None else reader


def edition_day(version: str) -> str | None:
    """День публикации изданной сборки (`ГГГГ-ММ-ДД`); у неизданной — `None`."""
    try:
        найдено = pinned(version, sources())
        издание = published(найдено[0]) if найдено else None
    except (LetterError, ConfigError):
        return None
    return издание[1] if издание else None


def price_key(row: InspectionRow) -> tuple[str, str]:
    """Ключ ряда проверки: код чек-листа и цена его издания."""
    return price_key_of(row.checklist_code, row.checklist_version)


def price_key_of(checklist_code: str, checklist_version: str) -> tuple[str, str]:
    """Тот же ключ по коду чек-листа и изданию — для агрегата среза из базы (#503)."""
    форма = _reader(checklist_version)
    return (
        checklist_code,
        f"shape:{форма}" if форма else f"edition:{checklist_version}",
    )
