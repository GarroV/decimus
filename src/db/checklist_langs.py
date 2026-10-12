"""Язык чек-листа, выбранный аудитором при старте проверки (D451): чтение и запись.

Строка на Telegram ID (`0057_checklist_langs.sql`), тот же приём, что у
`finish_modes` (D449): подключение своё, с коротким сроком, наружу — тип ошибки.
Нет строки — `None`: умолчание применяет вызывающий. «Не выбирал» (`None`) и
«не смогли посмотреть» (`AccessError`) — разные ответы.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg

from .config import check_environment
from .errors import AccessError

#: Сколько ждать установления связи с базой, секунд (минимум libpq — 2).
CONNECT_TIMEOUT_S = 3

#: Код языка — как проверка в базе: строчные латинские буквы.
_LANG_CODE = re.compile(r"^[a-z]{2,8}$")

_CHOSEN_SQL = "select lang from checklist_langs where telegram_id = %s"
_CHOOSE_SQL = """
    insert into checklist_langs (telegram_id, lang) values (%s, %s)
    on conflict (telegram_id) do update
       set lang = excluded.lang, chosen_at = now()
"""


@contextmanager
def _connected(зачем: str) -> Iterator[psycopg.Connection[Any]]:
    """Подключение роли приложения с коротким сроком. Наружу — ТИП ошибки, не текст."""
    settings = check_environment()
    try:
        with psycopg.connect(settings.dsn, connect_timeout=CONNECT_TIMEOUT_S) as conn:
            yield conn
    except psycopg.Error as exc:
        raise AccessError(f"Не удалось {зачем} ({type(exc).__name__})") from exc


def chosen_checklist_lang(telegram_id: int) -> str | None:
    """Язык чек-листа, который человек выбрал в прошлый раз, — или `None`."""
    with _connected("прочитать язык чек-листа") as conn, conn.cursor() as cur:
        cur.execute(_CHOSEN_SQL, (telegram_id,))
        row = cur.fetchone()
    return None if row is None else str(row[0])


def choose_checklist_lang(telegram_id: int, lang: str) -> None:
    """Запомнить выбор человека. Код не языка — отказ до базы."""
    if not _LANG_CODE.fullmatch(lang):
        raise ValueError(f"Код языка чек-листа «{lang}» не разбирается")
    with _connected("сохранить язык чек-листа") as conn, conn.cursor() as cur:
        cur.execute(_CHOOSE_SQL, (telegram_id, lang))
