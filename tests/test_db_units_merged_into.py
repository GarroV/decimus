"""D538 в живой базе: снятая точка (`units.merged_into`, миграция 0078) — скрыта, но ведёт на живую.

Правило проверено без базы (`test_domain_unit_resolve.py`, `test_unit_names_one_rule.py`);
здесь — что делают SQL и сторож схемы.
"""

from __future__ import annotations

import pytest
from conftest import requires_db
from db_harness import завести_пространства

psycopg = pytest.importorskip("psycopg")

from src.db import directory  # noqa: E402
from src.db.directory import create_unit, list_units, resolve_unit, upsert_unit  # noqa: E402
from src.db.errors import UnitExistsError  # noqa: E402
from src.db.reach import Reach  # noqa: E402

pytestmark = requires_db

УК = "HQ"
ВСЕ = Reach("HQ", None, None)


@pytest.fixture(autouse=True)
def _пространства(request: pytest.FixtureRequest) -> None:
    if "db_env" in request.fixturenames:
        завести_пространства(request.getfixturevalue("pg_dsn"), УК)


def _пара(dsn: str) -> tuple[str, str]:
    """Латинская точка и её снятый кириллический дубль.

    Дубль вставляется строкой, а не `upsert_unit`: с D538 заведение под кириллицей находит
    латинскую точку и дубля не рождает — он остаётся только от времён до правила.
    """
    латинская = upsert_unit("Tbilisi-1", country="GE", city="tbilisi", tenant=УК)
    with psycopg.connect(dsn) as conn:
        дубль = str(
            conn.execute(
                "insert into units (tenant_code, name, name_normalized) "
                "values ('HQ', 'Тбилиси-1', 'тбилиси-1') returning id"
            ).fetchone()[0]  # type: ignore[index]
        )
        conn.execute("update units set merged_into = %s where id = %s", (латинская, дубль))
        conn.execute(
            "insert into unit_aliases (tenant_code, alias_normalized, unit_id, alias) "
            "values ('HQ', 'тбилиси-1', %s, 'Тбилиси-1') on conflict do nothing",
            (латинская,),
        )
        conn.commit()
    return латинская, дубль


def test_снятая_точка_не_в_списках_а_её_имя_и_id_ведут_на_живую(db_env: str) -> None:
    латинская, дубль = _пара(db_env)

    assert [u.name for u in list_units(reach=ВСЕ)] == ["Tbilisi-1"]
    assert resolve_unit("Тбилиси -1", tenant=УК).id == латинская  # type: ignore[union-attr]
    assert directory.redirect_target(дубль) == латинская
    assert directory.redirect_target(латинская) is None


def test_заведение_под_кириллицей_отказ_с_латинской_точкой(db_env: str) -> None:
    латинская, _ = _пара(db_env)

    with pytest.raises(UnitExistsError) as отказ:
        create_unit("Тбилиси-1", country="GE", tenant=УК)

    assert отказ.value.unit_id == латинская


def test_upsert_под_кириллицей_обновляет_латинскую_а_не_заводит_вторую(db_env: str) -> None:
    латинская, _ = _пара(db_env)

    assert upsert_unit("тбилиси 1", city="tbilisi", tenant=УК) == латинская


def test_сторож_не_даёт_снять_точку_с_проверками_и_цепочки(db_env: str) -> None:
    латинская, дубль = _пара(db_env)
    третья = upsert_unit("Tbilisi-3", country="GE", tenant=УК)

    with psycopg.connect(db_env) as conn, pytest.raises(psycopg.Error):
        # Цель сама снята — цепочки запрещены.
        conn.execute("update units set merged_into = %s where id = %s", (дубль, третья))
    with psycopg.connect(db_env) as conn, pytest.raises(psycopg.Error):
        # В точку уже влиты другие — её саму снять нельзя.
        conn.execute("update units set merged_into = %s where id = %s", (третья, латинская))
