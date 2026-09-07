"""Приглашения по Telegram-юзернейму (задача #230).

Числовой ID нового аудитора неоткуда взять заранее: Bot API не отдаёт его по
юзернейму, а сам ID приходит только в апдейте — то есть после того, как
человек уже написал. Поэтому стенд называет юзернеймы, а ID бот узнаёт при
первом контакте.
"""

from __future__ import annotations

import pytest

from src.bot.errors import BotConfigError
from src.bot.invites import Invite, StaticInvites, normalize_username, parse_invites


def test_username_normalizes_at_sign_and_case() -> None:
    """@Ivanov, ivanov и IVANOV — один человек: юзернеймы Telegram
    регистронезависимы, и `@` человек пишет по привычке."""
    assert normalize_username("@Ivanov") == "ivanov"
    assert normalize_username("  IVANOV ") == "ivanov"


def test_invite_carries_name_for_report_header() -> None:
    invites = parse_invites("apetrov:Anna Petrova")
    assert invites == {"apetrov": Invite(username="apetrov", name="Anna Petrova")}


def test_invite_without_name_is_allowed() -> None:
    """Имя необязательно: без него сработает запасной источник — профиль."""
    assert parse_invites("@Sidorov") == {"sidorov": Invite(username="sidorov", name=None)}


def test_several_invites_and_blank_pieces() -> None:
    invites = parse_invites(" apetrov:Anna Petrova , , @Kuznetsov56 ")
    assert set(invites) == {"apetrov", "kuznetsov56"}


def test_empty_value_is_empty_map() -> None:
    """Переменная необязательна: стенд без приглашений обязан подниматься."""
    assert parse_invites("") == {}


def test_duplicate_username_is_rejected() -> None:
    """Две записи на один юзернейм — заявка на то, что имя в отчёте зависит от
    порядка строк в файле. Отказ на старте, а не молчаливый выбор последней."""
    with pytest.raises(BotConfigError, match="дважды"):
        parse_invites("apetrov:Anna Petrova,@APETROV:Пётр")


def test_empty_name_after_colon_is_rejected() -> None:
    with pytest.raises(BotConfigError, match="пустое имя"):
        parse_invites("apetrov:")


def test_username_with_space_is_rejected() -> None:
    """Частая опечатка — вписать в поле юзернейма имя человека."""
    with pytest.raises(BotConfigError, match="не похоже на юзернейм"):
        parse_invites("Anna Petrova")


def test_static_source_finds_invite_regardless_of_case() -> None:
    source = StaticInvites(parse_invites("apetrov:Anna Petrova"))
    assert source.find("@APETROV") == Invite(username="apetrov", name="Anna Petrova")
    assert source.find("someone_else") is None


def test_static_source_without_username_finds_nothing() -> None:
    """Апдейт без юзернейма (человек его не завёл) не активирует ничего."""
    source = StaticInvites(parse_invites("apetrov:Anna Petrova"))
    assert source.find(None) is None
