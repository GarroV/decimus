"""Блок «Состояние подключений» вкладки «Подключения» (D638, #1251): строки и итог.

Цвет каждой строки выводит `src/domain/health.py` из фактов: исходов проб (их пишет бот
раз в 15 минут, `src/bot/health_loader.py`), журналов загрузок сборов и настройки входа
через Google. Здесь только сборка строк и кнопка «Проверить сейчас»; сами пробы —
`src/health/checks.py`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from flask import current_app

from src.db import health_store
from src.db.errors import DbError
from src.domain import health
from src.domain.health import GREEN, GREY, RED, YELLOW, Status
from src.health import alerts, checks
from src.health import rows as health_rows
from src.health.checks import PENDING
from src.health.rows import Row

from . import auth

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Flash:
    """Исход «Проверить сейчас»."""

    key: str
    ok: bool
    params: dict[str, Any]


def _google() -> Status:
    # Вход через Google включается при сборке приложения, когда задан клиент OAuth.
    if current_app.extensions.get(auth.GOOGLE_ENABLED_KEY):
        return Status(GREEN, "health.reason.configured")
    return Status(GREY, "health.reason.not_configured")


def rows(now: datetime | None = None) -> tuple[Row, ...] | None:
    """Строки по реестру; `None` — база не ответила."""
    return health_rows.build(now, google=_google())


def grouped(found: tuple[Row, ...]) -> tuple[tuple[str, tuple[Row, ...]], ...]:
    """Строки по группам в порядке `checks.GROUPS`; пустые группы не показываются."""
    by_group = ((g, tuple(r for r in found if r.group == g)) for g in checks.GROUPS)
    return tuple((g, members) for g, members in by_group if members)


def alerts_status() -> Status | None:
    """Включены ли оповещения владельцу (D641): исход пишет бот под кодом канала."""
    try:
        row = health_store.probes().get(alerts.CHANNEL_CODE)
    except DbError:
        return None
    if row is None:
        return Status(GREY, "health.reason.never_checked")
    return Status(row.light, row.reason, row.checked_at)


def context(flash: Flash | None = None) -> dict[str, Any]:
    """Что нужно шаблону блока."""
    found = rows()
    lights = [r.status.light for r in found or ()]
    return {
        "health_rows": found,
        "health_groups": grouped(found) if found is not None else (),
        "health_summary": health.summary(lights),
        "health_count": {
            light: sum(1 for x in lights if x == light) for light in (GREEN, YELLOW, RED, GREY)
        },
        "health_alerts": alerts_status(),
        "health_flash": flash,
        "health_stamp": _stamp,
        "health_pending": PENDING,
    }


def _stamp(moment: datetime | None) -> str:
    return "" if moment is None else moment.astimezone(UTC).strftime("%d.%m %H:%M UTC")


def check_now(code: str) -> Flash:
    """Пробовать подключение сейчас и записать исход."""
    outcome = checks.run_probe(code)
    if outcome is None:
        return Flash("health.err.unavailable", False, {})
    light, reason = outcome
    try:
        health_store.record(code, light, reason, datetime.now(UTC))
    except DbError:
        _log.warning("Подключения: исход проверки %s не записался", code, exc_info=True)
        return Flash("health.err.db", False, {})
    return Flash("health.ok.checked", light == GREEN, {"code": code})
