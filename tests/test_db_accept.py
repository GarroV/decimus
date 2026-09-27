"""D199: этап приёмки — слитая проверка ждёт подтверждения человеком.

Проверяется то, что держит БАЗА, а не вызов: слив кладёт проверку на приёмку
и запечатать её не может, в историю сети ждущая не попадает, подтверждает
только администратор истории, а обратного хода нет.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from conftest import requires_db
from db_harness import admin_role_dsn, set_retraction_env

psycopg = pytest.importorskip("psycopg")

from src.db.accept import accept_inspection  # noqa: E402
from src.db.errors import AcceptError  # noqa: E402
from src.db.push import push_inspection  # noqa: E402
from src.db.queries import (  # noqa: E402
    class_counts,
    findings_by_unit,
    get_inspection,
    list_inspections,
)
from src.domain import add_finding, start_inspection  # noqa: E402

pytestmark = requires_db

ТОЧКА = "Белград-1"


@pytest.fixture
def admin_env(db_env: str, monkeypatch: pytest.MonkeyPatch) -> str:
    return set_retraction_env(db_env, monkeypatch)


def _проверка(chat_id: int) -> str:
    start_inspection(chat_id, unit=ТОЧКА, kind="planned", report_lang="ru", tenant="default")
    add_finding(chat_id, code="CLN05", level="D1", zone="hot_kitchen", text="нагар на печи")
    return push_inspection(chat_id)


def _статус(dsn: str, ident: str) -> tuple[Any, ...]:
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            "select status, accepted_at, accepted_by from inspections where id = %s", (ident,)
        ).fetchone()
    assert row is not None
    return tuple(row)


def test_слив_кладёт_проверку_на_приёмку(domain_env: Path, db_env: str) -> None:
    # Act
    ident = _проверка(901)

    # Assert
    статус, когда, кто = _статус(db_env, ident)
    assert (статус, когда, кто) == ("draft", None, None)


def test_ждущая_приёмки_не_входит_в_историю(domain_env: Path, db_env: str) -> None:
    # Arrange
    ident = _проверка(902)

    # Act
    история = list_inspections(tenant="default")
    очередь = list_inspections(tenant="default", on_review=True)

    # Assert — в очереди есть, в истории, находках точки и обзоре нет.
    assert [r.id for r in история] == []
    assert [r.id for r in очередь] == [ident]
    assert очередь[0].on_review is True
    assert get_inspection(ident, tenant="default") is None
    assert get_inspection(ident, tenant="default", include_on_review=True) is not None
    assert findings_by_unit(tenant="default", unit=ТОЧКА) == []
    assert class_counts(tenant="default") == {}


def test_подтверждение_переводит_в_историю_с_подписью(
    domain_env: Path, admin_env: str, db_env: str
) -> None:
    # Arrange
    ident = _проверка(903)

    # Act
    accept_inspection(ident, tenant="default", actor="garva")

    # Assert
    статус, когда, кто = _статус(db_env, ident)
    assert статус == "finalized" and когда is not None and кто == "garva"
    [строка] = list_inspections(tenant="default")
    assert (строка.id, строка.on_review, строка.accepted_by) == (ident, False, "garva")
    assert list_inspections(tenant="default", on_review=True) == []


def test_второй_раз_не_подтверждается(domain_env: Path, admin_env: str) -> None:
    # Arrange
    ident = _проверка(904)
    accept_inspection(ident, tenant="default", actor="garva")

    # Act / Assert
    with pytest.raises(AcceptError, match="уже принята"):
        accept_inspection(ident, tenant="default", actor="garva")


def test_без_подписи_не_подтверждается(domain_env: Path, admin_env: str) -> None:
    ident = _проверка(905)
    with pytest.raises(AcceptError, match="подтверждающий"):
        accept_inspection(ident, tenant="default", actor="  ")


def test_роль_приложения_подтвердить_не_может(domain_env: Path, db_env: str) -> None:
    """Бот ходит под ролью приложения; этап приёмки не держится на его памяти."""
    # Arrange
    ident = _проверка(906)

    # Act / Assert
    with (
        psycopg.connect(db_env) as conn,
        pytest.raises(psycopg.errors.InsufficientPrivilege, match="администратор истории"),
    ):
        conn.execute(
            "update inspections set status = 'finalized', accepted_at = now(), "
            "accepted_by = 'bot' where id = %s",
            (ident,),
        )
    assert _статус(db_env, ident)[0] == "draft"


def test_принятую_нельзя_вернуть_на_приёмку_и_переподписать(
    domain_env: Path, admin_env: str, db_env: str
) -> None:
    # Arrange
    ident = _проверка(907)
    accept_inspection(ident, tenant="default", actor="garva")

    # Act / Assert — ни обратного хода, ни подмены подписи даже администратору.
    for sql in (
        "update inspections set status = 'draft', accepted_at = null, accepted_by = null "
        "where id = %s",
        "update inspections set accepted_by = 'someone' where id = %s",
    ):
        with (
            psycopg.connect(admin_role_dsn(db_env)) as conn,
            pytest.raises(psycopg.errors.CheckViolation),
        ):
            conn.execute(sql, (ident,))
    assert _статус(db_env, ident)[2] == "garva"


def test_подтверждение_без_отметки_не_проходит(domain_env: Path, db_env: str) -> None:
    """Печать без «кто и когда» — принятая никем; база её не пропускает."""
    ident = _проверка(908)
    with (
        psycopg.connect(admin_role_dsn(db_env)) as conn,
        pytest.raises(psycopg.errors.CheckViolation),
    ):
        conn.execute("update inspections set status = 'finalized' where id = %s", (ident,))
