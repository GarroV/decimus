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
    def __init__(self, журнал: list[str]) -> None:
        self._журнал = журнал

    def __enter__(self) -> _Курсор:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, sql: str, _params: Any = None) -> None:
        self._журнал.append(" ".join(sql.split()))

    def fetchone(self) -> tuple[str]:
        return ("11111111-1111-4111-8111-111111111111",)


class _Подключение:
    def __init__(self, журнал: list[str]) -> None:
        self._журнал = журнал

    def cursor(self) -> _Курсор:
        return _Курсор(self._журнал)


def test_смена_пароля_командой_отзывает_подключения(monkeypatch: pytest.MonkeyPatch) -> None:
    журнал: list[str] = []

    @contextmanager
    def _managing(_зачем: str) -> Iterator[_Подключение]:
        yield _Подключение(журнал)

    monkeypatch.setattr(web_access, "_managing", _managing)

    assert web_access.change_password("anna", tenant="HQ", password="новый-пароль-учётки-anna")

    отзыв = [sql for sql in журнал if sql.startswith("update oauth_grants")]
    assert отзыв, f"смена пароля не отозвала подключения Claude: {журнал}"
    assert "revoked_reason = 'password'" in отзыв[0]
    assert "where user_id = %s and revoked_at is null" in отзыв[0]
    коды = [sql for sql in журнал if sql.startswith("update oauth_codes")]
    assert коды, f"смена пароля не погасила необменянные коды: {журнал}"
    assert "set expires_at = now() where user_id = %s and used_at is null" in коды[0]


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
    assert (
        "update public.oauth_codes set expires_at = now() where user_id = чей and used_at is null"
        in тело
    )
