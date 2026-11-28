"""Pointer key changes take effect in the running loader without a bot restart."""

import asyncio

import pytest

from src.bot import maps_loader
from src.db import service_keys


def test_database_key_is_used_after_empty_cycle(monkeypatch, caplog):
    monkeypatch.delenv("POINTER_API_KEY", raising=False)
    reads, steps, sleeps = [], [], []

    def stored(name):
        reads.append(name)
        return None if len(reads) == 1 else "private-pointer-key"

    async def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(service_keys, "stored", stored)
    monkeypatch.setattr(maps_loader.asyncio, "sleep", sleep)
    for name in ("_load_if_due", "_history_step", "_reviews_step"):
        monkeypatch.setattr(maps_loader, name, lambda state, name=name: steps.append(name))
    with caplog.at_level("INFO"), pytest.raises(asyncio.CancelledError):
        asyncio.run(maps_loader._load_forever())
    assert reads == ["pointer.api_key", "pointer.api_key"]
    assert steps == ["_load_if_due", "_history_step", "_reviews_step"]
    assert sleeps == [maps_loader.CHECK_EVERY_SEC] * 2
    assert "не настроен" in caplog.text and "private-pointer-key" not in caplog.text
