"""Окружение веб-админки: адрес, порт, тенант, язык интерфейса.

Та же форма проверки, что у бота (`tests/test_bot_config.py`): окружение
приходит аргументом `env=`, а не через `monkeypatch.setenv`, — так значения
видны в самом тесте, а не в отдельном шаге поверх него.
"""

from __future__ import annotations

import pytest

from src.web.config import DEFAULT_PORT, MIN_SECRET_KEY_LENGTH, Settings, load_settings
from src.web.errors import WebConfigError, WebTextError

КЛЮЧ = "ключ-подписи-длиной-не-меньше-тридцати-двух-знаков"


def test_loads_settings_from_full_environment() -> None:
    env = {
        "WEB_HOST": "localhost",
        "WEB_PORT": "18280",
        "WEB_TENANT": "belgrade",
        "WEB_UI_LANG": "en",
        "WEB_SECRET_KEY": КЛЮЧ,
    }
    assert load_settings(env) == Settings(
        host="localhost", port=18280, tenant="belgrade", ui_lang="en", secret_key=КЛЮЧ
    )


def test_secret_key_is_made_up_for_this_run_when_not_set() -> None:
    """Незаданный ключ не мешает подняться, но об этом обязано быть сказано.

    Случайные 32 байта сильнее любого ключа, который вписали бы «чтобы
    запустилось»; платится за это тем, что сессии не переживают перезапуск, —
    и признак этого едет в настройках, а не остаётся догадкой.
    """
    settings = load_settings({"WEB_TENANT": "belgrade"})
    assert settings.secret_key_is_ephemeral is True
    assert len(settings.secret_key) >= MIN_SECRET_KEY_LENGTH


def test_two_runs_without_the_variable_do_not_share_a_key() -> None:
    """Иначе «сделан на этот запуск» означало бы один и тот же ключ у всех."""
    первый = load_settings({"WEB_TENANT": "belgrade"}).secret_key
    второй = load_settings({"WEB_TENANT": "belgrade"}).secret_key
    assert первый != второй


def test_short_secret_key_is_refused() -> None:
    """Слабый ключ подбирается, а подобранный — это вход без пароля."""
    with pytest.raises(WebConfigError, match="WEB_SECRET_KEY"):
        load_settings({"WEB_TENANT": "belgrade", "WEB_SECRET_KEY": "коротко"})


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
    """Наружу выходим туннелем (D100): слушать что-то кроме петли — отказ."""
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


# --- прослушивание сети контейнера за общим прокси (переезд на VPS) --------


@pytest.mark.parametrize("raw", ["0.0.0.0", "::", "172.18.0.5"])  # noqa: S104
def test_network_host_is_accepted_only_with_explicit_opt_in(raw: str) -> None:
    """За общим Caddy в сети контейнеров петля недостижима, а звена нет (VPS).

    Разрешение только явным ключом: без него прежний отказ сохраняется, и
    ошибка в конфигурации не открывает админку в сеть молча.
    """
    env = {"WEB_TENANT": "belgrade", "WEB_HOST": raw, "WEB_LISTEN_NETWORK": "1"}
    assert load_settings(env).host == raw


def test_opt_in_does_not_accept_a_non_address() -> None:
    env = {"WEB_TENANT": "belgrade", "WEB_HOST": "не-адрес", "WEB_LISTEN_NETWORK": "1"}
    with pytest.raises(WebConfigError):
        load_settings(env)


@pytest.mark.parametrize("flag", ["", "0"])
def test_opt_in_off_keeps_the_loopback_rule(flag: str) -> None:
    env = {"WEB_TENANT": "belgrade", "WEB_HOST": "0.0.0.0", "WEB_LISTEN_NETWORK": flag}  # noqa: S104
    with pytest.raises(WebConfigError):
        load_settings(env)


@pytest.mark.parametrize("flag", ["yes", "true", "2"])
def test_opt_in_typo_is_config_error_not_silent_no(flag: str) -> None:
    env = {"WEB_TENANT": "belgrade", "WEB_LISTEN_NETWORK": flag}
    with pytest.raises(WebConfigError, match="WEB_LISTEN_NETWORK"):
        load_settings(env)
