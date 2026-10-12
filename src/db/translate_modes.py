"""Перевод комментариев на язык отчёта, выбранный аудитором (D443): чтение и запись.

Строка на Telegram ID (`0058_translate_modes.sql`), тот же приём, что у
`bot_langs` (D303), `finish_modes` (D439): подключение своё, с коротким сроком, наружу — тип ошибки.
Нет строки — умолчание `DEFAULT_MODE` (по кнопке, D394); его применяет вызывающий,
а здесь «не выбирал» (`None`) и «не смогли посмотреть» (`AccessError`) —
разные ответы.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg

from .config import check_environment
from .errors import AccessError

#: Переводит сам аудитор кнопкой под полем (D394).
BUTTON = "button"
#: Комментарии переводятся при сборке отчёта (D443).
AUTO = "auto"
MODES = (BUTTON, AUTO)
DEFAULT_MODE = BUTTON

#: Сколько ждать установления связи с базой, секунд (минимум libpq — 2).
CONNECT_TIMEOUT_S = 3

_CHOSEN_SQL = "select mode from translate_modes where telegram_id = %s"
_CHOOSE_SQL = """
    insert into translate_modes (telegram_id, mode) values (%s, %s)
    on conflict (telegram_id) do update
       set mode = excluded.mode, chosen_at = now()
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


def chosen_translate_mode(telegram_id: int) -> str | None:
    """Режим, который человек выбрал сам, — или `None`, если не выбирал."""
    with _connected("прочитать режим перевода") as conn, conn.cursor() as cur:
        cur.execute(_CHOSEN_SQL, (telegram_id,))
        row = cur.fetchone()
    return None if row is None else str(row[0])


def choose_translate_mode(telegram_id: int, mode: str) -> None:
    """Запомнить выбор человека. Режим вне `MODES` — отказ до базы."""
    if mode not in MODES:
        raise ValueError(f"Режим перевода «{mode}» не заведён. Доступны: {', '.join(MODES)}")
    with _connected("сохранить режим перевода") as conn, conn.cursor() as cur:
        cur.execute(_CHOOSE_SQL, (telegram_id, mode))
