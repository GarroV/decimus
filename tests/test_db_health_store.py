"""Схема `health` и двери вкладки «Подключения» в настоящей базе (D638, #1251).

Пишет и читает роль приложения: исход пробы заменяет прежний, а не копится; чужой цвет и
причина вне `health.reason.*` база не принимает; журналы сборов читаются последним заходом,
упавший агрегатор — поимённо.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from conftest import requires_db

psycopg = pytest.importorskip("psycopg")

from src.db import health_store  # noqa: E402
from src.db.errors import DbError  # noqa: E402

pytestmark = requires_db

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)


def test_исход_пробы_заменяет_прежний(db_env: str) -> None:
    health_store.record("openai", "red", "health.reason.rejected", NOW - timedelta(minutes=15))
    health_store.record("openai", "green", "health.reason.ok", NOW)
    found = health_store.probes()
    assert list(found) == ["openai"]
    assert (found["openai"].light, found["openai"].reason, found["openai"].checked_at) == (
        "green",
        "health.reason.ok",
        NOW,
    )


@pytest.mark.parametrize(
    ("light", "reason"), [("purple", "health.reason.ok"), ("green", "сломалось всё")]
)
def test_база_не_принимает_чужой_цвет_и_причину(db_env: str, light: str, reason: str) -> None:
    with pytest.raises(DbError):
        health_store.record("openai", light, reason, NOW)


def test_сборы_без_журналов_не_ходили(db_env: str) -> None:
    assert health_store.loads() == {
        "maps": None,
        "learning": None,
        "aggregators": None,
        "sheet": None,
    }


def test_агрегаторы_последний_заход_и_упавшие_поимённо(db_env: str) -> None:
    with psycopg.connect(db_env) as conn:
        conn.execute(
            "insert into agg.loads (at, aggregator, outcome, error) values "
            "(%s, 'wolt', 'ok', null), (%s, 'glovo', 'failed', '503'), "
            "(%s, 'glovo', 'ok', null)",
            (NOW, NOW - timedelta(hours=1), NOW - timedelta(days=1)),
        )
        conn.execute(
            "insert into maps.loads (at, outcome, error) values (%s, 'ok', null)",
            (NOW - timedelta(hours=3),),
        )
    found = health_store.loads()
    agg = found["aggregators"]
    assert agg is not None
    assert (agg.at, agg.ok, agg.error) == (NOW, False, "glovo: 503")
    maps = found["maps"]
    assert maps is not None
    assert (maps.at, maps.ok) == (NOW - timedelta(hours=3), True)
