"""Компоновка страницы «Рейтинги» (D368, D370): порядок и видимость блоков.

Блоки — готовые куски страницы; их набор задаёт код, а контролинг только
расставляет и прячет. Хранится в `ratings.layout`; здесь — чистые правила,
без базы: что считать порядком, если строк не хватает или пришло лишнее.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

#: Блоки страницы в порядке по умолчанию. Код блока — ключ текста
#: `ratings.layout.<код>` и ветка шаблона `ratings/index.html`.
BLOCKS: tuple[str, ...] = ("scores", "violations", "top", "hard", "risk")


@dataclass(frozen=True)
class Block:
    key: str
    visible: bool


def arrange(rows: Iterable[tuple[str, int, bool]]) -> tuple[Block, ...]:
    """Блоки по сохранённому порядку. Незнакомые коды выпадают, не сохранённые
    встают в конец видимыми: новый блок из кода не должен пропасть молча."""
    known = sorted((pos, key, visible) for key, pos, visible in rows if key in BLOCKS)
    seen = {key for _, key, _ in known}
    return tuple(Block(key, visible) for _, key, visible in known) + tuple(
        Block(key, True) for key in BLOCKS if key not in seen
    )


def moved(blocks: tuple[Block, ...], key: str, step: int) -> tuple[Block, ...]:
    """Тот же порядок, где `key` сдвинут на `step` (−1 — выше, +1 — ниже)."""
    keys = [b.key for b in blocks]
    if key not in keys:
        return blocks
    at = keys.index(key)
    to = min(max(at + step, 0), len(blocks) - 1)
    order = list(blocks)
    order.insert(to, order.pop(at))
    return tuple(order)
