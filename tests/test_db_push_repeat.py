"""#359: пометка повтора доезжает от аудитора до базы и обратно.

Правило D191 («повтор стоит вдвое») живёт в движке, но запись проверки идёт
через домен и базу. Пока пометка теряется по дороге, проверка, проведённая
ботом или вебом, отметить повтор не может вовсе — и удвоение существует только
на папочных проверках.

Это ядро: цена записи читается партнёром как факт и обжалуется деньгами.
Потерянная по дороге пометка не роняет ничего — она просто делает проверку
дешевле, чем посчитал бы аудитор, и молча.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import requires_db

psycopg = pytest.importorskip("psycopg")

from src.db.push import push_inspection  # noqa: E402
from src.db.queries import findings_by_unit, get_inspection  # noqa: E402
from src.domain import add_finding, start_inspection  # noqa: E402

pytestmark = requires_db

ТЕНАНТ = "default"


def _строки(dsn: str, sql: str, params: tuple[object, ...] = ()) -> list[tuple[object, ...]]:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def _проверка_с_повтором(chat_id: int) -> None:
    start_inspection(chat_id, unit="Белград-1", kind="planned", report_lang="ru")
    add_finding(
        chat_id, code="CLN05", level="D1", zone="hot_kitchen", text="нагар", repeat=True
    )
    add_finding(chat_id, code="CLN06", level="D1", zone="hot_kitchen", text="течь")


def test_слив_переносит_пометку_повтора(domain_env: Path, db_env: str) -> None:
    _проверка_с_повтором(1)

    inspection_id = push_inspection(1)

    отметки = _строки(
        db_env,
        "select code, repeat from findings where inspection_id = %s order by n",
        (inspection_id,),
    )
    assert отметки == [("CLN05", True), ("CLN06", False)]


def test_чтение_проверки_отдаёт_пометку(domain_env: Path, db_env: str) -> None:
    _проверка_с_повтором(1)
    inspection_id = push_inspection(1)

    detail = get_inspection(inspection_id, tenant=ТЕНАНТ)

    assert detail is not None
    assert {f.code: f.repeat for f in detail.findings} == {"CLN05": True, "CLN06": False}


def test_находки_точки_отдают_пометку(domain_env: Path, db_env: str) -> None:
    # Карточка точки читает историю именно этой выборкой: без пометки здесь
    # экран не сможет отличить «встречалось» от «засчитано вдвое».
    _проверка_с_повтором(1)
    push_inspection(1)

    записи = findings_by_unit(tenant=ТЕНАНТ, unit="Белград-1")

    assert {f.code: f.repeat for f in записи} == {"CLN05": True, "CLN06": False}


def test_запись_без_пометки_ложью_не_становится(domain_env: Path, db_env: str) -> None:
    # Обратная сторона: колонка с умолчанием `false` означает «не отмечено», а
    # не «неизвестно». Проверки, слитые до появления колонки, обязаны читаться
    # как обычные, а не как повторы.
    start_inspection(2, unit="Белград-2", kind="planned", report_lang="ru")
    add_finding(2, code="CLN05", level="D1", zone="hot_kitchen", text="нагар")

    inspection_id = push_inspection(2)

    (строка,) = _строки(
        db_env, "select repeat from findings where inspection_id = %s", (inspection_id,)
    )
    assert строка == (False,)
