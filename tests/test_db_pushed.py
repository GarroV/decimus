"""`find_pushed`: где проверка чата лежит в истории и ждёт ли она приёмки (27.10.2026).

Нужна напоминанию бота «отчёт предварительный»: оно уходит только слитой и ещё
не принятой проверке, а повторная отправка отчёта ничего в историю не пишет.
Поэтому читающий вызов проверяется ещё и на то, что он НЕ создаёт строк.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import requires_db
from db_harness import accept_pushed

psycopg = pytest.importorskip("psycopg")

from src.db.push import push_inspection  # noqa: E402 — после importorskip намеренно
from src.db.pushed import find_pushed  # noqa: E402
from src.domain import add_finding, start_inspection  # noqa: E402

pytestmark = requires_db

АРЕНДАТОР = "HQ"


def _проверка(chat_id: int) -> None:
    start_inspection(chat_id, unit="Белград-1", kind="planned", report_lang="ru", tenant=АРЕНДАТОР)
    add_finding(chat_id, code="CLN05", level="D1", zone="hot_kitchen", text="нагар на печи")


def _сколько(dsn: str) -> int:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("select count(*) from inspections where tenant_code = %s", (АРЕНДАТОР,))
        row = cur.fetchone()
    assert row is not None
    return int(row[0])


def test_не_слитой_проверки_в_истории_нет_и_поиск_ничего_не_пишет(
    domain_env: Path, db_env: str
) -> None:
    _проверка(811)

    assert find_pushed(811) is None
    assert _сколько(db_env) == 0, "читающий вызов завёл строку в истории"


def test_слитая_проверка_ждёт_приёмки_а_принятая_нет(domain_env: Path, db_env: str) -> None:
    _проверка(812)
    ident = push_inspection(812)

    ждёт = find_pushed(812)
    assert ждёт is not None and ждёт.id == ident and ждёт.awaiting_acceptance

    accept_pushed(ident)
    принята = find_pushed(812)
    assert принята is not None and принята.id == ident
    assert not принята.awaiting_acceptance, "принятую проверку считают ждущей приёмки"
