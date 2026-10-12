"""Сервисные токены API в настоящей базе (D356, D388): отпечаток, права, отзыв, журнал."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

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
    выпущен = api_access.issue("swarm", (api_access.SCOPE_RATING_SCORES,), by="test")
    токен = api_access.resolve(выпущен.value)
    assert токен == api_access.ApiToken(выпущен.id, "swarm", (api_access.SCOPE_RATING_SCORES,))
    assert токен.allows(api_access.SCOPE_RATING_SCORES)
    assert not токен.allows(api_access.SCOPE_INSPECTION_DETAIL)
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


@pytest.mark.parametrize("права", [(), ("ratings:write",), ("ratings:read",)])
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
            "values ('swarm', repeat('b', 64), array['ratings:scores'], 'test')"
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


def test_просроченный_не_опознаётся(выдача: str) -> None:
    вчера = datetime.now(UTC) - timedelta(days=1)
    завтра = datetime.now(UTC) + timedelta(days=1)
    старый = api_access.issue("svc", api_access.SCOPES, by="test", expires_at=вчера)
    живой = api_access.issue("svc", api_access.SCOPES, by="test", expires_at=завтра)
    assert api_access.resolve(старый.value) is None, "просроченный токен пускает"
    assert api_access.resolve(живой.value) is not None


def test_страны_имя_контакт_и_правка_без_нового_ключа(выдача: str) -> None:
    выпущен = api_access.issue(
        "roga",
        (api_access.SCOPE_MAPS,),
        by="test",
        title="Рога и копыта",
        contact="ops@example.com",
        countries=("TR",),
    )
    assert api_access.resolve(выпущен.value).countries == ("TR",)
    assert api_access.update(
        выпущен.id,
        (api_access.SCOPE_MAPS, api_access.SCOPE_AGGREGATORS),
        title="Рога и копыта",
        contact=None,
        expires_at=None,
        countries=None,
    )
    токен = api_access.resolve(выпущен.value)
    assert токен.countries is None and токен.allows(api_access.SCOPE_AGGREGATORS)
    строка = next(т for т in api_access.list_tokens() if т.id == выпущен.id)
    assert (строка.name, строка.contact) == ("Рога и копыта", None)


def test_перевыпуск_гасит_старый_и_сохраняет_права(выдача: str) -> None:
    выпущен = api_access.issue(
        "roga", (api_access.SCOPE_MAPS,), by="test", title="Рога", countries=("TR",)
    )
    новый = api_access.reissue(выпущен.id, by="test")
    assert новый is not None and новый.value != выпущен.value
    assert api_access.resolve(выпущен.value) is None
    токен = api_access.resolve(новый.value)
    assert токен.scopes == (api_access.SCOPE_MAPS,) and токен.countries == ("TR",)
    assert api_access.reissue(выпущен.id, by="test") is None, "отозванный перевыпустился"


def test_схема_не_примет_кривую_страну(выдача: str) -> None:
    with (
        psycopg.connect(выдача) as conn,
        conn.cursor() as cur,
        pytest.raises(psycopg.errors.CheckViolation),
    ):
        cur.execute(
            "insert into api.tokens (consumer, fingerprint, scopes, issued_by, countries) "
            "values ('svc', repeat('c', 64), array['maps:ratings'], 'test', array['tr'])"
        )


def test_журнал_по_дням_и_последние_обращения(выдача: str) -> None:
    выпущен = api_access.issue("svc", api_access.SCOPES, by="test")
    api_access.log_access(выпущен.id, "/api/v1/maps/ratings", 200, None)
    api_access.log_access(выпущен.id, "/api/v1/maps/ratings", 403, None)
    (день,) = api_access.usage(выпущен.id, days=7)
    assert (день.calls, день.errors) == (2, 1)
    assert [строка.status for строка in api_access.recent_log(выпущен.id, limit=5)] == [403, 200]
    строка = next(т for т in api_access.list_tokens() if т.id == выпущен.id)
    assert (строка.calls_week, строка.errors_week) == (2, 1)
    assert строка.last_used_at is not None
