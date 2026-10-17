"""Окружение блока `bot`: токен, режим запуска, имена проверяющих."""

from __future__ import annotations

import pytest

from src.bot.config import BotSettings, load_bot_settings
from src.bot.errors import BotConfigError


def test_list_of_ids_is_not_required_any_more() -> None:
    """D520: `ALLOWED_TELEGRAM_IDS` больше не вход — бот поднимается без него."""
    settings = load_bot_settings({"TELEGRAM_BOT_TOKEN": "123:abc"})
    assert not hasattr(settings, "allowed_ids")


def test_loads_settings_from_mapping() -> None:
    env = {
        "TELEGRAM_BOT_TOKEN": "123:abc",
        "BOT_MODE": "polling",
    }
    settings = load_bot_settings(env)
    assert settings == BotSettings(
        token="123:abc",
        mode="polling",
        auditor_names={},
    )


def test_missing_token_is_config_error() -> None:
    env = {"BOT_MODE": "polling"}
    with pytest.raises(BotConfigError, match="TELEGRAM_BOT_TOKEN"):
        load_bot_settings(env)


def test_default_mode_is_polling() -> None:
    env = {"TELEGRAM_BOT_TOKEN": "123:abc"}
    assert load_bot_settings(env).mode == "polling"


def test_unknown_mode_is_config_error() -> None:
    env = {
        "TELEGRAM_BOT_TOKEN": "123:abc",
        "BOT_MODE": "carrier-pigeon",
    }
    with pytest.raises(BotConfigError, match="carrier-pigeon"):
        load_bot_settings(env)


def test_reads_from_real_os_environ_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "999:zzz")
    monkeypatch.setenv("BOT_MODE", "polling")
    settings = load_bot_settings()
    assert settings.token == "999:zzz"


def test_auditor_names_are_parsed_into_map() -> None:
    """Имя проверяющего берётся по Telegram ID (T063): карта «ID:имя» через запятую."""
    env = {
        "TELEGRAM_BOT_TOKEN": "123:abc",
        "AUDITOR_NAMES": "111:Владимир Гарро, 222 : Пётр Петров ",
    }
    assert load_bot_settings(env).auditor_names == {111: "Владимир Гарро", 222: "Пётр Петров"}


def test_auditor_names_absent_is_empty_map_not_failure() -> None:
    """Переменная необязательна: без неё имя берётся из профиля Telegram."""
    env = {"TELEGRAM_BOT_TOKEN": "123:abc"}
    assert load_bot_settings(env).auditor_names == {}


def test_auditor_names_without_colon_is_config_error() -> None:
    """Молча пропустить кривую запись нельзя: имя молча уедет из профиля, а не из карты."""
    env = {
        "TELEGRAM_BOT_TOKEN": "123:abc",
        "AUDITOR_NAMES": "Владимир Гарро",
    }
    with pytest.raises(BotConfigError, match="AUDITOR_NAMES"):
        load_bot_settings(env)


def test_auditor_names_with_non_numeric_id_is_config_error() -> None:
    env = {
        "TELEGRAM_BOT_TOKEN": "123:abc",
        "AUDITOR_NAMES": "garro:Владимир Гарро",
    }
    with pytest.raises(BotConfigError, match="AUDITOR_NAMES"):
        load_bot_settings(env)


def test_name_for_id_outside_allowed_list_is_accepted() -> None:
    """D286: привязавший бота через веб в списке разрешённых не стоит, а имя ему нужно."""
    settings = load_bot_settings(
        {
            "TELEGRAM_BOT_TOKEN": "123:abc",
            "AUDITOR_NAMES": "555000111:Пётр Петров",
        }
    )
    assert settings.auditor_names == {555000111: "Пётр Петров"}


def test_invites_variable_is_no_longer_read() -> None:
    """Приглашения по юзернейму сняты: прежняя переменная не открывает доступ."""
    settings = load_bot_settings(
        {
            "TELEGRAM_BOT_TOKEN": "123:abc",
            "BOT_INVITES": "apetrov:Anna Petrova",
        }
    )
    assert not hasattr(settings, "invites")
