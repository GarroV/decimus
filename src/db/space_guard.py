"""Пространство записи обязано быть заведено — опечатка в коде это отказ (#481).

До #481 двери базы перед записью вставляли строку в `tenants` с `on conflict do
nothing`, и опечатка в коде пространства молча заводила новое пустое
пространство — запись уезжала туда, где её никто не увидит. Пространства
заводит команда (`make space`, `src/db/spaces.py`), строку `HQ` — схема
(`0029`); остальные двери только сверяются.

Сверка идёт ТЕМ ЖЕ курсором, что и запись: в одной транзакции между «есть» и
«пишем» ничего не вклинится. Отказ — тип вызывающего блока: у каждой двери свой
словарь отказов, и вызывающие ловят именно его.
"""

from __future__ import annotations

from typing import Any

import psycopg

from .errors import DbError

_SPACE_EXISTS_SQL = "select 1 from tenants where code = %s"


def missing_space_text(code: str) -> str:
    """Текст отказа — один на все двери: что не так и кто заводит пространства."""
    return (
        f"Пространства «{code}» нет. Пространства заводит команда `make space` — "
        f"опечатка в коде пространства не заводит новое молча"
    )


def require_space(cur: psycopg.Cursor[Any], code: str, *, error: type[DbError]) -> None:
    """Отказать (`error`), если пространства `code` нет. Курсор — тот, что пишет."""
    cur.execute(_SPACE_EXISTS_SQL, (code,))
    if cur.fetchone() is None:
        raise error(missing_space_text(code))
