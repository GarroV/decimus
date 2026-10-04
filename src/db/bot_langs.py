"""Язык бота, выбранный человеком (D303, #411): чтение и запись.

Строка на Telegram ID (`0035_bot_ui_langs.sql`). Заведён ли язык в словаре
бота, здесь не решается — это знает бот (`src/bot/texts.py: UI_LANGS`); база
держит только форму кода.

Отказ базы — `AccessError` (через `_connected`), а не `None`: «выбора нет» и
«не смогли посмотреть» — разные ответы, и бот обязан их различать.
"""

from __future__ import annotations

from .web_access import _connected

_CHOSEN_SQL = "select ui_lang from bot_ui_langs where telegram_id = %s"
_CHOOSE_SQL = """
    insert into bot_ui_langs (telegram_id, ui_lang) values (%s, %s)
    on conflict (telegram_id) do update
       set ui_lang = excluded.ui_lang, chosen_at = now()
"""


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
