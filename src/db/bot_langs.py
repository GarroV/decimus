"""Язык бота, выбранный человеком (D303, #411): чтение и запись.

Строка на Telegram ID (`0035_bot_ui_langs.sql`). Заведён ли язык в словаре
бота, здесь не решается — это знает бот (`src/bot/texts.py: UI_LANGS`); база
держит только форму кода.

Отказ базы — `AccessError`, а не `None`: «выбора нет» и «не смогли
посмотреть» — разные ответы, и бот обязан их различать.

**Подключение своё, с коротким сроком** (ревью #492, п.1). Выбор языка нужен
на каждом сообщении человека, и у него есть честное умолчание, поэтому ждать
базу дольше `CONNECT_TIMEOUT_S` секунд незачем. Общее `web_access._connected`
срока не задаёт, и менять его ради этого модуля значило бы менять поведение
всем остальным его вызовам.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg

from .config import check_environment
from .errors import AccessError

#: Сколько ждать установления связи с базой, секунд (минимум libpq — 2).
CONNECT_TIMEOUT_S = 3

_CHOSEN_SQL = "select ui_lang from bot_ui_langs where telegram_id = %s"
_CHOOSE_SQL = """
    insert into bot_ui_langs (telegram_id, ui_lang) values (%s, %s)
    on conflict (telegram_id) do update
       set ui_lang = excluded.ui_lang, chosen_at = now()
"""


@contextmanager
def _connected(зачем: str) -> Iterator[psycopg.Connection[Any]]:
    """Подключение роли приложения с коротким сроком. Наружу — ТИП ошибки, не текст.

    В тексте psycopg может оказаться строка подключения целиком — тот же приём,
    что у `web_access._connected`.
    """
    settings = check_environment()
    try:
        with psycopg.connect(settings.dsn, connect_timeout=CONNECT_TIMEOUT_S) as conn:
            yield conn
    except psycopg.Error as exc:
        raise AccessError(f"Не удалось {зачем} ({type(exc).__name__})") from exc


def chosen_lang(telegram_id: int) -> str | None:
    """Язык, который человек выбрал сам, — или `None`, если не выбирал."""
    with _connected("прочитать выбранный язык бота") as conn, conn.cursor() as cur:
        cur.execute(_CHOSEN_SQL, (telegram_id,))
        row = cur.fetchone()
    return None if row is None else str(row[0])


def choose_lang(telegram_id: int, lang: str) -> None:
    """Запомнить выбор человека. Повторный выбор перезаписывает прежний."""
    with _connected("сохранить выбранный язык бота") as conn, conn.cursor() as cur:
        cur.execute(_CHOOSE_SQL, (telegram_id, lang))
