"""Окружение веб-админки: адрес, порт, тенант, язык интерфейса.

Та же форма проверки, что у бота (`tests/test_bot_config.py`): окружение
приходит аргументом `env=`, а не через `monkeypatch.setenv`, — так значения
видны в самом тесте, а не в отдельном шаге поверх него.
"""

from __future__ import annotations

import pytest

from src.web.config import DEFAULT_PORT, Settings, load_settings
from src.web.errors import WebConfigError, WebTextError


def test_loads_settings_from_full_environment() -> None:
    env = {
        "WEB_HOST": "localhost",
        "WEB_PORT": "18280",
        "WEB_TENANT": "belgrade",
        "WEB_UI_LANG": "en",
    }
    assert load_settings(env) == Settings(
        host="localhost", port=18280, tenant="belgrade", ui_lang="en"
    )


@pytest.mark.parametrize(
    "env",
    [
        {},
        {"WEB_TENANT": "   "},
    ],
)
def test_missing_or_blank_tenant_is_config_error(env: dict[str, str]) -> None:
    with pytest.raises(WebConfigError, match="WEB_TENANT"):
        load_settings(env)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", "127.0.0.1"),
        ("localhost", "localhost"),
        ("::1", "::1"),
    ],
)
def test_loopback_host_is_accepted(raw: str, expected: str) -> None:
    env = {"WEB_TENANT": "belgrade", "WEB_HOST": raw}
    assert load_settings(env).host == expected


@pytest.mark.parametrize("raw", ["0.0.0.0", "192.168.1.10", "не-адрес"])  # noqa: S104
def test_non_loopback_host_is_config_error(raw: str) -> None:
    """У админки нет аутентификации: слушать что-то кроме петли наружу — отказ."""
    env = {"WEB_TENANT": "belgrade", "WEB_HOST": raw}
    with pytest.raises(WebConfigError):
        load_settings(env)


def test_empty_port_defaults_to_default_port() -> None:
    env = {"WEB_TENANT": "belgrade"}
    assert load_settings(env).port == DEFAULT_PORT


def test_port_is_parsed_from_string() -> None:
    env = {"WEB_TENANT": "belgrade", "WEB_PORT": "18280"}
    assert load_settings(env).port == 18280


@pytest.mark.parametrize("raw", ["восемь", "80", "70000"])
def test_bad_port_is_config_error(raw: str) -> None:
    env = {"WEB_TENANT": "belgrade", "WEB_PORT": raw}
    with pytest.raises(WebConfigError):
        load_settings(env)


def test_unknown_ui_lang_is_text_error_not_config_error() -> None:
    """Язык разбирает каталог текстов, а не конфиг, — и отказ соответствующего типа."""
    env = {"WEB_TENANT": "belgrade", "WEB_UI_LANG": "de"}
    with pytest.raises(WebTextError):
        load_settings(env)
