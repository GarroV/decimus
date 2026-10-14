"""#787: уборка копий кадров переживает любой отказ прохода, а не только OSError."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from src.bot import frame_copies


@pytest.mark.asyncio
async def test_отказ_прохода_не_останавливает_уборку(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    проходы: list[int] = []

    def sweep(_root: Path) -> int:
        проходы.append(1)
        if len(проходы) == 1:
            raise ValueError("сломанный проход")
        return 0

    monkeypatch.setattr(frame_copies, "frames_dir", lambda: tmp_path)
    monkeypatch.setattr(frame_copies, "sweep", sweep)
    monkeypatch.setattr(frame_copies, "SWEEP_EVERY_SEC", 0)

    задача = asyncio.create_task(frame_copies.sweep_forever())
    for _ in range(50):
        await asyncio.sleep(0.01)
        if len(проходы) >= 2:
            break
    задача.cancel()

    assert len(проходы) >= 2, "после первого отказа уборка встала"
