"""Реестр «Проверки»: счёт по месту совпадает со списком, записи ждущих приёмки — по классам.

Ядро — числа, читаемые как факт: счётчик страны слева и «N» в «100 из N» берутся тем же
отбором, что и список «Принятые», иначе они молча расходятся (на демо 28 против 26).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import requires_db
from db_harness import привязать_страну, слить_проверку, точка_справочника

from src.db.queries import class_counts, count_by_place, list_inspections, review_class_counts
from src.db.reach import own_reach
from src.web.inspections import load_registry

pytestmark = requires_db

УК = own_reach("HQ")
ТОЧКИ = (
    ("Batumi-1", "GE", "batumi"),
    ("Tbilisi-1", "GE", "tbilisi"),
    ("Antalya-1", "TR", "antalya"),
)


@pytest.fixture
def сеть(pg_dsn: str, db_env: str, domain_env: Path) -> dict[str, str]:
    """Три точки в двух странах; принятые в сентябре и октябре, одна ждёт приёмки."""
    for название, страна, город in ТОЧКИ:
        точка_справочника(название, country=страна, city=город)
    привязать_страну(pg_dsn, tenant="GE", country="GE")
    return {
        "bat_sep": слить_проверку(unit="Batumi-1", tenant="HQ", date="2026-09-10"),
        "tbi_sep": слить_проверку(unit="Tbilisi-1", tenant="HQ", date="2026-09-20"),
        "tbi_oct": слить_проверку(unit="Tbilisi-1", tenant="HQ", date="2026-10-05"),
        "ant_oct": слить_проверку(unit="Antalya-1", tenant="HQ", date="2026-10-07"),
        "ждёт": слить_проверку(unit="Antalya-1", tenant="HQ", date="2026-10-08", accept=False),
    }


ПЕРИОДЫ = (
    {},
    {"date_from": "2026-09-01", "date_to": "2026-09-30"},
    {"date_from": "2026-10-01", "date_to": "2026-10-31"},
    {"date_from": "2026-10-06"},
)
ОТБОРЫ = ({}, {"q": "tbilisi"}, {"q": "ANTALYA"}, {"kind": "planned"}, {"kind": "repeat"})


def _дата(значение: str | None):  # type: ignore[no-untyped-def]
    from datetime import date

    return date.fromisoformat(значение) if значение else None


@pytest.mark.parametrize("период", ПЕРИОДЫ)
@pytest.mark.parametrize("отбор", ОТБОРЫ)
def test_счёт_по_месту_равен_списку_принятых(
    сеть: dict[str, str], период: dict[str, str], отбор: dict[str, str]
) -> None:
    # Arrange
    окно = {к: _дата(з) for к, з in период.items()}

    # Act
    счёт = count_by_place(reach=УК, **окно, **отбор)
    список = list_inspections(reach=УК, limit=100, **окно, **отбор)

    # Assert — и всего, и по каждой стране; ждущая приёмки ни туда, ни туда не входит
    assert sum(счёт.values()) == len(список)
    страны = {c for c, _ in счёт}
    for страна in страны:
        assert sum(n for (c, _), n in счёт.items() if c == страна) == len(
            list_inspections(reach=УК, limit=100, country=страна, **окно, **отбор)
        )


def test_реестр_отдаёт_настоящее_число_когда_список_обрезан(сеть: dict[str, str]) -> None:
    # Act — предел 2 при четырёх принятых; отбор «Тбилиси» читается в базе, а не по странице
    реестр = load_registry(reach=УК, limit=2, q="tbilisi")

    # Assert
    assert len(реестр.rows) == 2
    assert реестр.place_counts is not None
    assert sum(n for _, _, n in реестр.place_counts) == 2
    реестр = load_registry(reach=УК, limit=2, country="TR")
    assert реестр.accepted is not None
    assert [r.unit_name for r in реестр.accepted] == ["Antalya-1"]
    assert sum(n for c, _, n in реестр.place_counts or () if c == "TR") == 1


def test_записи_ждущих_приёмки_читаются_по_классам_одним_запросом(сеть: dict[str, str]) -> None:
    # Act
    ждущие = review_class_counts(reach=УК)
    принятые = class_counts(reach=УК)

    # Assert — очередь и история не смешиваются
    assert ждущие == {сеть["ждёт"]: {"D1": 1}}
    assert сеть["ждёт"] not in принятые
    assert load_registry(reach=УК, limit=10).review_classes == ждущие
