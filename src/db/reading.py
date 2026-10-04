"""Подключение на время чтения: отказ базы — `DbError`, а не пустая выдача.

Отдельный модуль, а не часть `queries`, потому что его делят `queries` и
`reach`, а `queries` сам знает `Reach`: общий помощник в одном из двух давал бы
цикл импорта (Н20).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg

from .config import check_environment, load_retraction_settings
from .errors import DbError


@contextmanager
def reading(что: str, *, as_admin: bool = False) -> Iterator[psycopg.Connection[Any]]:
    """Подключение на время чтения; отказ базы — `DbError`, а не пустая выдача.

    Пустой список вместо отказа означал бы «ничего не найдено» — а на деле
    прочитать не смогли, и это разные ответы. Наружу уходит тип исключения, а
    не его текст: в тексте драйвера может оказаться строка подключения.

    `as_admin` меняет не запрос, а РОЛЬ, под которой запрос идёт: снятые
    проверки прячет построчная политика (миграция `0010`), и увидеть их можно
    только придя администратором истории. Фильтра «показывать ли снятые» в
    тексте запросов нет и быть не должно — снятый фильтр не краснеет.
    """
    settings = load_retraction_settings() if as_admin else check_environment()
    try:
        with psycopg.connect(settings.dsn) as conn:
            yield conn
    except psycopg.Error as exc:
        raise DbError(f"Не удалось прочитать {что} ({type(exc).__name__})") from exc
