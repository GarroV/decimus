"""Смена пароля отзывает подключения Claude (D417, LOW-4) — без базы.

Ядро: ошибка тихая — пароль сменён «потому что его узнали», а Claude, которому
вошедший по старому паролю успел разрешить доступ, продолжает ходить в MCP.
Живой путь до Postgres проверяет `tests/test_db_oauth_store.py`; здесь —
то, что можно проверить без базы: какие запросы шлёт смена командой и что
действующее определение функции смены с экрана отзывает подключения.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from src.db import web_access
from src.db.migrate import discover_migrations


class _Курсор:
    def __init__(self, журнал: list[tuple[str, Any]]) -> None:
        self._журнал = журнал

    def __enter__(self) -> _Курсор:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        self._журнал.append((" ".join(sql.split()), params))

    def fetchone(self) -> tuple[str, bool]:
        # Учётка нашлась; для смены почты — почта и правда сменилась.
        return ("11111111-1111-4111-8111-111111111111", True)


class _Подключение:
    def __init__(self, журнал: list[tuple[str, Any]]) -> None:
        self._журнал = журнал

    def cursor(self) -> _Курсор:
        return _Курсор(self._журнал)


def _записи(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Any]]:
    журнал: list[tuple[str, Any]] = []

    @contextmanager
    def _managing(_зачем: str) -> Iterator[_Подключение]:
        yield _Подключение(журнал)

    monkeypatch.setattr(web_access, "_managing", _managing)
    return журнал


def _проверить_отзыв(журнал: list[tuple[str, Any]], причина: str) -> None:
    """Коды гаснут, затем подключения отзываются — в той же транзакции и в этом порядке."""
    запросы = [sql for sql, _ in журнал]
    коды = [i for i, sql in enumerate(запросы) if sql.startswith("update oauth_codes")]
    отзыв = [i for i, sql in enumerate(запросы) if sql.startswith("update oauth_grants")]
    assert коды and отзыв, f"смена не отозвала подключения Claude: {запросы}"
    assert коды[0] < отзыв[0], "коды обязаны гаснуть ДО отзыва подключений (0054)"
    assert "set expires_at = now() where user_id = %s and used_at is null" in запросы[коды[0]]
    assert "where user_id = %s and revoked_at is null" in запросы[отзыв[0]]
    assert журнал[отзыв[0]][1][0] == причина


def test_смена_пароля_командой_отзывает_подключения(monkeypatch: pytest.MonkeyPatch) -> None:
    журнал = _записи(monkeypatch)

    assert web_access.change_password("anna", tenant="HQ", password="новый-пароль-учётки-anna")

    _проверить_отзыв(журнал, "password")


def test_смена_почты_отзывает_подключения(monkeypatch: pytest.MonkeyPatch) -> None:
    журнал = _записи(monkeypatch)

    assert web_access.set_email("anna", tenant="HQ", email="anna@example.com")

    _проверить_отзыв(журнал, "email")


def _последнее_определение(функция: str) -> str:
    """Тело функции из ПОСЛЕДНЕЙ миграции, которая её (пере)определяет, — оно и действует."""
    образец = re.compile(
        rf"create (?:or replace )?function {функция}\(.*?\$\$(.*?)\$\$", re.S | re.I
    )
    тела = [найдено.group(1) for м in discover_migrations() for найдено in образец.finditer(м.sql)]
    assert тела, f"функция {функция} не определена ни одной миграцией"
    return тела[-1]


def test_смена_своего_пароля_отзывает_подключения() -> None:
    тело = " ".join(_последнее_определение("change_own_password").split())

    assert "update public.oauth_grants set revoked_at = now(), revoked_reason = 'password'" in (
        тело
    )
    assert "where user_id = чей and revoked_at is null" in тело
    коды = (
        "update public.oauth_codes set expires_at = now() where user_id = чей and used_at is null"
    )
    assert коды in тело
    assert тело.index(коды) < тело.index("update public.oauth_grants"), (
        "коды обязаны гаснуть ДО отзыва подключений: иначе подключение, выпущенное "
        "параллельным обменом кода, уцелеет"
    )


def test_ротация_refresh_держит_строку_подключения() -> None:
    """Без замка на `oauth_grants` ротация, начатая до отзыва, выпустила бы пару после него."""
    from src.db import oauth_store

    запрос = " ".join(oauth_store._LOCK_REFRESH_SQL.split())

    assert запрос.endswith("for update of t, g")
