"""F-012 аудита 12.10: текст ошибки драйвера не доходит до экрана партнёра.

`directory.list_units` заворачивает исключение psycopg в `PushError` с `{exc}`
внутри; до правки обработчик `DbError` отдавал `public_reason(exc)` = `str(exc)`
в `error_db.html`, и партнёр на `/units/<id>` (маршрут вне разделов, открыт
любому вошедшему) видел хост, адрес и роль базы. #515 требует, чтобы карта
стенда вошедшему, в том числе партнёру, не показывалась.

Подключение подменено исключением с ВЫДУМАННЫМИ хостом и ролью: настоящая база
не нужна. Набор ПАДАЕТ, если текст драйвера снова дойдёт до страницы.
"""

from __future__ import annotations

import psycopg
import pytest

from src.db import directory
from tests.web_harness import войти, подменить_двери, собрать

PARTNER = "PARTNER1"
FAKE_HOST = "db-host.example.invalid"
FAKE_ROLE = "fake_app_role"


def _упасть(*_args: object, **_kwargs: object) -> None:
    raise psycopg.OperationalError(
        f'connection to server at "{FAKE_HOST}" (192.0.2.10), port 5432 failed: '
        f'FATAL:  password authentication failed for user "{FAKE_ROLE}"'
    )


def test_partner_unit_page_hides_driver_error_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://user@localhost:5432/db")
    monkeypatch.setattr(directory.psycopg, "connect", _упасть)
    подменить_двери(monkeypatch, tenant=PARTNER, role="admin")
    client = собрать(tenant=PARTNER).test_client()
    войти(client)

    ответ = client.get("/units/any-unit")
    текст = ответ.get_data(as_text=True)

    assert ответ.status_code == 503  # дошли до обработчика DbError, а не до заслона
    assert FAKE_HOST not in текст
    assert FAKE_ROLE not in текст
