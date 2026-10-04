"""Связки, собранные по приглашениям до D286: только чтение, совместимость (#340)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.bot.errors import BotConfigError
from src.bot.roster import Roster


def _записать(tmp_path: Path, entries: list[dict[str, object]]) -> None:
    path = tmp_path / "access" / "roster.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"version": 1, "entries": entries}), encoding="utf-8")


def test_missing_file_is_empty_roster(tmp_path: Path) -> None:
    """Стенд, где никого не приглашали, поднимается без файла."""
    assert Roster.load(tmp_path).knows(555000111) is False


def test_stored_people_are_known_with_their_names(tmp_path: Path) -> None:
    _записать(
        tmp_path,
        [
            {"telegram_id": 555000111, "name": "Anna Petrova"},
            {"telegram_id": 111, "name": None},
        ],
    )
    roster = Roster.load(tmp_path)
    assert roster.knows(555000111) and roster.knows(111)
    assert roster.names() == {555000111: "Anna Petrova"}


def test_reading_does_not_touch_the_file(tmp_path: Path) -> None:
    """Связки больше не дописываются: файл после подъёма тот же байт в байт."""
    _записать(tmp_path, [{"telegram_id": 111, "name": None}])
    path = tmp_path / "access" / "roster.json"
    было = path.read_bytes()
    Roster.load(tmp_path)
    assert path.read_bytes() == было


def test_broken_file_refuses_to_start(tmp_path: Path) -> None:
    """Битый файл — отказ, а не молчаливый сброс: иначе узнанные молча теряют бота."""
    path = tmp_path / "access" / "roster.json"
    path.parent.mkdir(parents=True)
    path.write_text("{это не json", encoding="utf-8")

    with pytest.raises(BotConfigError, match="не разобрался"):
        Roster.load(tmp_path)
