"""Запросы к `maps.ratings` (миграция 0055): новые отвечают так же, как прежние.

Прежние — `distinct on` по всей таблице — переписаны на «пара за парой» ради
скорости (130–170 мс → 4–6 мс на 107 тыс. строк). Скорость ответ менять не
вправе: здесь оба текста идут на одних данных и сравниваются строка в строку.
Прежние тексты лежат в тесте копией — это эталон, который не правится вслед
за кодом.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from conftest import requires_db

psycopg = pytest.importorskip("psycopg")

from src.db import maps_store  # noqa: E402

pytestmark = requires_db

_OLD_LATEST_SQL = """
    select distinct on (r.company_uuid, r.provider_id)
           c.country_code, r.provider_id, r.avg_rating, r.ratings_count, r.on_date
    from maps.ratings r
    join maps.companies c on c.uuid = r.company_uuid
    where c.country_code = any(%s) and (%s::date is null or r.on_date <= %s::date)
      and c.excluded_reason is null
    order by r.company_uuid, r.provider_id, r.on_date desc
"""

_OLD_UNIT_SCORES_SQL = """
    select distinct on (c.dodo_id) c.dodo_id, r.avg_rating, r.ratings_count
    from maps.ratings r
    join maps.companies c on c.uuid = r.company_uuid
    where c.dodo_id is not null and r.provider_id = %s and r.on_date <= %s
      and c.excluded_reason is null
      and r.ratings_count > 0
    order by c.dodo_id, r.on_date desc
"""

TODAY = date(2026, 10, 12)
UNIT_X = "a" * 32
UNIT_Y = "b" * 32
UNIT_Z = "c" * 32


def _uuid() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def seeded(db_env: str) -> str:
    """Филиалы и снимки: две записи одной пиццерии, снятый филиал, нулевые отзывы."""
    with psycopg.connect(db_env) as conn:
        companies = {
            "a1": ("AA", UNIT_X, None),
            "a2": ("AA", UNIT_X, None),  # второй филиал той же пиццерии
            "a3": ("AA", None, None),  # без связи с пиццерией
            "b1": ("BB", UNIT_Y, None),
            "b2": ("BB", UNIT_Z, "закрыт"),  # снят
            "c1": ("CC", UNIT_Z, None),
        }
        ids = {name: _uuid() for name in companies}
        for name, (country, dodo, excluded) in companies.items():
            conn.execute(
                "insert into maps.companies (uuid, name, country_code, dodo_id, excluded_reason) "
                "values (%s, %s, %s, %s, %s)",
                (ids[name], name, country, dodo, excluded),
            )
        # (филиал, карта) → [(дней назад, оценка, отзывов)]
        history = {
            ("a1", 1): [(0, "4.50", 100), (10, "4.00", 90), (40, "3.50", 80)],
            ("a1", 2): [(5, "4.10", 50)],
            ("a2", 1): [(3, "3.90", 70), (30, "3.00", 60)],  # свежее у a2, чем у a1 на дату -2
            ("a3", 1): [(1, "5.00", 10)],
            ("b1", 1): [(0, "4.20", 0), (7, "4.00", 33)],  # последняя без отзывов
            ("b1", 3): [(2, "4.80", 20)],
            ("b2", 1): [(0, "1.00", 999)],
            ("c1", 1): [(60, "4.40", 12)],
        }
        for (name, provider), points in history.items():
            for back, avg, count in points:
                conn.execute(
                    "insert into maps.ratings (company_uuid, provider_id, on_date, avg_rating, "
                    "ratings_count) values (%s, %s, %s, %s, %s)",
                    (ids[name], provider, TODAY - timedelta(days=back), avg, count),
                )
    return db_env


@pytest.mark.parametrize("back", [None, 0, 3, 8, 35, 70])
@pytest.mark.parametrize("countries", [["AA", "BB", "CC"], ["AA"], ["BB", "CC"], ["ZZ"]])
def test_последняя_оценка_совпадает_с_прежним_запросом(
    seeded: str, countries: list[str], back: int | None
) -> None:
    until = None if back is None else TODAY - timedelta(days=back)
    with psycopg.connect(seeded) as conn:
        эталон = conn.execute(_OLD_LATEST_SQL, (countries, until, until)).fetchall()

    новое = maps_store.latest(countries, until=until)

    ожидаемое = tuple(
        maps_store.LatestRating(str(r[0]), int(r[1]), float(r[2]), int(r[3]), r[4]) for r in эталон
    )
    assert новое == ожидаемое


@pytest.mark.parametrize("provider", [1, 2, 3, 4])
@pytest.mark.parametrize("back", [0, 2, 8, 35, 70])
def test_оценка_пиццерии_совпадает_с_прежним_запросом(
    seeded: str, provider: int, back: int
) -> None:
    until = TODAY - timedelta(days=back)
    with psycopg.connect(seeded) as conn:
        эталон = conn.execute(_OLD_UNIT_SCORES_SQL, (provider, until)).fetchall()

    новое = maps_store.unit_scores(provider, until=until)

    assert новое == {str(r[0]): (float(r[1]), int(r[2])) for r in эталон}


def test_данные_теста_отличают_запросы_от_пустого_ответа(seeded: str) -> None:
    """Страховка от пустой проверки: на этих данных ответы не пусты и не вырождены."""
    последние = maps_store.latest(["AA", "BB", "CC"], until=None)
    оценки = maps_store.unit_scores(1, until=TODAY)

    assert len(последние) == 7  # a1×2 карты, a2, a3, b1×2 карты, c1 — снятый b2 не в счёт
    assert оценки[UNIT_X] == (4.5, 100)  # самая свежая среди двух филиалов пиццерии
    assert оценки[UNIT_Y] == (4.0, 33)  # свежая запись без отзывов пропущена
    assert UNIT_Z in оценки and оценки[UNIT_Z] == (4.4, 12)  # снятый b2 (999) не учтён

    с_датой = maps_store.unit_scores_dated(1, until=TODAY)
    assert {k: (v[0], v[1]) for k, v in с_датой.items()} == оценки
    assert all(isinstance(v[2], date) and v[2] <= TODAY for v in с_датой.values())


def test_индекс_под_выборки_на_месте(seeded: str) -> None:
    with psycopg.connect(seeded) as conn:
        строка = conn.execute(
            "select indexdef from pg_indexes where schemaname = 'maps' "
            "and indexname = 'ratings_provider_company_date_idx'"
        ).fetchone()

    assert строка is not None
    assert "provider_id, company_uuid, on_date DESC" in строка[0]
