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
from src.health import checks
from src.health.checks import CONFIG, LOAD, PENDING, PROBE, PROBE_EVERY

from . import auth

_log = logging.getLogger(__name__)

_PENDING_REASON = {
    "backup": "health.reason.backup_host",
    "dodo_is": "health.reason.dodo_is_pending",
}


@dataclass(frozen=True)
class Row:
    """Строка подключения на экране."""

    code: str
    kind: str
    status: Status

    @property
    def checkable(self) -> bool:
        return self.kind == PROBE


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
    moment = now or datetime.now(UTC)
    try:
        probes = health_store.probes()
        loads = health_store.loads()
    except DbError:
        _log.warning("Подключения: состояние не прочиталось", exc_info=True)
        return None
    found: list[Row] = []
    for conn in checks.CONNECTIONS:
        if conn.kind == PROBE:
            status = health.of_probe(probes.get(conn.code), moment, every=PROBE_EVERY)
        elif conn.kind == LOAD and conn.fresh_for is not None:
            status = health.of_loads(loads.get(conn.code), moment, fresh_for=conn.fresh_for)
        elif conn.kind == CONFIG:
            status = _google()
        else:
            status = Status(GREY, _PENDING_REASON.get(conn.code, "health.reason.not_configured"))
        found.append(Row(conn.code, conn.kind, status))
    return tuple(found)


def context(flash: Flash | None = None) -> dict[str, Any]:
    """Что нужно шаблону блока."""
    found = rows()
    lights = [r.status.light for r in found or ()]
    return {
        "health_rows": found,
        "health_summary": health.summary(lights),
        "health_count": {
            light: sum(1 for x in lights if x == light) for light in (GREEN, YELLOW, RED, GREY)
        },
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
