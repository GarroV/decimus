"""Связки «юзернейм → числовой ID», узнанные при первом контакте (#230)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.bot.errors import BotConfigError
from src.bot.invites import Invite
from src.bot.roster import Roster


def test_missing_file_is_empty_roster(tmp_path: Path) -> None:
    """Стенд, где ещё никто не приглашён, поднимается без файла."""
    roster = Roster.load(tmp_path)
    assert roster.knows(555000111) is False
    assert roster.username_used("apetrov") is False


def test_activation_is_remembered_across_restart(tmp_path: Path) -> None:
    roster = Roster.load(tmp_path)
    roster.activate(555000111, Invite(username="apetrov", name="Anna Petrova"))

    restarted = Roster.load(tmp_path)
    assert restarted.knows(555000111) is True
    assert restarted.names() == {555000111: "Anna Petrova"}


def test_used_invite_does_not_work_twice(tmp_path: Path) -> None:
    """Главное правило: отпущенный юзернейм не пускает того, кто его занял.

    После активации ключом остаётся ID. Юзернейм, уже сработавший однажды,
    считается использованным — иначе освободившийся `@vasya`, занятый
    посторонним, открыл бы ему отчёты партнёров.
    """
    roster = Roster.load(tmp_path)
    roster.activate(555000111, Invite(username="apetrov", name="Anna Petrova"))

    assert roster.username_used("@APETROV") is True


def test_invite_without_name_leaves_name_to_profile(tmp_path: Path) -> None:
    roster = Roster.load(tmp_path)
    roster.activate(111, Invite(username="sidorov", name=None))

    assert roster.knows(111) is True
    assert roster.names() == {}


def test_broken_file_refuses_to_start(tmp_path: Path) -> None:
    """Битый файл — отказ, а не молчаливый сброс.

    Забытые связки означают, что аудиторы перестали входить, а бот об этом
    молчит: посторонним он не отвечает намеренно, и отличить «список пропал»
    от «меня не пригласили» человек на точке не может.
    """
    path = tmp_path / "access" / "roster.json"
    path.parent.mkdir(parents=True)
    path.write_text("{это не json", encoding="utf-8")

    with pytest.raises(BotConfigError, match="не разобрался"):
        Roster.load(tmp_path)


def test_write_leaves_no_temporary_file(tmp_path: Path) -> None:
    """Запись атомарна: временный файл не остаётся ни при каком исходе."""
    roster = Roster.load(tmp_path)
    roster.activate(111, Invite(username="sidorov", name=None))

    leftovers = [p.name for p in (tmp_path / "access").iterdir() if p.name != "roster.json"]
    assert leftovers == []


def test_stored_shape_is_readable_by_hand(tmp_path: Path) -> None:
    """Файл читается глазами: в него смотрят, когда выясняют, кто вошёл."""
    roster = Roster.load(tmp_path)
    roster.activate(555000111, Invite(username="apetrov", name="Anna Petrova"))

    stored = json.loads((tmp_path / "access" / "roster.json").read_text(encoding="utf-8"))
    entry = stored["entries"][0]
    assert entry["telegram_id"] == 555000111
    assert entry["username"] == "apetrov"
    assert entry["activated_at"]
