"""D199: этап приёмки — слитая проверка ждёт подтверждения человеком.

Проверяется то, что держит БАЗА и запрос, а не вызов: слив кладёт проверку на
приёмку и запечатать её не может, в историю сети ждущая не попадает,
подтверждает только администратор истории и только своё пространство (D283),
а обратного хода нет.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from conftest import requires_db
from db_harness import (
    admin_role_dsn,
    set_retraction_env,
    привязать_страну,
    слить_проверку,
    точка_справочника,
)

psycopg = pytest.importorskip("psycopg")

from src.db.accept import accept_inspection  # noqa: E402
from src.db.errors import AcceptError  # noqa: E402
from src.db.queries import (  # noqa: E402
    class_counts,
    findings_by_unit,
    get_inspection,
    list_inspections,
)
from src.db.reach import own_reach, reach_of  # noqa: E402

pytestmark = requires_db

ТОЧКА = "Batumi-1"
УК = own_reach("HQ")


@pytest.fixture
def admin_env(db_env: str, monkeypatch: pytest.MonkeyPatch) -> str:
    return set_retraction_env(db_env, monkeypatch)


@pytest.fixture
def сеть(pg_dsn: str, db_env: str, domain_env: Path) -> None:
    """Справочник УК: Batumi-1 в Грузии; пространство GE привязано к Грузии."""
    точка_справочника(ТОЧКА, country="GE", city="Batumi")
    привязать_страну(pg_dsn, tenant="GE", country="GE")


def _ждущая(tenant: str = "HQ") -> str:
    return слить_проверку(unit=ТОЧКА, tenant=tenant, accept=False)


def _статус(dsn: str, ident: str) -> tuple[Any, ...]:
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            "select status, accepted_at, accepted_by from inspections where id = %s", (ident,)
        ).fetchone()
    assert row is not None
    return tuple(row)


def test_слив_кладёт_проверку_на_приёмку(сеть: None, db_env: str) -> None:
    # Act
    ident = _ждущая()

    # Assert
    assert _статус(db_env, ident) == ("draft", None, None)


def test_ждущая_приёмки_не_входит_в_историю(сеть: None) -> None:
    # Arrange
    ident = _ждущая()

    # Act
    история = list_inspections(reach=УК)
    очередь = list_inspections(reach=УК, on_review=True)

    # Assert — в очереди есть, в истории, находках точки и обзоре нет.
    assert [r.id for r in история] == []
    assert [r.id for r in очередь] == [ident]
    assert очередь[0].on_review is True
    assert get_inspection(ident, reach=УК) is None
    assert get_inspection(ident, reach=УК, include_on_review=True) is not None
    assert findings_by_unit(reach=УК, unit=ТОЧКА) == []
    assert class_counts(reach=УК) == {}


def test_очередь_идёт_по_охвату_читающего(сеть: None) -> None:
    """УК видит ждущую партнёра (на чтение, D283); партнёр — ждущие своей страны."""
    # Arrange
    своя_уК = _ждущая("HQ")
    партнёра = _ждущая("GE")

    # Act
    у_уК = {r.id for r in list_inspections(reach=reach_of("HQ"), on_review=True)}
    у_партнёра = {r.id for r in list_inspections(reach=reach_of("GE"), on_review=True)}
    только_свои = {r.id for r in list_inspections(reach=own_reach("GE"), on_review=True)}

    # Assert
    assert у_уК == {своя_уК, партнёра}
    assert у_партнёра == {своя_уК, партнёра}
    assert только_свои == {партнёра}


def test_подтверждение_переводит_в_историю_с_подписью(
    сеть: None, admin_env: str, db_env: str
) -> None:
    # Arrange
    ident = _ждущая()

    # Act
    accept_inspection(ident, tenant="HQ", actor="garva")

    # Assert
    статус, когда, кто = _статус(db_env, ident)
    assert статус == "finalized" and когда is not None and кто == "garva"
    [строка] = list_inspections(reach=УК)
    assert (строка.id, строка.on_review, строка.accepted_by) == (ident, False, "garva")
    assert list_inspections(reach=УК, on_review=True) == []


@pytest.mark.parametrize(("владелец", "подтверждает"), [("GE", "HQ"), ("HQ", "GE")])
def test_чужое_пространство_не_подтверждает(
    сеть: None, admin_env: str, db_env: str, владелец: str, подтверждает: str
) -> None:
    """Роль администратора истории одна на всех — своё пространство держит запрос."""
    # Arrange
    ident = _ждущая(владелец)

    # Act / Assert
    with pytest.raises(AcceptError, match="нет"):
        accept_inspection(ident, tenant=подтверждает, actor="garva")
    assert _статус(db_env, ident)[0] == "draft"


def test_второй_раз_не_подтверждается(сеть: None, admin_env: str) -> None:
    # Arrange
    ident = _ждущая()
    accept_inspection(ident, tenant="HQ", actor="garva")

    # Act / Assert
    with pytest.raises(AcceptError, match="уже принята"):
        accept_inspection(ident, tenant="HQ", actor="garva")


def test_без_подписи_не_подтверждается(сеть: None, admin_env: str) -> None:
    ident = _ждущая()
    with pytest.raises(AcceptError, match="подтверждающий"):
        accept_inspection(ident, tenant="HQ", actor="  ")


def test_роль_приложения_подтвердить_не_может(сеть: None, db_env: str) -> None:
    """Бот ходит под ролью приложения; этап приёмки не держится на его памяти."""
    # Arrange
    ident = _ждущая()

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
    сеть: None, admin_env: str, db_env: str
) -> None:
    # Arrange
    ident = _ждущая()
    accept_inspection(ident, tenant="HQ", actor="garva")

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


def test_подтверждение_без_отметки_не_проходит(сеть: None, db_env: str) -> None:
    """Печать без «кто и когда» — принятая никем; база её не пропускает."""
    ident = _ждущая()
    with (
        psycopg.connect(admin_role_dsn(db_env)) as conn,
        pytest.raises(psycopg.errors.CheckViolation),
    ):
        conn.execute("update inspections set status = 'finalized' where id = %s", (ident,))
