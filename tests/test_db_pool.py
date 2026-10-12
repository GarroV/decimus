"""Пул соединений (`src/db/pool.py`): что не должно утечь между пользователями.

Соединение живёт дольше запроса. Всё, что запрос оставил на сессии — настройка,
роль, advisory-замок, — увидел бы следующий. У проекта роли и построчные
политики, поэтому утечка здесь — это утечка пространства между пользователями.
"""

from __future__ import annotations

import uuid

import pytest
from conftest import requires_db

psycopg = pytest.importorskip("psycopg")
from psycopg import sql  # noqa: E402

from src.db import pool  # noqa: E402

pytestmark = requires_db

#: Своё имя настройки: настоящую `decimus.*` тест не трогает.
CUSTOM = "decimus.pool_probe"


@pytest.fixture(autouse=True)
def _свежая_настройка() -> object:
    """Настройка пула читается один раз на процесс — каждому тесту нужна своя."""
    pool.close_pools()
    yield
    pool.close_pools()


@pytest.fixture
def one_connection(db_env: str, monkeypatch: pytest.MonkeyPatch) -> str:
    """Пул на одно соединение: второе использование гарантированно то же самое."""
    monkeypatch.setenv(pool.POOL_MAX_VAR, "1")
    return db_env


def _pid(conn: psycopg.Connection) -> int:
    return conn.info.backend_pid


def test_сессионные_настройки_не_переходят_к_следующему(one_connection: str) -> None:
    # Arrange — первый пользователь оставляет на сессии всё, что умеет.
    with pool.connection(one_connection) as conn:
        первый = _pid(conn)
        conn.execute("select set_config(%s, 'чужое', false)", (CUSTOM,))
        conn.execute("set statement_timeout = '7s'")
        conn.execute("select pg_advisory_lock(424242)")

    # Act
    with pool.connection(one_connection) as conn:
        второй = _pid(conn)
        значение = conn.execute("select current_setting(%s, true)", (CUSTOM,)).fetchone()
        срок = conn.execute("show statement_timeout").fetchone()
        замки = conn.execute(
            "select count(*) from pg_locks where locktype = 'advisory' and pid = pg_backend_pid()"
        ).fetchone()

    # Assert — это то же соединение (иначе тест ничего не доказывает) и оно чисто.
    assert второй == первый, "второй заход получил другое соединение — проверка пуста"
    assert значение is not None and not значение[0], f"настройка утекла: {значение}"
    assert срок is not None and срок[0] != "7s", "statement_timeout остался от прошлого"
    assert замки is not None and замки[0] == 0, "advisory-замок остался от прошлого"


def test_роль_сессии_не_переходит_к_следующему(pg_dsn: str, one_connection: str) -> None:
    # Arrange — роль, на которую роли приложения можно переключиться. Роль
    # общая на весь кластер, поэтому имя случайное и роль снимается за собой.
    имя = f"pool_probe_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(pg_dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("create role {} nologin").format(sql.Identifier(имя)))
        admin.execute(sql.SQL("grant {} to dodo_audit_app").format(sql.Identifier(имя)))
    try:
        with pool.connection(one_connection) as conn:
            исходная = conn.execute("select current_user").fetchone()
            conn.execute(sql.SQL("set role {}").format(sql.Identifier(имя)))
            assert conn.execute("select current_user").fetchone() == (имя,)

        # Act
        with pool.connection(one_connection) as conn:
            после = conn.execute("select current_user").fetchone()

        # Assert
        assert после == исходная, f"роль утекла: {после}"
    finally:
        pool.close_pools()
        with psycopg.connect(pg_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL("drop role {}").format(sql.Identifier(имя)))


def test_временная_таблица_не_переходит_к_следующему(one_connection: str) -> None:
    with pool.connection(one_connection) as conn:
        conn.execute("create temp table pool_probe_tmp (x int)")

    with pool.connection(one_connection) as conn:
        есть = conn.execute("select to_regclass('pg_temp.pool_probe_tmp')").fetchone()

    assert есть == (None,), "временная таблица осталась от прошлого"


def test_упавшая_транзакция_откатывается(pg_dsn: str, one_connection: str) -> None:
    # Arrange — настоящая таблица: временная пережила бы только то, что сброс не трогает.
    with psycopg.connect(pg_dsn, autocommit=True) as admin:
        admin.execute("create table pool_probe (x int)")
        admin.execute("grant all on pool_probe to dodo_audit_app")
    with pool.connection(one_connection) as conn:
        conn.execute("insert into pool_probe values (1)")

    # Act — исключение через границу `with`, как в двери.
    with pytest.raises(RuntimeError), pool.connection(one_connection) as conn:
        conn.execute("insert into pool_probe values (2)")
        raise RuntimeError("упали после записи")

    # Assert — вторая вставка откатилась, соединение снова рабочее.
    with pool.connection(one_connection) as conn:
        строки = conn.execute("select count(*) from pool_probe").fetchone()
    assert строки == (1,)


def test_нет_свободного_соединения_отказ_без_адреса(
    one_connection: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(pool.POOL_TIMEOUT_VAR, "0.3")

    with pool.connection(one_connection), pytest.raises(pool.PoolBusyError) as отказ:
        with pool.connection(one_connection):
            pytest.fail("второе соединение выдано при пуле на одно")

    # И DbError (для дверей), и psycopg.Error (для `except psycopg.Error`).
    assert isinstance(отказ.value, psycopg.Error)
    assert "host=" not in str(отказ.value)


def test_пул_выключен_каждое_обращение_своё(db_env: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(pool.POOL_MAX_VAR, "0")

    with pool.connection(db_env) as conn:
        первый = _pid(conn)
    with pool.connection(db_env) as conn:
        второй = _pid(conn)

    assert первый != второй


def test_недоступная_база_отказывает_сразу_а_не_по_таймауту_пула(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Пул молча пересоединяется в фоне; без пробы первого соединения отказ ждал бы 10 с."""
    import time

    monkeypatch.setenv(pool.POOL_TIMEOUT_VAR, "30")
    начало = time.monotonic()

    with pytest.raises(psycopg.OperationalError), pool.connection("host=127.0.0.1 port=1 dbname=x"):
        pytest.fail("соединение выдано с недоступной базой")

    assert time.monotonic() - начало < 5
    assert not pool._pools, "пул на недоступную базу остался в таблице"


@pytest.mark.parametrize("raw", ["abc", "-1", "2.5", "4 workers"])
def test_негодный_потолок_даёт_сообщение_и_значение_по_умолчанию(
    raw: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv(pool.POOL_MAX_VAR, raw)

    with caplog.at_level("ERROR", logger=pool.log.name):
        настройка = pool._settings()

    assert настройка.max_size == pool.DEFAULT_POOL_MAX
    assert [r.getMessage() for r in caplog.records if pool.POOL_MAX_VAR in r.getMessage()]


def test_нуль_выключает_пул_а_негодный_срок_берёт_умолчание(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv(pool.POOL_MAX_VAR, "0")
    monkeypatch.setenv(pool.POOL_TIMEOUT_VAR, "скоро")

    with caplog.at_level("ERROR", logger=pool.log.name):
        настройка = pool._settings()

    assert настройка.max_size == 0
    assert настройка.timeout_s == pool.DEFAULT_POOL_TIMEOUT_S
    assert any(pool.POOL_TIMEOUT_VAR in r.getMessage() for r in caplog.records)
