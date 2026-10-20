"""Ключи iSpring для загрузчика: база, затем окружение (`src/db/service_keys.resolve`)."""

from __future__ import annotations

from src.db import service_keys

from .ispring import Client

SERVICE = "ispring"


def client() -> Client | None:
    """Клиент iSpring или `None`, если нет хотя бы одного из двух ключей."""
    client_id = service_keys.resolve(SERVICE, "client_id")
    client_secret = service_keys.resolve(SERVICE, "client_secret")
    if not client_id or not client_secret:
        return None
    return Client(client_id, client_secret)
