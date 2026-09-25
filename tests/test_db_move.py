"""D195: перенос сданной проверки по дате и пиццерии — с историей каждой правки.

Проверяется то, что держит БАЗА, а не вызов: перенос мимо истории невозможен,
историю нельзя дописать руками, содержимое проверки переносом не трогается,
а обычной роли перенос недоступен вовсе.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest
from conftest import requires_db
from db_harness import set_retraction_env

psycopg = pytest.importorskip("psycopg")

from src.db.errors import MoveError  # noqa: E402
from src.db.move import list_moves, move_inspection  # noqa: E402
from src.db.push import push_inspection  # noqa: E402
from src.db.queries import get_inspection, unit_ids  # noqa: E402
from src.db.retract import retract_inspection  # noqa: E402
from src.domain import add_finding, start_inspection  # noqa: E402

pytestmark = requires_db

ТОЧКА = "Белград-1"
ДРУГАЯ = "Белград-2"
НОВАЯ_ДАТА = date(2026, 9, 1)
ПРИЧИНА = "аудитор выбрал не ту точку"


@pytest.fixture
def admin_env(db_env: str, monkeypatch: pytest.MonkeyPatch) -> str:
    return set_retraction_env(db_env, monkeypatch)


def _проверка(chat_id: int, *, точка: str = ТОЧКА) -> str:
    start_inspection(chat_id, unit=точка, kind="planned", report_lang="ru", tenant="default")
    add_finding(chat_id, code="CLN05", level="D1", zone="hot_kitchen", text="нагар на печи")
    return push_inspection(chat_id)


def _id_точки(название: str) -> str:
    return unit_ids(tenant="default")[название]


def _выполнить(dsn: str, sql: str, params: tuple[Any, ...] = ()) -> int:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        conn.commit()
        return cur.rowcount


# --- перенос и его след -----------------------------------------------------------


def test_перенос_меняет_шапку_и_оставляет_след(domain_env: Path, admin_env: str) -> None:
    # Arrange
    ident = _проверка(801)
    _проверка(802, точка=ДРУГАЯ)  # заводит вторую точку в справочнике
    до = get_inspection(ident, tenant="default")
    assert до is not None

    # Act
    изменено = move_inspection(
        ident,
        tenant="default",
        new_date=НОВАЯ_ДАТА,
        new_unit_id=_id_точки(ДРУГАЯ),
        reason=ПРИЧИНА,
        actor="admin",
    )

    # Assert — шапка другая, документ тот же, след один и полный.
    после = get_inspection(ident, tenant="default")
    assert изменено is True
    assert после is not None
    assert после.inspection.unit_name == ДРУГАЯ
    assert после.inspection.inspection_date == НОВАЯ_ДАТА
    assert (после.inspection.pct, после.inspection.grade) == (
        до.inspection.pct,
        до.inspection.grade,
    )
    assert [f.code for f in после.findings] == [f.code for f in до.findings]
    [след] = list_moves(ident, tenant="default")
    assert (след.old_unit, след.new_unit) == (ТОЧКА, ДРУГАЯ)
    assert (след.old_date, след.new_date) == (
        до.inspection.inspection_date.isoformat(),
        "2026-09-01",
    )
    assert (след.reason, след.moved_by) == (ПРИЧИНА, "admin")


def test_перенос_в_то_же_место_следа_не_оставляет(domain_env: Path, admin_env: str) -> None:
    # Arrange
    ident = _проверка(803)
    до = get_inspection(ident, tenant="default")
    assert до is not None

    # Act
    изменено = move_inspection(
        ident,
        tenant="default",
        new_date=до.inspection.inspection_date,
        new_unit_id=_id_точки(ТОЧКА),
        reason=ПРИЧИНА,
        actor="admin",
    )

    # Assert
    assert изменено is False
    assert list_moves(ident, tenant="default") == ()


# --- отказы -------------------------------------------------------------------------


def test_без_причины_перенос_отказан(domain_env: Path, admin_env: str) -> None:
    ident = _проверка(804)
    with pytest.raises(MoveError, match="повод"):
        move_inspection(
            ident,
            tenant="default",
            new_date=НОВАЯ_ДАТА,
            new_unit_id=_id_точки(ТОЧКА),
            reason="  ",
            actor="admin",
        )


def test_отклонённую_не_переносят(domain_env: Path, admin_env: str) -> None:
    ident = _проверка(805)
    retract_inspection(ident, tenant="default", reason="дубль")
    with pytest.raises(MoveError, match="отклонена"):
        move_inspection(
            ident,
            tenant="default",
            new_date=НОВАЯ_ДАТА,
            new_unit_id=_id_точки(ТОЧКА),
            reason=ПРИЧИНА,
            actor="admin",
        )


def test_чужой_пиццерии_перенос_отказан(domain_env: Path, admin_env: str) -> None:
    ident = _проверка(806)
    with pytest.raises(MoveError, match="справочнике"):
        move_inspection(
            ident,
            tenant="default",
            new_date=НОВАЯ_ДАТА,
            new_unit_id="00000000-0000-0000-0000-000000000000",
            reason=ПРИЧИНА,
            actor="admin",
        )


# --- что держит база, а не вызов ----------------------------------------------------


def test_прямая_правка_шапки_без_причины_отказана_базой(domain_env: Path, admin_env: str) -> None:
    # Arrange — мимо move_inspection, сырым SQL под администратором истории.
    ident = _проверка(807)

    # Act / Assert — след обязателен, и держит его триггер.
    with pytest.raises(psycopg.errors.CheckViolation):
        _выполнить(
            admin_env,
            "update inspections set inspection_date = %s where id = %s",
            (НОВАЯ_ДАТА, ident),
        )
    assert list_moves(ident, tenant="default") == ()


def test_историю_нельзя_дописать_руками(domain_env: Path, admin_env: str) -> None:
    # Arrange
    ident = _проверка(808)
    точка = _id_точки(ТОЧКА)

    # Act / Assert — прямой записи в историю не выдано даже администратору.
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        _выполнить(
            admin_env,
            "insert into inspection_moves (tenant_code, inspection_id, old_date, new_date,"
            " old_unit_id, new_unit_id, reason, moved_by)"
            " values ('default', %s, %s, %s, %s, %s, 'выдумка', 'кто-то')",
            (ident, НОВАЯ_ДАТА, date(2026, 9, 2), точка, точка),
        )


def test_обычная_роль_шапку_сданной_не_правит(domain_env: Path, db_env: str) -> None:
    # Arrange
    ident = _проверка(809)

    # Act — роль приложения: политика 0004/0010 молча не видит строки для записи.
    обновлено = _выполнить(
        db_env, "update inspections set inspection_date = %s where id = %s", (НОВАЯ_ДАТА, ident)
    )

    # Assert
    assert обновлено == 0


def test_администратор_не_правит_содержимое(domain_env: Path, admin_env: str) -> None:
    # Arrange — перенос открыл две колонки шапки, и только их.
    ident = _проверка(810)

    # Act / Assert
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        _выполнить(admin_env, "update inspections set pct = 100 where id = %s", (ident,))
