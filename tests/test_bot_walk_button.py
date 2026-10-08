"""#418: кнопка «Обход точки» — есть ровно тогда, когда задан адрес мини-аппа."""

from __future__ import annotations

import pytest

from src.bot.config import BotConfigError, load_bot_settings
from src.bot.keyboards import walk_keyboard

ОКРУЖЕНИЕ = {"TELEGRAM_BOT_TOKEN": "1:x", "ALLOWED_TELEGRAM_IDS": "1"}


def test_без_адреса_кнопки_нет_и_бот_прежний() -> None:
    assert load_bot_settings(ОКРУЖЕНИЕ).walk_url is None
    assert walk_keyboard("ru", None) is None


def test_адрес_даёт_кнопку_мини_аппа() -> None:
    адрес = "https://example.org/tg/walk"
    settings = load_bot_settings({**ОКРУЖЕНИЕ, "BOT_WALK_URL": адрес})

    клавиатура = walk_keyboard("ru", settings.walk_url)

    assert клавиатура is not None
    кнопка = клавиатура.inline_keyboard[0][0]
    assert кнопка.web_app is not None and кнопка.web_app.url == адрес
    assert кнопка.text == "Обход точки"


def test_не_https_адрес_отказ_на_старте() -> None:
    with pytest.raises(BotConfigError, match="https"):
        load_bot_settings({**ОКРУЖЕНИЕ, "BOT_WALK_URL": "http://example.org/tg/walk"})


def test_круг_тестеров_кнопка_только_им() -> None:
    """Пробный запуск на боевом боте: остальным бот прежний, без кнопки."""
    адрес = "https://example.org/tg/walk"
    settings = load_bot_settings({**ОКРУЖЕНИЕ, "BOT_WALK_URL": адрес, "WALK_USERS": "7, 8"})

    assert settings.walk_url_for(7) == адрес
    assert settings.walk_url_for(1) is None
    assert walk_keyboard("ru", settings.walk_url_for(1)) is None


def test_без_круга_кнопка_всем_с_доступом() -> None:
    адрес = "https://example.org/tg/walk"
    settings = load_bot_settings({**ОКРУЖЕНИЕ, "BOT_WALK_URL": адрес})
    assert settings.walk_url_for(1) == адрес


def test_кривой_круг_тестеров_отказ_на_старте() -> None:
    with pytest.raises(BotConfigError, match="WALK_USERS"):
        load_bot_settings({**ОКРУЖЕНИЕ, "WALK_USERS": "Вася"})
