"""Когда пара «страна × источник» данных рейтингов считается дырой (D704, D706, #1444).

Чистые правила, без базы и сети: факты собирает `src/health/coverage_check.py`, оповещает он же.

**Источники:** рейтинг стандартов (РС), рейтинг контроля (РКО), клиентские оценки (КР), карты
Google и Яндекс, агрегаторы доставки (по одному на площадку).

**Цвет пары.** Красный — данных нет совсем (ни у одной пиццерии страны) или у страны не
подключён вход Dodo IS, из которого берутся клиентские оценки. Жёлтый — данные есть, но
старше порога свежести, или нет одного из двух месяцев клиентских оценок, или покрыто меньше
`MIN_SHARE` пиццерий. Если причин несколько — называется самая тяжёлая:
пусто → устарело → нет месяца → мало.

**Чего не ждём.** Агрегатор, не заведённый для страны, — не дыра (`enrolled=False`).
Пиццерии, которых человек отметил «нет на площадке», в базу страны для агрегатора не входят.
Страна без пиццерий в базе (`base == 0`) ничего не ждёт.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

RED = "red"
YELLOW = "yellow"

#: Покрытие ниже этой доли пиццерий страны — жёлтое.
MIN_SHARE = 0.8
#: Карты и агрегаторы: данные старше стольких суток — устарели.
FRESH_DAYS = 7

SRC_RS = "rs"
SRC_RKO = "rko"
SRC_KR = "kr"
SRC_GOOGLE = "maps_google"
SRC_YANDEX = "maps_yandex"
AGG_PREFIX = "agg_"

EMPTY = "empty"
NOT_CONNECTED = "not_connected"
STALE = "stale"
MISSING_CURRENT = "missing_current"
MISSING_PREVIOUS = "missing_previous"
LOW = "low"

#: Какого месяца клиентских оценок нет (`Fact.missing`).
CURRENT = "current"
PREVIOUS = "previous"

#: Префикс кода состояния в `health.alerts`: отделяет проверку покрытия от входов и сборов.
STATE_PREFIX = "cov_"

_STATE_CODE = re.compile(r"^[a-z_]{1,40}(:[A-Z]{2})?$")  # health.alerts.code, миграция 0099


def agg_source(aggregator: str) -> str:
    return f"{AGG_PREFIX}{aggregator}"


def state_code(source: str, country: str) -> str:
    """Код пары в `health.alerts`: `cov_rs:SI`."""
    code = f"{STATE_PREFIX}{source}:{country}"
    if not _STATE_CODE.match(code):
        raise ValueError(f"Код состояния не подходит таблице оповещений: {code}")
    return code


@dataclass(frozen=True)
class Fact:
    """Что известно о паре «страна × источник».

    `base` — пиццерий страны, у которых источник ожидается; `covered` — у скольких из них
    данные годные (у карт и агрегаторов — свежие); `ever` — у скольких есть хоть какие-то.
    `age_days` — возраст самых новых данных, `max_age_days` — порог свежести источника
    (`None` — возраст не проверяется).
    """

    country: str
    source: str
    base: int
    covered: int
    ever: int
    age_days: int | None = None
    max_age_days: int | None = None
    enrolled: bool = True
    connected: bool = True
    missing: tuple[str, ...] = ()


@dataclass(frozen=True)
class Finding:
    country: str
    source: str
    level: str
    reason: str
    share: float
    age_days: int | None


def share_of(fact: Fact) -> float:
    return fact.covered / fact.base if fact.base else 0.0


def _reason(fact: Fact) -> str | None:
    if not fact.connected:
        return NOT_CONNECTED
    if fact.ever == 0:
        return EMPTY
    if (
        fact.age_days is not None
        and fact.max_age_days is not None
        and fact.age_days > fact.max_age_days
    ):
        return STALE
    if CURRENT in fact.missing:
        return MISSING_CURRENT
    if PREVIOUS in fact.missing:
        return MISSING_PREVIOUS
    if share_of(fact) < MIN_SHARE:
        return LOW
    return None


def judge(fact: Fact) -> Finding | None:
    """Дыра в паре или `None`, если всё в порядке (или от пары ничего не ждём)."""
    if not fact.enrolled or fact.base <= 0:
        return None
    reason = _reason(fact)
    if reason is None:
        return None
    level = RED if reason in (NOT_CONNECTED, EMPTY) else YELLOW
    return Finding(fact.country, fact.source, level, reason, share_of(fact), fact.age_days)


def judge_all(facts: Iterable[Fact]) -> list[Finding]:
    """Все дыры, в порядке (источник, страна) — стабильном для текста и тестов."""
    found = [f for f in map(judge, facts) if f is not None]
    return sorted(found, key=lambda f: (f.source, f.country))
