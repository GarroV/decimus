"""Сервисные токены API в настоящей базе (D356, D388): отпечаток, права, отзыв, журнал."""

from __future__ import annotations

from datetime import timedelta

import pytest
from conftest import requires_db

psycopg = pytest.importorskip("psycopg")

from src.db import api_access  # noqa: E402
from src.db.errors import AccessError  # noqa: E402
from src.db.mcp_access import token_fingerprint  # noqa: E402

pytestmark = requires_db


@pytest.fixture
def выдача(pg_dsn: str, db_env: str, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("DATABASE_ADMIN_URL", pg_dsn)
    return pg_dsn


def test_выпущенный_опознаётся_с_правами(выдача: str) -> None:
    выпущен = api_access.issue("swarm", (api_access.SCOPE_RATINGS_READ,), by="test")
    токен = api_access.resolve(выпущен.value)
    assert токен == api_access.ApiToken(выпущен.id, "swarm", (api_access.SCOPE_RATINGS_READ,))
    assert токен.allows(api_access.SCOPE_RATINGS_READ)
    assert not токен.allows(api_access.SCOPE_INSPECTIONS_READ)
    assert api_access.resolve(выпущен.value + "x") is None


def test_в_базе_только_отпечаток(выдача: str) -> None:
    выпущен = api_access.issue("swarm", api_access.SCOPES, by="test")
    with psycopg.connect(выдача) as conn, conn.cursor() as cur:
        cur.execute("select fingerprint, tokens::text from api.tokens where id = %s", (выпущен.id,))
        отпечаток, строка = cur.fetchone()
    assert отпечаток == token_fingerprint(выпущен.value)
    assert выпущен.value not in строка


def test_отозванный_не_опознаётся(выдача: str) -> None:
    выпущен = api_access.issue("swarm", api_access.SCOPES, by="test")
    assert api_access.revoke(выпущен.id, by="test")
    assert api_access.resolve(выпущен.value) is None
    assert not api_access.revoke(выпущен.id, by="test"), "второй отзыв — не живой токен"
    строка = next(т for т in api_access.list_tokens() if т.id == выпущен.id)
    assert строка.revoked_at is not None and строка.revoked_by == "test"


@pytest.mark.parametrize("права", [(), ("ratings:write",)])
def test_права_вне_перечня_не_выпускаются(выдача: str, права: tuple[str, ...]) -> None:
    with pytest.raises(AccessError):
        api_access.issue("swarm", права, by="test")


def test_схема_не_примет_чужое_право(выдача: str) -> None:
    with (
        psycopg.connect(выдача) as conn,
        conn.cursor() as cur,
        pytest.raises(psycopg.errors.CheckViolation),
    ):
        cur.execute(
            "insert into api.tokens (consumer, fingerprint, scopes, issued_by) "
            "values ('swarm', repeat('a', 64), array['admin'], 'test')"
        )


def test_роль_приложения_токен_не_выпустит(выдача: str, db_env: str) -> None:
    with (
        psycopg.connect(db_env) as conn,
        conn.cursor() as cur,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        cur.execute(
            "insert into api.tokens (consumer, fingerprint, scopes, issued_by) "
            "values ('swarm', repeat('b', 64), array['ratings:read'], 'test')"
        )


def test_журнал_считает_обращения_токена(выдача: str) -> None:
    выпущен = api_access.issue("swarm", api_access.SCOPES, by="test")
    другой = api_access.issue("swarm", api_access.SCOPES, by="test")
    for _ in range(3):
        api_access.log_access(выпущен.id, "/api/v1/ratings/scores", 200, "203.0.113.5")
    api_access.log_access(другой.id, "/api/v1/inspections", 200, None)
    api_access.log_access(None, "/api/v1/inspections", 401, "203.0.113.9")
    assert api_access.recent_requests(выпущен.id, timedelta(minutes=1)) == 3
    assert api_access.recent_requests(другой.id, timedelta(minutes=1)) == 1
