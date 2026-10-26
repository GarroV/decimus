"""Строки состояния подключений: реестр + факты из базы → цвет каждой (D638, D641).

Одно место, где цвет подключения выводится из фактов: им красится плитка во вкладке
«Подключения» (`src/web/admin_health.py`) и им же бот решает, оповещать ли владельца
(`src/health/alerts.py`) — чтобы экран и сообщение никогда не расходились.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from src.db import dodois_logins, health_store
from src.db.errors import DbError
from src.domain import dodois as dodois_rules
from src.domain import health
from src.domain.dodois import Login
from src.domain.health import GREY, Status

from . import checks
from .checks import CONFIG, DODOIS, LOAD, PROBE, PROBE_EVERY

_log = logging.getLogger(__name__)

_PENDING_REASON = {"backup": "health.reason.backup_host"}


@dataclass(frozen=True)
class Row:
    """Строка подключения на экране."""

    code: str
    kind: str
    status: Status
    #: Группа плиток (`checks.GROUPS`).
    group: str = ""
    #: Код страны у строки входа Dodo IS (D640); у остальных пусто.
    country: str = ""

    @property
    def checkable(self) -> bool:
        return self.kind == PROBE


def _dodois_rows(conn: checks.Connection, logins: tuple[Login, ...], moment: datetime) -> list[Row]:
    """Строка на каждый вход Dodo IS; входов нет — одна серая строка «подключений нет»."""
    if not logins:
        return [Row(conn.code, DODOIS, Status(GREY, "health.reason.dodois_none"), conn.group)]
    return [
        Row(
            conn.code,
            DODOIS,
            dodois_rules.status_of(login, moment),
            conn.group,
            country=login.country,
        )
        for login in logins
    ]


def build(now: datetime | None = None, *, google: Status | None = None) -> tuple[Row, ...] | None:
    """Строки по реестру; `None` — база не ответила.

    `google` — состояние входа через Google, его знает только веб (клиент OAuth задаётся при
    сборке приложения); бот не знает и строку входа через Google не получает.
    """
    moment = now or datetime.now(UTC)
    try:
        probes = health_store.probes()
        loads = health_store.loads()
        logins = dodois_logins.list_logins()
    except DbError:
        _log.warning("Подключения: состояние не прочиталось", exc_info=True)
        return None
    found: list[Row] = []
    for conn in checks.CONNECTIONS:
        if conn.kind == PROBE:
            every = PROBE_EVERY if conn.scheduled else None
            status = health.of_probe(probes.get(conn.code), moment, every=every)
        elif conn.kind == LOAD and conn.fresh_for is not None:
            status = health.of_loads(loads.get(conn.code), moment, fresh_for=conn.fresh_for)
        elif conn.kind == DODOIS:
            found.extend(_dodois_rows(conn, logins, moment))
            continue
        elif conn.kind == CONFIG:
            if google is None:
                continue
            status = google
        else:
            status = Status(GREY, _PENDING_REASON.get(conn.code, "health.reason.not_configured"))
        found.append(Row(conn.code, conn.kind, status, conn.group))
    return tuple(found)
