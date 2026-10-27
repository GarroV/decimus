"""Компоновка страницы «Рейтинги» (D368, D370): порядок и видимость блоков.

Блоки — готовые куски страницы; их набор задаёт код, а контролинг только
расставляет и прячет. Хранится в `ratings.layout`; здесь — чистые правила,
без базы: что считать порядком, если строк не хватает или пришло лишнее.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

#: Ярусы страницы (D658): состав яруса задан кодом, контролинг двигает блоки только
#: внутри яруса. Код блока — ключ текста `ratings.layout.<код>` и ветка шаблона
#: `ratings/index.html`. «Сравнение» (D551) видит только УК: у остальных блок пропускается
#: шаблоном. «Оценки клиентов» (`clients`) — из Dodo IS, пока без данных (#1303).
TIERS: tuple[tuple[str, ...], ...] = (
    ("scores", "violations", "top"),
    ("clients", "maps", "aggregators", "risk"),
    ("hard", "compare"),
)

#: Блоки страницы в порядке по умолчанию: ярус за ярусом.
BLOCKS: tuple[str, ...] = tuple(key for tier in TIERS for key in tier)

_TIER_OF = {key: i for i, tier in enumerate(TIERS) for key in tier}


def tier_of(key: str) -> int:
    """Номер яруса блока; код, которого нет в `BLOCKS`, — `KeyError`."""
    return _TIER_OF[key]


@dataclass(frozen=True)
class Block:
    key: str
    visible: bool


def arrange(rows: Iterable[tuple[str, int, bool]]) -> tuple[Block, ...]:
    """Блоки по ярусам, внутри яруса — по сохранённому порядку. Незнакомые коды выпадают,
    не сохранённые встают в конец своего яруса видимыми: новый блок из кода не должен
    пропасть молча, а старая раскладка из базы — разъехаться по ярусам."""
    known = sorted(
        (_TIER_OF[key], pos, key, visible) for key, pos, visible in rows if key in BLOCKS
    )
    seen = {key for _, _, key, _ in known}
    placed = [(tier, pos, key, visible) for tier, pos, key, visible in known]
    placed += [
        (_TIER_OF[key], len(BLOCKS) + i, key, True)
        for i, key in enumerate(BLOCKS)
        if key not in seen
    ]
    return tuple(Block(key, visible) for _, _, key, visible in sorted(placed))


def moved(blocks: tuple[Block, ...], key: str, step: int) -> tuple[Block, ...]:
    """Тот же порядок, где `key` сдвинут на `step` (−1 — выше, +1 — ниже); из своего яруса
    блок не выходит — крайний остаётся на месте."""
    keys = [b.key for b in blocks]
    if key not in keys:
        return blocks
    at = keys.index(key)
    to = min(max(at + step, 0), len(blocks) - 1)
    if _TIER_OF[blocks[to].key] != _TIER_OF[key]:
        return blocks
    order = list(blocks)
    order.insert(to, order.pop(at))
    return tuple(order)
