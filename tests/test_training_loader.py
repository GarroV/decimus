"""Суточный загрузчик обучения в боте (#906): когда пора, нет ключей, тревога один раз."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from src.bot import learning_loader as ll
from src.learning.ispring import IspringError
from src.learning.sync import Summary


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    w: dict[str, Any] = {"last": None, "got": True, "client": object(), "logged": [], "ran": 0}

    @contextmanager
    def lock(_key: int, *, what: str):
        yield w["got"]

    monkeypatch.setattr(ll, "job_lock", lock)
    monkeypatch.setattr(ll.learning_store, "last_ok_load", lambda: w["last"])
    monkeypatch.setattr(ll.learning_store, "log_load", lambda **kw: w["logged"].append(kw))
    monkeypatch.setattr(ll.keys, "client", lambda: w["client"])

    def run(_client: object) -> Summary:
        w["ran"] += 1
        if w.get("error"):
            raise w["error"]
        return Summary(10, 8, 7, 100, 0, 0)

    monkeypatch.setattr(ll, "run", run)
    return w


def test_пора_когда_загрузок_не_было(world: dict[str, Any]) -> None:
    assert ll.load_if_due(ll.State()) is None
    assert world["ran"] == 1
    assert world["logged"][0]["ok"] is True


def test_свежая_загрузка_не_повторяется(world: dict[str, Any]) -> None:
    world["last"] = datetime.now(UTC) - timedelta(hours=ll.FRESH_FOR_SEC / 3600 - 1)
    ll.load_if_due(ll.State())
    assert world["ran"] == 0


def test_старая_загрузка_повторяется(world: dict[str, Any]) -> None:
    world["last"] = datetime.now(UTC) - timedelta(hours=ll.FRESH_FOR_SEC / 3600 + 1)
    ll.load_if_due(ll.State())
    assert world["ran"] == 1


def test_замок_занят_заход_пропускается(world: dict[str, Any]) -> None:
    world["got"] = False
    ll.load_if_due(ll.State())
    assert world["ran"] == 0


def test_нет_ключей_молча_пропуск_и_одна_строка_в_лог(
    world: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    world["client"] = None
    state = ll.State()
    with caplog.at_level(logging.INFO):
        for _ in range(3):
            assert ll.load_if_due(state) is None
    assert world["ran"] == 0
    assert sum("ключи iSpring не заданы" in r.getMessage() for r in caplog.records) == 1


def test_сбой_пишется_в_журнал_и_возвращается_текстом(world: dict[str, Any]) -> None:
    world["error"] = IspringError("iSpring ответил 500 на /learners/results")
    failure = ll.load_if_due(ll.State())
    assert failure is not None and "500" in failure
    assert world["logged"][0]["ok"] is False
