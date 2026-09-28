"""Иконки админки — набор линейки из дизайн-системы (`static/icons.json`).

Набор один на все продукты: эталон — Swarm Brain (решение владельца
28.09.2026, в MERIDIUS записано как D164). Файл кладёт раскатка forma рядом с
ядром, руками он не правится.

Неизвестное имя — отказ, а не пустое место: иконка, которая молча не
нарисовалась, выглядит как сдвинутая вёрстка, и её замечают глазами через
неделю. Отказ же виден на первом открытии страницы и в тестах.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from markupsafe import Markup

ICONS_PATH = Path(__file__).resolve().parent / "static" / "icons.json"

#: Как рисует набор Swarm (RoyIcon): поле 20×20, контур цветом текста.
SVG = (
    '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="{width}" '
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">'
    '<path d="{d}"/></svg>'
)


#: Путь SVG — только команды и числа. Проверяется при загрузке: в разметку
#: значение идёт без экранирования, и всё прочее в нём — отказ.
PATH_DATA = re.compile(r"[MmLlHhVvCcSsQqTtAaZz0-9 .,\-]+")


@lru_cache(maxsize=1)
def _paths() -> dict[str, str]:
    raw = json.loads(ICONS_PATH.read_text(encoding="utf-8"))
    paths = {name: d for name, d in raw.items() if not name.startswith("_")}
    чужие = sorted(name for name, d in paths.items() if not PATH_DATA.fullmatch(d))
    if чужие:
        raise ValueError(f"В {ICONS_PATH.name} не пути SVG: {', '.join(чужие)}")
    return paths


def icon(name: str, width: float = 1.7) -> Markup:
    """SVG иконки по имени из набора линейки."""
    paths = _paths()
    if name not in paths:
        raise KeyError(f"Иконки «{name}» нет в {ICONS_PATH.name}; есть: {', '.join(sorted(paths))}")
    # Безопасно: путь проверен PATH_DATA, ширина — число.
    return Markup(SVG.format(d=paths[name], width=float(width)))  # noqa: S704
