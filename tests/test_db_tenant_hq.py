"""Тенант УК переименован `default` → `HQ` (D234, #439): история уезжает целиком.

Ядро: код тенанта — ключ всех чтений истории. Проверка, оставшаяся под
`default`, после переименования пропала бы из админки и MCP без единой ошибки.
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest
from conftest import requires_db
from db_harness import empty_database

psycopg = pytest.importorskip("psycopg")

from src.db.migrate import MIGRATIONS_DIR, apply_migrations  # noqa: E402
from src.domain.tenants import canonical_tenant  # noqa: E402

pytestmark = requires_db

МИГРАЦИЯ = "0027_tenant_hq.sql"

_ЗАТРАВКА = """
insert into tenants (code, name) values ('default', 'УК');
insert into units (id, tenant_code, name, name_normalized)
    values (%(unit)s, 'default', 'Belgrade-1', 'belgrade-1');
insert into unit_aliases (tenant_code, alias_normalized, unit_id, alias)
    values ('default', 'белград-1', %(unit)s, 'Белград-1');
insert into phrase_aliases (tenant_code, lang, phrase_normalized, item_code, phrase)
    values ('default', 'ru', 'грязный пол', 'CLN05', 'грязный пол');
insert into inspections (tenant_code, unit_id, chat_id, kind, inspection_date, report_lang,
    ui_lang, speech_lang, checklist_version, pct, grade, source_fingerprint, status)
    values ('default', %(unit)s, 1, 'planned', '2026-09-20', 'ru', 'ru', 'ru', 'v1', 97.5, 'A',
            'fp-1', 'finalized');
"""


def _до_переименования(tmp_path: Path) -> Path:
    каталог = tmp_path / "migrations"
    каталог.mkdir()
    for файл in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if файл.name < МИГРАЦИЯ:
            shutil.copy(файл, каталог / файл.name)
    return каталог


def test_вся_история_уезжает_в_hq_и_ссылки_целы(tmp_path: Path) -> None:
    # Arrange — база до переименования, в ней принятая проверка УК под `default`.
    with empty_database() as dsn:
        apply_migrations(dsn, directory=_до_переименования(tmp_path))
        with psycopg.connect(dsn) as conn, conn.cursor() as cur:
            точка = {"unit": uuid.uuid4()}
            for запрос in filter(str.strip, _ЗАТРАВКА.split(";")):
                cur.execute(запрос, точка)
            conn.commit()

        # Act
        применено = apply_migrations(dsn)

        # Assert
        assert применено == [МИГРАЦИЯ]
        with psycopg.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("select code from tenants order by code")
            assert [r[0] for r in cur.fetchall()] == ["HQ"]
            for таблица in ("units", "unit_aliases", "phrase_aliases", "inspections"):
                cur.execute(f"select tenant_code, count(*) from {таблица} group by 1")  # noqa: S608
                assert cur.fetchall() == [("HQ", 1)], таблица
            # Составные ссылки вернулись: точка чужого тенанта не принимается.
            cur.execute(
                "select count(*) from pg_constraint where conname = any(%s)",
                (
                    [
                        "inspections_unit_same_tenant",
                        "inspection_moves_tenant_code_new_unit_id_fkey",
                        "inspection_moves_tenant_code_old_unit_id_fkey",
                        "unit_aliases_tenant_code_unit_id_fkey",
                    ],
                ),
            )
            assert cur.fetchone() == (4,)


def test_на_свежей_базе_переименовывать_нечего() -> None:
    with empty_database() as dsn:
        apply_migrations(dsn)
        with psycopg.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("select count(*) from tenants")
            assert cur.fetchone() == (0,)


@pytest.mark.parametrize(
    ("код", "нынешний"),
    [("default", "HQ"), (" default ", "HQ"), ("HQ", "HQ"), ("partner-a", "partner-a")],
)
def test_старый_код_тенанта_переводится_на_входе(код: str, нынешний: str) -> None:
    assert canonical_tenant(код) == нынешний
