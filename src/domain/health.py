"""Цвет подключения на вкладке «Подключения» (D638): правила, без базы и сети.

Подключения двух видов. **Проба** — ключ или служба, которую фоновая задача бота
дёргает раз в `every` и пишет исход (`src/bot/health_loader.py`): ключи OpenAI,
Pointer, iSpring, сам бот, хранилище кадров. **Сбор** — загрузчик, у которого
уже есть свой журнал загрузок (агрегаторы, карты, таблица контроля, iSpring):
его цвет выводится из последнего захода, отдельной проверки нет.

Цвет — факт, а не настроение: зелёный значит «последняя проверка прошла и она
свежая». Проверка, которая перестала идти, не может оставаться зелёной: она
желтеет, потому что встал тот, кто проверяет, а не обязательно проверяемое.
Серый — «нечего сказать»: не настроено или ещё ни разу не шло; в итог не входит.

Причина — ключ текста (`health.reason.*`), подстановки — в `params`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

GREEN = "green"
YELLOW = "yellow"
RED = "red"
GREY = "grey"

#: Сколько сроков проверки может пропасть, прежде чем исход считается несвежим.
STALE_AFTER_PERIODS = 3

_WORSE = {GREY: 0, GREEN: 1, YELLOW: 2, RED: 3}


@dataclass(frozen=True)
class Status:
    """Что показать в строке подключения."""

    light: str
    reason: str
    checked_at: datetime | None = None
    params: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProbeRow:
    """Исход последней пробы, как его записала фоновая задача."""

    light: str
    reason: str
    checked_at: datetime


@dataclass(frozen=True)
class LoadFacts:
    """Последний заход сбора по его журналу загрузок."""

    at: datetime
    ok: bool
    error: str | None


def of_probe(row: ProbeRow | None, now: datetime, *, every: timedelta | None) -> Status:
    """Цвет пробы: последний исход, если он свежий, иначе «проверка не идёт».

    `every=None` — подключение пробуется только по кнопке, а не по расписанию: исход не
    стареет, время проверки видно рядом с ним.
    """
    if row is None:
        return Status(GREY, "health.reason.never_checked")
    if every is not None and now - row.checked_at > STALE_AFTER_PERIODS * every:
        return Status(YELLOW, "health.reason.stale", row.checked_at)
    return Status(row.light, row.reason, row.checked_at)


def of_loads(facts: LoadFacts | None, now: datetime, *, fresh_for: timedelta) -> Status:
    """Цвет сбора: упал — красный; опаздывает — жёлтый; встал надолго — красный.

    `fresh_for` — сколько может пройти между удачными заходами у исправного
    загрузчика (его расписание плюс запас). Вдвое дольше — сбор встал.
    """
    if facts is None:
        return Status(GREY, "health.reason.never_ran")
    if not facts.ok:
        return Status(RED, "health.reason.failed", facts.at, {"error": facts.error or "—"})
    age = now - facts.at
    if age > 2 * fresh_for:
        return Status(RED, "health.reason.stopped", facts.at)
    if age > fresh_for:
        return Status(YELLOW, "health.reason.late", facts.at)
    return Status(GREEN, "health.reason.ran", facts.at)


def summary(lights: Iterable[str]) -> str:
    """Худший цвет из несерых; одни серые — серый."""
    return max(lights, key=lambda light: _WORSE[light], default=GREY)
