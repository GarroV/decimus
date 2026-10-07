# tests/test_db_roles_migration.py
"""Миграция `0038`: роли по умолчанию и перенос учёток (спека «Администрирование», D310, D311).

Ядро (права): каждая текущая учётка получает роль по таблице переноса, засев
совпадает с `DEFAULT_MATRIX`, роль чужого охвата не ложится никому.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from conftest import requires_db
from db_harness import empty_database

psycopg = pytest.importorskip("psycopg")

from src.db.migrate import MIGRATIONS_DIR, apply_migrations  # noqa: E402
from src.db.web_access import password_hash  # noqa: E402
from src.domain.permissions import DEFAULT_MATRIX, ROLE_SCOPES  # noqa: E402

pytestmark = requires_db

МИГРАЦИЯ = "0038_roles.sql"
ХЕШ = password_hash("пароль-для-переноса")


def _каталог(tmp_path: Path, *, включая: bool) -> Path:
    каталог = tmp_path / ("по" if включая else "до")
    каталог.mkdir()
    for файл in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if файл.name < МИГРАЦИЯ or (включая and файл.name == МИГРАЦИЯ):
            shutil.copy(файл, каталог / файл.name)
    return каталог


def test_каждая_учётка_получает_роль_по_таблице(tmp_path: Path) -> None:
    with empty_database() as dsn:
        apply_migrations(dsn, directory=_каталог(tmp_path, включая=False))
        with psycopg.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("insert into tenants (code) values ('GE')")
            for tenant, login, role in (
                ("HQ", "hq-admin", "admin"),
                ("HQ", "hq-auditor", "auditor"),
                ("GE", "ge-admin", "admin"),
                ("GE", "ge-auditor", "auditor"),
            ):
                cur.execute(
                    "insert into web_users (tenant_code, login, password_hash, role) "
                    "values (%s, %s, %s, %s)",
                    (tenant, login, ХЕШ, role),
                )
        assert apply_migrations(dsn, directory=_каталог(tmp_path, включая=True)) == [МИГРАЦИЯ]
        with psycopg.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("select login, role from web_users order by login")
            assert cur.fetchall() == [
                ("ge-admin", "country_admin"),
                ("ge-auditor", "country_staff"),
                ("hq-admin", "hq_admin"),
                ("hq-auditor", "hq_staff"),
            ]


def test_засев_ролей_равен_матрице_по_умолчанию(pg_dsn: str) -> None:
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute("select code, scope from roles")
        assert dict(cur.fetchall()) == dict(ROLE_SCOPES)
        cur.execute("select role_code, action_code, reach from role_permissions")
        засев: dict[str, dict[str, str]] = {}
        for роль, код, охват in cur.fetchall():
            засев.setdefault(роль, {})[код] = охват
        assert засев == {р: dict(п) for р, п in DEFAULT_MATRIX.items()}


def test_свои_не_ложатся_на_действие_не_над_проверкой(pg_dsn: str) -> None:
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.errors.CheckViolation) as отказ:
            cur.execute(
                "update role_permissions set reach = 'own' "
                "where role_code = 'hq_staff' and action_code = 'checklist.edit'"
            )
        assert отказ.value.diag.constraint_name == "role_permissions_own_on_inspection"


def test_роль_чужого_охвата_не_ложится(pg_dsn: str) -> None:
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute("insert into tenants (code) values ('GE')")
        with pytest.raises(psycopg.errors.CheckViolation) as отказ:
            cur.execute(
                "insert into web_users (tenant_code, login, password_hash, role) "
                "values ('GE', 'ge-intruder', %s, 'hq_admin')",
                (ХЕШ,),
            )
        assert отказ.value.diag.constraint_name == "web_users_role_scope"


def test_незаведённая_роль_не_ложится(pg_dsn: str) -> None:
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            cur.execute(
                "insert into web_users (tenant_code, login, password_hash, role) "
                "values ('HQ', 'hq-ghost', %s, 'admin')",
                (ХЕШ,),
            )


def test_смена_пространства_проверяет_охват_роли(pg_dsn: str) -> None:
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute("insert into tenants (code) values ('GE')")
        cur.execute(
            "insert into web_users (tenant_code, login, password_hash, role) "
            "values ('HQ', 'hq-mover', %s, 'hq_staff')",
            (ХЕШ,),
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute("update web_users set tenant_code = 'GE' where login = 'hq-mover'")
