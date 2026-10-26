"""Оповещённые состояния подключений в настоящей базе и заход оповещений целиком (D641).

Состояние переживает «перезапуск бота» (новый заход читает его из базы), канал не задан — ничего
не пишется, строка состояния канала ложится для вкладки «Подключения».
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from conftest import requires_db

psycopg = pytest.importorskip("psycopg")

from src.db import health_store  # noqa: E402
from src.db.errors import DbError  # noqa: E402
from src.domain.health import RED, Status  # noqa: E402
from src.health import alerts, checks  # noqa: E402
from src.health.rows import Row  # noqa: E402

pytestmark = requires_db

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)
ENV = {"FURCA_NOTIFY_URL": "http://ch:8090", "FURCA_SECRET": "s"}


def _строки(light: str) -> tuple[Row, ...]:
    reason = "health.reason.dodois_failed" if light == RED else "health.reason.dodois_ok"
    return (
        Row(
            "dodo_is",
            checks.DODOIS,
            Status(light, reason, NOW, {"open": 1, "total": 1}),
            "dodo_is",
            "SI",
        ),
    )


def test_состояния_пишутся_и_заменяются(db_env: str) -> None:
    assert health_store.alert_levels() == {}
    health_store.save_alert_levels({"dodo_is:SI": "ok", "aggregators": "red"}, NOW)
    health_store.save_alert_levels({"dodo_is:SI": "red"}, NOW)
    assert health_store.alert_levels() == {"dodo_is:SI": "red", "aggregators": "red"}


@pytest.mark.parametrize("code", ["dodo_is:si", "Dodo IS", "x" * 41])
def test_база_не_принимает_чужой_код_и_уровень(db_env: str, code: str) -> None:
    with pytest.raises(DbError):
        health_store.save_alert_levels({code: "ok"}, NOW)
    with pytest.raises(DbError):
        health_store.save_alert_levels({"dodo_is:SI": "purple"}, NOW)


def test_заход_с_базой_первый_молчит_поломка_одно_сообщение_перезапуск_не_повторяет(
    db_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[tuple[str, str]] = []
    send = lambda _t, text, kind: sent.append((kind, text))  # noqa: E731
    состояние = {"rows": _строки("green")}
    monkeypatch.setattr(alerts, "build_rows", lambda *_a, **_k: состояние["rows"])

    assert alerts.run_pass(NOW, env=ENV, send=send) == 0  # первый заход: фиксирует
    состояние["rows"] = _строки(RED)
    assert alerts.run_pass(NOW, env=ENV, send=send) == 1  # сломалось
    assert alerts.run_pass(NOW, env=ENV, send=send) == 0  # «перезапуск»: состояние из базы
    состояние["rows"] = _строки("green")
    assert alerts.run_pass(NOW, env=ENV, send=send) == 1  # починилось
    assert [kind for kind, _ in sent] == ["alert", "done"]


def test_канал_не_задан_ничего_не_пишется_а_строка_канала_ложится(
    db_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(alerts, "build_rows", lambda *_a, **_k: _строки(RED))
    assert alerts.run_pass(NOW, env={}) == 0
    assert health_store.alert_levels() == {}
    row = health_store.probes()[alerts.CHANNEL_CODE]
    assert row.reason == "health.reason.alerts_off"
    # Демо при заданном канале: то же самое.
    assert alerts.run_pass(NOW, env={**ENV, "WEB_DEMO": "1"}) == 0
    assert health_store.probes()[alerts.CHANNEL_CODE].reason == "health.reason.alerts_demo"
    assert health_store.alert_levels() == {}
