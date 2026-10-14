"""Одно соединение на запрос страницы (`pool.shared_connections`, #732)."""

from __future__ import annotations

import pytest
from conftest import requires_db

psycopg = pytest.importorskip("psycopg")

from src.db import pool  # noqa: E402
from src.db.space import acting_space  # noqa: E402

pytestmark = requires_db

CUSTOM = "decimus.pool_probe"


@pytest.fixture(autouse=True)
def _свежая_настройка() -> object:
    pool.close_pools()
    yield
    pool.close_pools()


@pytest.fixture
def пул(db_env: str, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv(pool.POOL_MAX_VAR, "4")
    return db_env


def _pid(conn: psycopg.Connection) -> int:
    return conn.info.backend_pid


def test_чтения_запроса_идут_одним_соединением(пул: str) -> None:
    with pool.shared_connections():
        with pool.connection(пул) as a:
            первый = _pid(a)
        with pool.connection(пул) as b:
            второй = _pid(b)
    assert первый == второй


def test_каждый_блок_фиксируется_сам(pg_dsn: str, пул: str) -> None:
    """Записанное в одном блоке видно другому соединению до конца запроса."""
    with psycopg.connect(pg_dsn, autocommit=True) as admin:
        admin.execute("create table pool_shared_probe (n int)")
        admin.execute("grant select, insert on pool_shared_probe to dodo_audit_app")
    with pool.shared_connections():
        with pool.connection(пул) as conn:
            conn.execute("insert into pool_shared_probe values (7)")
        with psycopg.connect(пул) as другое:
            видно = другое.execute("select count(*) from pool_shared_probe").fetchone()
    assert видно == (1,)


def test_вложенный_блок_получает_другое_соединение(пул: str) -> None:
    with pool.shared_connections(), pool.connection(пул) as внешнее:
        with pool.connection(пул) as вложенное:
            assert _pid(вложенное) != _pid(внешнее)


def test_ошибка_откатывает_блок_и_соединение_годно_дальше(пул: str) -> None:
    with pool.shared_connections():
        with pytest.raises(psycopg.errors.DivisionByZero), pool.connection(пул) as conn:
            conn.execute("select 1/0")
        with pool.connection(пул) as conn:
            assert conn.execute("select 2").fetchone() == (2,)


def test_чужое_пространство_получает_своё_соединение(пул: str) -> None:
    with pool.shared_connections():
        with acting_space("AA"), pool.connection(пул) as a:
            первый = _pid(a)
            своё = a.execute("select current_setting('decimus.space', true)").fetchone()
        with acting_space("BB"), pool.connection(пул) as b:
            второй = _pid(b)
            чужое = b.execute("select current_setting('decimus.space', true)").fetchone()
    assert своё == ("AA",)
    assert чужое == ("BB",)
    assert первый != второй


def test_после_запроса_соединение_сброшено_для_следующего(пул: str) -> None:
    with pool.shared_connections(), pool.connection(пул) as conn:
        conn.execute("select set_config(%s, 'чужое', false)", (CUSTOM,))
    with pool.connection(пул) as conn:
        значение = conn.execute("select current_setting(%s, true)", (CUSTOM,)).fetchone()
    assert значение is not None and not значение[0]
