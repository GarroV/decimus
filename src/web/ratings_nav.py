"""Разделы «Рейтингов» и подменю в общей навигации (D660).

Состав и порядок разделов задаёт код: контролинг их не двигает (редактор
компоновки снят). Здесь — что за разделы, кому виден какой и как собирается
подменю: подпись, адрес, текущий пункт и точка свежести источника.

Адрес раздела — `/ratings/<раздел>`; голый `/ratings` — первый раздел. Срез и
период едут в адресе каждого пункта: переход между разделами их не сбрасывает.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode

from src.ratings import freshness as fresh
from src.ratings import report

from . import ratings_freshness
from .texts import t

RS = "rs"
RKO = "rko"
CLIENTS = "clients"
MAPS = "maps"
AGG = "agg"
RISK = "risk"
COMPARE = "compare"
INSPECTIONS = "inspections"

#: Разделы в порядке подменю.
SECTIONS: tuple[str, ...] = (RS, RKO, CLIENTS, MAPS, AGG, RISK, COMPARE, INSPECTIONS)
DEFAULT = RS
#: Видны только УК (D551): партнёру чужие страны и девелоперов не показываем.
HQ_ONLY = frozenset({COMPARE})


@dataclass(frozen=True)
class Item:
    """Пункт подменю. `dot` — цвет точки свежести (`None` — точки нет)."""

    key: str
    title: str
    href: str
    current: bool
    dot: str | None
    dot_word: str


def visible(is_hq: bool, *, inspections: bool = False) -> tuple[str, ...]:
    """Разделы, доступные вошедшему."""
    keys = SECTIONS if inspections else tuple(k for k in SECTIONS if k != INSPECTIONS)
    return tuple(key for key in keys if is_hq or key not in HQ_ONLY)


def query(selection: report.Selection, lang: str, **extra: str) -> str:
    """Срез, период и язык — одной строкой адреса; `extra` — добавочные поля."""
    pairs = [("group", selection.group)]
    if selection.value:
        pairs.append(("value", selection.value))
    pairs += [("period", selection.period.key), ("lang", lang), *extra.items()]
    return urlencode(pairs)


def section_url(root: str, key: str, selection: report.Selection, lang: str, **extra: str) -> str:
    """Адрес раздела с тем же срезом и периодом."""
    return f"{root}/{key}?{query(selection, lang, **extra)}"


def items(
    root: str,
    *,
    is_hq: bool,
    current: str,
    selection: report.Selection,
    lang: str,
    rows: tuple[fresh.Row, ...],
    inspections: bool = False,
) -> tuple[Item, ...]:
    """Подменю для вошедшего: пункты, адреса с текущим отбором, точки свежести."""
    result = []
    for key in visible(is_hq, inspections=inspections):
        status = ratings_freshness.section_status(rows, key)
        result.append(
            Item(
                key=key,
                title=t(f"ratings.sec.{key}", lang),
                href=section_url(root, key, selection, lang),
                current=key == current,
                dot=status,
                dot_word=t(f"ratings.fresh.word.{status}", lang) if status else "",
            )
        )
    return tuple(result)
