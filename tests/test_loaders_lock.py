"""F-125: плановые загрузчики не работают, когда замок занят другим процессом.

Базы не нужно: замок подменён. Что сам замок исключает второго держателя —
`tests/test_db_busy_lock.py` на настоящей базе.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest

from src.bot import maps_loader, sheet_loader


def _замок(взят: bool, взятия: list[int]) -> object:
    @contextmanager
    def замок(key: int, *, what: str) -> Iterator[bool]:
        взятия.append(key)
        yield взят

    return замок


def test_карты_замок_занят_ничего_не_грузим(monkeypatch: pytest.MonkeyPatch) -> None:
    взятия: list[int] = []
    звали: list[str] = []
    monkeypatch.setattr(maps_loader, "job_lock", _замок(False, взятия))
    monkeypatch.setattr(maps_loader, "_due", lambda: звали.append("due") or True)
    monkeypatch.setattr(maps_loader.maps, "load_once", lambda: звали.append("load"))
    monkeypatch.setattr(maps_loader, "history_cycle", lambda state: звали.append("history") or True)
    history = maps_loader.HistoryState()

    maps_loader._load_if_due(history)
    maps_loader._history_step(history)

    assert звали == [], f"другой процесс держит замок, а этот полез в источник: {звали}"
    assert взятия == [maps_loader.MAPS_LOADER_LOCK_KEY] * 2


def test_карты_замок_взят_пора_значит_грузим_и_открываем_историю(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    звали: list[str] = []
    monkeypatch.setattr(maps_loader, "job_lock", _замок(True, []))
    monkeypatch.setattr(maps_loader, "_due", lambda: True)
    monkeypatch.setattr(maps_loader.maps, "load_once", lambda: звали.append("load"))
    monkeypatch.setattr(maps_loader, "history_cycle", lambda state: звали.append("history") or True)
    history = maps_loader.HistoryState(done=True)

    maps_loader._load_if_due(history)
    maps_loader._history_step(history)

    assert звали == ["load", "history"]
    assert history.done is False, (
        "в загрузке могли прийти новые филиалы — история открывается заново"
    )


def test_карты_замок_взят_не_пора_не_грузим(monkeypatch: pytest.MonkeyPatch) -> None:
    звали: list[str] = []
    monkeypatch.setattr(maps_loader, "job_lock", _замок(True, []))
    monkeypatch.setattr(maps_loader, "_due", lambda: False)
    monkeypatch.setattr(maps_loader.maps, "load_once", lambda: звали.append("load"))

    maps_loader._load_if_due(maps_loader.HistoryState())

    assert звали == []


def test_таблица_замок_занят_заявку_и_забор_не_трогаем(monkeypatch: pytest.MonkeyPatch) -> None:
    взятия: list[int] = []
    звали: list[str] = []
    monkeypatch.setattr(sheet_loader, "job_lock", _замок(False, взятия))
    monkeypatch.setattr(sheet_loader.state, "open_request", lambda: звали.append("request"))
    monkeypatch.setattr(sheet_loader.sheet_sync, "run", lambda: звали.append("run") or ())

    sheet_loader._tick()

    assert звали == [], f"другой процесс держит замок, а этот полез в таблицу: {звали}"
    assert взятия == [sheet_loader.SHEET_LOADER_LOCK_KEY]


def test_номера_замков_загрузчиков_не_пересекаются() -> None:
    from src.db import agg_store, job_lock

    keys = [
        job_lock.MAPS_LOADER_LOCK_KEY,
        job_lock.SHEET_LOADER_LOCK_KEY,
        agg_store.COLLECTOR_LOCK_KEY,
    ]
    assert len(set(keys)) == len(keys)
