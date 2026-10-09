"""День публикации издания методики — для шапки проверки на приёмке.

Каталог издания ищется тем же `pinned`, которым собирается письмо: хранилище
версий, боевая методика или полка снимков бота.

Сравнимостью рядов модуль больше не занимается (D352): оценка каждой проверки
верна по своей методике, и смена издания средние и движение не гасит.
"""

from __future__ import annotations

from src.domain.errors import ConfigError
from src.domain.version import published
from src.report.letters import LetterError, pinned, sources


def edition_day(version: str) -> str | None:
    """День публикации изданной сборки (`ГГГГ-ММ-ДД`); у неизданной — `None`."""
    try:
        найдено = pinned(version, sources())
        издание = published(найдено[0]) if найдено else None
    except (LetterError, ConfigError):
        return None
    return издание[1] if издание else None
