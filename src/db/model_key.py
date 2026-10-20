"""Ключ модели из базы (D491): тонкая обёртка над общим хранилищем `service_keys` (D576).

Ключ провайдера вставляет главный админ на экране «Подключения». Запись называется
`model_key` и лежит там же, где ключи остальных сервисов; вся механика (шифрование, кэш на
минуту, сброс при записи, отказ чтения не роняет разбор, значение нигде не пишется) —
в `src/db/service_keys.py`. Здесь остались имя записи и вызовы, которыми пользуется
`recognize`.
"""

from __future__ import annotations

from . import service_keys
from .errors import AccessError  # noqa: F401 — часть прежнего интерфейса модуля
from .service_keys import CACHE_SECONDS, KeyStatus  # noqa: F401

NAME = "model_key"


def stored_key() -> str | None:
    """Ключ модели из базы (расшифрованный) или `None`; кэш и отказ чтения — как у всех."""
    return service_keys.stored(NAME)


def status() -> KeyStatus | None:
    """Запись о ключе без самого ключа; `None` — в базе ключа нет."""
    return service_keys.status(NAME)
