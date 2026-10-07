"""Проверка помнит учётку, которая её занесла (D311): «свои» решаются по ней."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import requires_db
from db_harness import слить_проверку

psycopg = pytest.importorskip("psycopg")

from src.db.queries import get_inspection  # noqa: E402
from src.db.reach import reach_of  # noqa: E402
from src.db.web_access import password_hash  # noqa: E402
from src.domain import get_state, start_inspection  # noqa: E402

pytestmark = requires_db
ТОЧКА = "Белград-автор"


def _учётка(pg_dsn: str) -> str:
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "insert into web_users (tenant_code, login, password_hash, role) "
            "values ('HQ', 'hq-author', %s, 'hq_staff') returning id",
            (password_hash("пароль-автора-1"),),
        )
        строка = cur.fetchone()
    assert строка is not None
    return str(строка[0])


def test_автор_едет_из_состояния_в_базу(domain_env: Path, db_env: str, pg_dsn: str) -> None:
    кто = _учётка(pg_dsn)
    ident = слить_проверку(unit=ТОЧКА, tenant="HQ", author_user_id=кто, accept=False)
    карточка = get_inspection(ident, reach=reach_of("HQ"), include_on_review=True)
    assert карточка is not None and карточка.inspection.created_by == кто


def test_проверка_без_учётки_ложится_без_автора(domain_env: Path, db_env: str, pg_dsn: str) -> None:
    ident = слить_проверку(unit=ТОЧКА, tenant="HQ", accept=False)
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute("select created_by from inspections where id = %s", (ident,))
        assert cur.fetchone() == (None,)
    карточка = get_inspection(ident, reach=reach_of("HQ"), include_on_review=True)
    assert карточка is not None and карточка.inspection.created_by == ""


def test_автор_сохраняется_в_состоянии_чата(domain_env: Path) -> None:
    start_inspection(
        9100, unit=ТОЧКА, kind="planned", report_lang="ru", tenant="HQ", author_user_id="u-77"
    )
    состояние = get_state(9100)
    assert состояние is not None and состояние.author_user_id == "u-77"


def test_автор_не_входит_в_отпечаток(domain_env: Path, db_env: str, pg_dsn: str) -> None:
    кто = _учётка(pg_dsn)
    первая = слить_проверку(unit=ТОЧКА, tenant="HQ", chat_id=9101, accept=False)
    вторая = слить_проверку(unit=ТОЧКА, tenant="HQ", chat_id=9101, author_user_id=кто, accept=False)
    assert первая == вторая
