"""Токены API (`src/db/api_tokens.py`, миграция `0041`) — тесты уровня базы.

Ядро доступа (#567, #568, D336): значения токена в базе нет, роль приложения
не выпускает и не переписывает токены, отзыв окончателен. Токены генерируются
в тесте и нигде не лежат.
"""

from __future__ import annotations

from typing import Any

import pytest
from conftest import requires_db
from db_harness import set_retraction_env

psycopg = pytest.importorskip("psycopg")

from src.db import api_tokens  # noqa: E402
from src.db.errors import AccessError  # noqa: E402
from src.db.mcp_access import token_fingerprint  # noqa: E402

pytestmark = requires_db


@pytest.fixture
def admin_env(db_env: str, monkeypatch: pytest.MonkeyPatch) -> str:
    return set_retraction_env(db_env, monkeypatch)


def _выполнить(dsn: str, sql: str, params: tuple[Any, ...] = ()) -> int:
    with psycopg.connect(dsn) as conn:
        return conn.execute(sql, params).rowcount


def test_выпущенный_токен_открывает_свои_права(admin_env: str) -> None:
    выпущен = api_tokens.issue("swarm", scopes=["ratings:read"], by="tester")

    потребитель = api_tokens.resolve(выпущен.value)

    assert потребитель is not None
    assert потребитель.consumer == "swarm"
    assert потребитель.scopes == frozenset({"ratings:read"})
    assert выпущен.value not in repr(выпущен)


def test_в_базе_только_отпечаток(admin_env: str, db_env: str) -> None:
    выпущен = api_tokens.issue("swarm", scopes=["ratings:read"], by="tester")

    with psycopg.connect(admin_env) as conn:
        строки = conn.execute("select fingerprint from api_tokens").fetchall()

    assert строки == [(token_fingerprint(выпущен.value),)]


def test_сырой_токен_в_колонку_не_ложится(admin_env: str) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        _выполнить(
            admin_env,
            "insert into api_tokens (consumer, scopes, fingerprint, issued_by) "
            "values ('swarm', array['ratings:read'], %s, 't')",
            (api_tokens.new_token(),),
        )


def test_неизвестное_право_не_ложится(admin_env: str) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        _выполнить(
            admin_env,
            "insert into api_tokens (consumer, scopes, fingerprint, issued_by) "
            "values ('swarm', array['ratings:write'], %s, 't')",
            ("a" * 64,),
        )
    with pytest.raises(AccessError):
        api_tokens.issue("swarm", scopes=["ratings:write"], by="tester")


def test_отозванный_не_находится(admin_env: str) -> None:
    выпущен = api_tokens.issue("swarm", scopes=["ratings:read"], by="tester")

    assert api_tokens.revoke(выпущен.id, by="tester") is True

    assert api_tokens.resolve(выпущен.value) is None
    assert api_tokens.revoke(выпущен.id, by="tester") is False


def test_отзыв_не_снимается(admin_env: str) -> None:
    выпущен = api_tokens.issue("swarm", scopes=["ratings:read"], by="tester")
    api_tokens.revoke(выпущен.id, by="tester")

    снято = _выполнить(
        admin_env,
        "update api_tokens set revoked_at = null, revoked_by = null where id = %s",
        (выпущен.id,),
    )

    assert снято == 0
    assert api_tokens.resolve(выпущен.value) is None


def test_роль_приложения_не_выпускает(admin_env: str, db_env: str) -> None:
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        _выполнить(
            db_env,
            "insert into api_tokens (consumer, scopes, fingerprint, issued_by) "
            "values ('evil', array['inspections:read'], %s, 't')",
            ("b" * 64,),
        )


def test_роль_приложения_не_расширяет_права(admin_env: str, db_env: str) -> None:
    выпущен = api_tokens.issue("swarm", scopes=["ratings:read"], by="tester")

    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        _выполнить(
            db_env,
            "update api_tokens set scopes = array['ratings:read','inspections:read'] where id = %s",
            (выпущен.id,),
        )


def test_роль_приложения_не_отзывает_и_не_подменяет(admin_env: str, db_env: str) -> None:
    выпущен = api_tokens.issue("swarm", scopes=["ratings:read"], by="tester")

    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        _выполнить(
            db_env, "update api_tokens set fingerprint = %s where id = %s", ("c" * 64, выпущен.id)
        )
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        _выполнить(db_env, "delete from api_tokens where id = %s", (выпущен.id,))


def test_использование_отмечается(admin_env: str) -> None:
    выпущен = api_tokens.issue("swarm", scopes=["inspections:read"], by="tester")
    assert api_tokens.list_tokens()[0].last_used_at is None

    api_tokens.resolve(выпущен.value)

    (строка,) = api_tokens.list_tokens()
    assert строка.last_used_at is not None
    assert строка.issued_by == "tester"


def test_чужая_форма_не_доходит_до_базы(admin_env: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://nobody@127.0.0.1:1/none")

    assert api_tokens.resolve("not-a-token") is None
    assert api_tokens.resolve("dcm_" + "x" * 10) is None
