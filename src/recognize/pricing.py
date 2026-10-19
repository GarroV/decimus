"""Оценка стоимости вызовов модели в долларах (D537).

Цены лежат в `model_prices.json` (цена за миллион токенов на входе и выходе, для
расшифровки — ещё и за минуту звука). Это ОЦЕНКА по публичному прейскуранту на день
сверки: счёт провайдера может разойтись (скидки, кэш, уровни). Модели без цены
стоимость не считается вовсе — `None`, а не ноль: «неизвестно» и «бесплатно» разные
ответы, и экран обязан их различать.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PRICES_FILE = Path(__file__).with_name("model_prices.json")

_PER_MILLION = 1_000_000
_SECONDS_PER_MINUTE = 60


@dataclass(frozen=True)
class Price:
    """Цена одной модели. Пустое поле — не задано."""

    input_per_1m: float | None = None
    output_per_1m: float | None = None
    audio_per_minute: float | None = None


@lru_cache(maxsize=1)
def load_prices() -> dict[str, Price]:
    """Цены по именам моделей. Нечитаемый файл — отказ: молча «без цен» скрыло бы поломку."""
    raw = json.loads(PRICES_FILE.read_text(encoding="utf-8"))
    return {
        name: Price(
            input_per_1m=entry.get("input_per_1m"),
            output_per_1m=entry.get("output_per_1m"),
            audio_per_minute=entry.get("audio_per_minute"),
        )
        for name, entry in raw["models"].items()
    }


def estimate_cost(
    model: str,
    *,
    input_tokens: int,
    output_tokens: int,
    audio_seconds: float = 0.0,
    prices: dict[str, Price] | None = None,
) -> float | None:
    """Оценка стоимости, USD; `None` — цены модели нет (или её не хватает на расход).

    Звук с длительностью считается по минутам; токены — по ценам входа и выхода. Если
    расход есть, а нужной цены нет, итог неизвестен целиком: частичная сумма выдала бы
    себя за полную.
    """
    price = (prices if prices is not None else load_prices()).get(model)
    if price is None:
        return None
    total = 0.0
    if audio_seconds:
        if price.audio_per_minute is None:
            return None
        total += audio_seconds / _SECONDS_PER_MINUTE * price.audio_per_minute
    for tokens, per_million in (
        (input_tokens, price.input_per_1m),
        (output_tokens, price.output_per_1m),
    ):
        if not tokens:
            continue
        if per_million is None:
            return None
        total += tokens / _PER_MILLION * per_million
    return total
