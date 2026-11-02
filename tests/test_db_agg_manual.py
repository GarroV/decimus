"""Ручные решения по охвату агрегаторов в базе (миграция 0118, D700): отметка «нет на
площадке», закреплённая привязка, непривязанные точки и отсев тестовых пиццерий.

Идут ролью приложения — так их пишут веб и бот: права из миграции проверяются тем же.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from conftest import requires_db

pytest.importorskip("psycopg")

from src.db import agg_store
from src.db.agg_store import PointRow

pytestmark = requires_db

ADANA, MERSIN, TEST = "a" * 32, "b" * 32, "c" * 32
DAY = date(2026, 11, 2)


def _point(key: str, dodo_id: str | None = None, lat: float | None = 37.0) -> PointRow:
    return PointRow(
        "trendyol_go", key, "TR", f"Dodo {key}", f"https://t/{key}", lat, 35.3,
        dodo_id, "Adana-3" if dodo_id else None, 10 if dodo_id else None, {},
    )  # fmt: skip


def _unit(key: str, name: str) -> SimpleNamespace:
    return SimpleNamespace(dodo_id=key, country="TR", name=name, lat=37.0, lng=35.3, working=True)


def test_отметка_ставится_повторно_без_ошибки_и_снимается(db_env: str) -> None:
    agg_store.mark_absent("glovo", ADANA, by="anna")
    agg_store.mark_absent("glovo", ADANA, by="boris")
    agg_store.mark_absent("chowdeck", ADANA, by="anna")

    assert agg_store.unit_absent() == {("glovo", ADANA), ("chowdeck", ADANA)}
    agg_store.unmark_absent("glovo", ADANA)
    agg_store.unmark_absent("glovo", ADANA)
    assert agg_store.unit_absent() == {("chowdeck", ADANA)}


def test_закрепление_пишет_привязку_сразу_и_снимается_вместе_с_ней(db_env: str) -> None:
    agg_store.save([_point("374489")], [])
    agg_store.mark_absent("trendyol_go", ADANA, by="anna")

    assert agg_store.pin_link("trendyol_go", "374489", ADANA, "Adana-3", 1500, by="anna")

    assert agg_store.pins("trendyol_go") == {"374489": ADANA}
    (row,) = agg_store.coverage()
    assert (row.aggregator, row.dodo_id) == ("trendyol_go", ADANA)
    assert agg_store.unit_absent() == frozenset()  # привязка сильнее отметки
    assert agg_store.open_points() == ()

    agg_store.unpin_link("trendyol_go", "374489")

    assert agg_store.pins("trendyol_go") == {} and agg_store.coverage() == ()
    assert [p.point_key for p in agg_store.open_points()] == ["374489"]


def test_закрепление_заменяет_прежнее_и_отвязывает_чужую_точку_той_же_пиццерии(
    db_env: str,
) -> None:
    agg_store.save([_point("old", ADANA), _point("new"), _point("other", MERSIN)], [])
    assert agg_store.pin_link("trendyol_go", "old", ADANA, "Adana-3", 5, by="anna")

    assert agg_store.pin_link("trendyol_go", "new", ADANA, "Adana-3", 900, by="boris")

    assert agg_store.pins("trendyol_go") == {"new": ADANA}
    assert {r.dodo_id for r in agg_store.coverage()} == {ADANA, MERSIN}
    assert [p.point_key for p in agg_store.open_points()] == ["old"]


def test_закрепить_несуществующую_точку_нельзя(db_env: str) -> None:
    assert not agg_store.pin_link("trendyol_go", "ghost", ADANA, "Adana-3", 5, by="anna")
    assert agg_store.point_links() == ()


def test_непривязанные_точки_без_исключённых_и_без_координат(db_env: str) -> None:
    agg_store.save([_point("free"), _point("linked", ADANA), _point("nocoords", lat=None)], [])
    agg_store.save([_point("banned")], [])
    from src.db.config import check_environment
    from src.db.pool import connection

    with connection(check_environment().dsn) as conn, conn.transaction():
        conn.execute(
            "update agg.points set excluded_reason = 'не пиццерия' where point_key = 'banned'"
        )

    assert [p.point_key for p in agg_store.open_points()] == ["free"]


def test_тестовые_пиццерии_реестр_не_отдаёт(db_env: str) -> None:
    agg_store.save_units(
        [_unit(ADANA, "Adana-3"), _unit(TEST, "TEST-1"), _unit(MERSIN, "test-22")], DAY
    )

    assert [u.name for u in agg_store.units()] == ["Adana-3"]
    assert [u.name for u in agg_store.units(("TR",))] == ["Adana-3"]
