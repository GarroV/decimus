"""Сторожа схемы пространств (волна 1, #340): ответ не зависит от роли пишущего.

Проверку пишут две роли: приложение (слив) и администратор истории (перенос).
Сторож точки проверки работает правами владельца, поэтому его отказ — один и
тот же, какие бы права на справочник ни были у пишущей роли.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import requires_db

psycopg = pytest.importorskip("psycopg")

from db_harness import (  # noqa: E402
    admin_role_dsn,
    привязать_страну,
    слить_проверку,
    точка_справочника,
)

pytestmark = requires_db

ВСТАВКА = (
    "insert into inspections (tenant_code, unit_id, chat_id, kind, inspection_date, "
    "report_lang, ui_lang, speech_lang, checklist_version, pct, grade, source_fingerprint) "
    "values ('GE', %s, 1, 'planned', '2026-09-03', 'ru', 'ru', 'ru', 'v1', 100, 'A', %s)"
)


@pytest.fixture
def сеть(pg_dsn: str, db_env: str, domain_env: Path) -> dict[str, str]:
    """Batumi-1 (GE) и Yerevan-1 (AM) в справочнике УК; GE привязано к GE.

    У обеих пишущих ролей отнято чтение `space_countries` и `units`: сторож
    обязан отвечать правами владельца, а не их.
    """
    батуми = точка_справочника("Batumi-1", country="GE", city="Batumi")
    ереван = точка_справочника("Yerevan-1", country="AM", city="Yerevan")
    привязать_страну(pg_dsn, tenant="GE", country="GE")
    проверка = слить_проверку(unit="Batumi-1", tenant="GE")
    with psycopg.connect(pg_dsn) as conn:
        for роль in ("dodo_audit_app", "dodo_audit_admin"):
            conn.execute(f"revoke select on space_countries, units from {роль}")  # noqa: S608
    return {"батуми": батуми, "ереван": ереван, "проверка": проверка}


def test_вставка_приложением_идёт_правами_владельца(сеть: dict[str, str], db_env: str) -> None:
    with psycopg.connect(db_env) as conn, conn.cursor() as cur:
        cur.execute(ВСТАВКА, (сеть["батуми"], "сторож-свой"))
        with pytest.raises(psycopg.errors.RaiseException, match="не из справочника страны"):
            cur.execute(ВСТАВКА, (сеть["ереван"], "сторож-чужой"))


def test_перенос_администратором_идёт_правами_владельца(сеть: dict[str, str], db_env: str) -> None:
    with psycopg.connect(admin_role_dsn(db_env)) as conn, conn.cursor() as cur:
        cur.execute("select set_config('decimus.move_reason', 'тест сторожа', true)")
        cur.execute("select set_config('decimus.move_actor', 'тест', true)")
        with pytest.raises(psycopg.errors.RaiseException, match="не из справочника страны"):
            cur.execute(
                "update inspections set unit_id = %s where id = %s",
                (сеть["ереван"], сеть["проверка"]),
            )
