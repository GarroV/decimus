"""Журнал действий человека УК в пространстве партнёра (спека «Администрирование», D017).

Запись ложится тем же подключением, что и действие, и только при его коммите.
"""

from __future__ import annotations

import pytest
from conftest import requires_db
from db_harness import завести_пространства

psycopg = pytest.importorskip("psycopg")

from src.db.cross_space import Entry, entry_for, record  # noqa: E402
from src.db.web_access import password_hash  # noqa: E402
from src.domain.permissions import Actor, UnknownAction  # noqa: E402

pytestmark = requires_db


def _учётка_уК(pg_dsn: str) -> str:
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "insert into web_users (tenant_code, login, password_hash, role) "
            "values ('HQ', 'hq-journal', %s, 'hq_admin') returning id",
            (password_hash("пароль-журнала"),),
        )
        строка = cur.fetchone()
    assert строка is not None
    return str(строка[0])


def _уК(user_id: str | None = "u-1") -> Actor:
    return Actor(tenant="HQ", role="hq_admin", grants={}, user_id=user_id)


def test_своё_пространство_журнала_не_требует() -> None:
    assert entry_for(_уК(), object_tenant="HQ", action="inspection.retract", object_ref="x") is None


def test_чужое_пространство_даёт_запись() -> None:
    запись = entry_for(
        _уК(), object_tenant="GE", action="inspection.retract", object_ref="inspection:1"
    )
    assert запись == Entry("u-1", "HQ", "GE", "inspection.retract", "inspection:1")


def test_запись_без_учётки_это_ошибка_кода() -> None:
    with pytest.raises(ValueError, match="учётк"):
        entry_for(_уК(None), object_tenant="GE", action="inspection.retract", object_ref="x")


def test_код_не_из_каталога_это_ошибка_кода() -> None:
    with pytest.raises(UnknownAction):
        entry_for(_уК(), object_tenant="GE", action="inspection.delete", object_ref="x")


def test_запись_ложится_только_с_коммитом(pg_dsn: str, db_env: str) -> None:
    завести_пространства(pg_dsn, "GE")
    кто = _учётка_уК(pg_dsn)
    with psycopg.connect(db_env) as conn:
        record(conn, Entry(кто, "HQ", "GE", "inspection.retract", "inspection:откат"))
        conn.rollback()
    with psycopg.connect(db_env) as conn:
        record(conn, Entry(кто, "HQ", "GE", "inspection.retract", "inspection:коммит"))
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute("select object_ref from cross_space_actions order by id")
        assert cur.fetchall() == [("inspection:коммит",)]


def test_схема_не_принимает_действие_партнёра(pg_dsn: str) -> None:
    завести_пространства(pg_dsn, "GE")
    кто = _учётка_уК(pg_dsn)
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute(
                "insert into cross_space_actions "
                "(actor_web_user_id, actor_tenant, object_tenant, action_code, object_ref) "
                "values (%s, 'GE', 'HQ', 'inspection.retract', 'x')",
                (кто,),
            )


def test_роль_приложения_журнал_не_правит(pg_dsn: str, db_env: str) -> None:
    завести_пространства(pg_dsn, "GE")
    кто = _учётка_уК(pg_dsn)
    with psycopg.connect(db_env) as conn:
        record(conn, Entry(кто, "HQ", "GE", "inspection.move", "inspection:1"))
    with psycopg.connect(db_env) as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute("delete from cross_space_actions")


def test_схема_не_принимает_действие_не_от_ук(pg_dsn: str) -> None:
    """Обе границы держатся порознь: партнёр, действующий в ЧУЖОМ пространстве, тоже отказ."""
    завести_пространства(pg_dsn, "GE", "FR")
    кто = _учётка_уК(pg_dsn)
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute(
                "insert into cross_space_actions "
                "(actor_web_user_id, actor_tenant, object_tenant, action_code, object_ref) "
                "values (%s, 'GE', 'FR', 'inspection.retract', 'x')",
                (кто,),
            )
