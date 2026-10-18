"""D507: слив кладёт в базу разбивку по процессам ровно такой, какой её вернул движок.

Ядро: цифры, которые партнёр и сеть читают как факт. Колонка `by_process`
пишется сливом, а долив принятых проверок идёт под администратором истории и
только из NULL (сторож `inspections_by_process_guarded`, 0073).
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest
from conftest import requires_db
from db_harness import accept_pushed, set_retraction_env

psycopg = pytest.importorskip("psycopg")

from src.db.push import push_inspection  # noqa: E402
from src.domain import add_finding, start_inspection  # noqa: E402
from src.domain import score as domain_score  # noqa: E402

pytestmark = requires_db

ЗАПРОС = "select by_process, deductions from inspections where id = %s"


@pytest.fixture
def admin_env(db_env: str, monkeypatch: pytest.MonkeyPatch) -> str:
    return set_retraction_env(db_env, monkeypatch)


def _начать(chat_id: int) -> None:
    start_inspection(chat_id, unit="Белград-1", kind="planned", report_lang="ru")
    add_finding(chat_id, code="CLN05", level="D1", zone="hot_kitchen", text="нагар на печи")
    add_finding(chat_id, code="CLN06", level="D1", zone="hot_kitchen", text="течь под мойкой")


def _строка(dsn: str, sql: str, params: tuple[Any, ...]) -> tuple[Any, ...]:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        assert row is not None
        return row


def _выполнить(dsn: str, sql: str, params: tuple[Any, ...]) -> None:
    with psycopg.connect(dsn) as conn:
        conn.execute(sql, params)
        conn.commit()


def test_слив_кладёт_разбивку_движка_и_вклады_сходятся_с_вычетом(
    domain_env: Path, db_env: str
) -> None:
    # Arrange
    _начать(1)
    эталон = domain_score(1)

    # Act
    ident = push_inspection(1)
    хранится, вычет = _строка(db_env, ЗАПРОС, (ident,))

    # Assert
    assert эталон.by_process, "движок не вернул разбивку — проверка ничего не проверяет"
    assert хранится == {k: asdict(v) for k, v in эталон.by_process.items()}
    сумма = sum(p["loss"] for p in хранится.values())
    assert сумма > 0, "вклады нулевые — сходство с вычетом ничего не значит"
    assert сумма == pytest.approx(float(вычет), abs=0.05)


def test_долив_принятой_проверки_пишется_один_раз_и_только_из_пустого(
    domain_env: Path, db_env: str, admin_env: str
) -> None:
    # Arrange — проверка, слитая «до миграции»: разбивки нет; принимаем её.
    _начать(2)
    ident = push_inspection(2)
    _выполнить(db_env, "update inspections set by_process = null where id = %s", (ident,))
    accept_pushed(ident)

    # Act — долив под администратором истории из NULL проходит
    _выполнить(admin_env, "update inspections set by_process = '{}'::jsonb where id = %s", (ident,))

    # Assert — а переписать уже записанное нельзя
    with pytest.raises(psycopg.errors.CheckViolation, match="нельзя переписать"):
        _выполнить(
            admin_env,
            "update inspections set by_process = '{\"x\": 1}'::jsonb where id = %s",
            (ident,),
        )


def test_администратор_истории_не_трогает_оценку_принятой_проверки(
    domain_env: Path, db_env: str, admin_env: str
) -> None:
    """Грант на колонку узкий: процент править через него по-прежнему нельзя."""
    # Arrange
    _начать(3)
    ident = push_inspection(3)
    accept_pushed(ident)

    # Act / Assert
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        _выполнить(admin_env, "update inspections set pct = 100 where id = %s", (ident,))
