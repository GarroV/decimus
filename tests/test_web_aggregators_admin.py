"""Охват агрегаторов: счётчики, реальные пробелы, права и пакетное чтение."""

from datetime import UTC, date, datetime, timedelta

import pytest
from web_harness import войти, подменить_двери, собрать

from src.db import agg_store, ratings_read
from src.db.errors import RatingsError
from src.web import aggregators_admin as screen

TODAY = date(2026, 11, 2)
NOW = datetime(2026, 11, 2, tzinfo=UTC)
COUNTRIES = (
    ratings_read.CountryRow("BG", "Болгария", "Bulgaria", None, True),
    ratings_read.CountryRow("RS", "Сербия", "Serbia", None, True),
)


def unit(key: str, working: bool = True) -> agg_store.UnitRow:
    return agg_store.UnitRow(key, "BG", key, 1, 1, working, None, TODAY)


def linked(key: str, age: int | None) -> agg_store.CoverageRow:
    return agg_store.CoverageRow(
        "wolt",
        key,
        "BG",
        9 if age is not None else None,
        10 if age is not None else None,
        TODAY - timedelta(days=age) if age is not None else None,
    )


def load(outcome: str = "ok", age: int = 0) -> agg_store.LoadState:
    return agg_store.LoadState(
        "wolt",
        NOW,
        outcome,
        4,
        "test failure" if outcome != "ok" else None,
        NOW - timedelta(days=age),
    )


def build(*, loads: tuple[agg_store.LoadState, ...] = ()) -> tuple[screen.Country, ...]:
    return screen.build(
        COUNTRIES,
        [unit("fresh"), unit("stale"), unit("unrated"), unit("missing"), unit("closed", False)],
        [linked("fresh", 7), linked("stale", 8), linked("unrated", None)],
        {"wolt": {"BG"}},
        loads,
        [agg_store.UnmatchedCount("BG", "wolt", 2, 3)],
        TODAY,
    )


def test_counts_partition_working_units_and_separate_excluded() -> None:
    bg, rs = build(loads=(load(),))
    (p,) = bg.platforms
    assert (bg.working, p.expected, p.linked, p.scored, p.fresh, p.stale, p.unrated, p.missing) == (
        4,
        4,
        3,
        2,
        1,
        1,
        1,
        1,
    )
    assert (p.unmatched, p.excluded) == (2, 3)
    assert p.latest == TODAY - timedelta(days=7)
    assert p.gaps == (
        ("stale", "stale", TODAY - timedelta(days=8)),
        ("unrated", "unrated", None),
        ("missing", "missing", None),
    )
    assert bg.tone == "yellow"
    assert rs.tone == "grey" and not rs.platforms and rs.working == 0


@pytest.mark.parametrize(
    ("states", "tone"),
    [((load(),), "green"), ((load("failed"),), "red"), ((load(age=8),), "yellow"), ((), "yellow")],
)
def test_green_requires_complete_fresh_scores_and_successful_recent_collector(
    states: tuple[agg_store.LoadState, ...], tone: str
) -> None:
    (row,) = screen.build(
        COUNTRIES[:1], [unit("a")], [linked("a", 0)], {"wolt": {"BG"}}, states, (), TODAY
    )
    assert row.tone == tone


def doors(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    calls: dict[str, int] = {}

    def counted(key: str, value: object):
        def read(*args: object):
            calls[key] = calls.get(key, 0) + 1
            return value

        return read

    monkeypatch.setattr(ratings_read, "countries", counted("countries", COUNTRIES))
    monkeypatch.setattr(agg_store, "units", counted("units", [unit("missing")]))
    monkeypatch.setattr(agg_store, "coverage", counted("coverage", ()))
    monkeypatch.setattr(agg_store, "load_states", counted("loads", (load("failed"),)))
    monkeypatch.setattr(
        agg_store,
        "unmatched_counts",
        counted("unmatched", [agg_store.UnmatchedCount("BG", "wolt", 2, 1)]),
    )
    monkeypatch.setattr(
        screen.ratings_platforms, "agg_countries", counted("expected", {"wolt": {"BG"}})
    )
    return calls


def page(monkeypatch: pytest.MonkeyPatch, tenant: str, role: str, url: str):
    подменить_двери(monkeypatch, tenant=tenant, role=role)
    with собрать(tenant="HQ").test_client() as client:
        assert войти(client).status_code == 302
        return client.get(url)


@pytest.mark.parametrize("role", ["superadmin", "admin", "control"])
def test_hq_managers_see_actual_gaps_and_global_status(
    monkeypatch: pytest.MonkeyPatch, role: str
) -> None:
    calls = doors(monkeypatch)
    response = page(monkeypatch, "HQ", role, "/administration?tab=aggregators&country=BG")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert html.index('<header class="page-heading">') < html.index('class="sadmin"')
    assert "missing — нет привязки" in html
    assert "подробности в закрытом журнале" in html and "всему сборщику" in html
    assert "/ratings/agg?group=country&amp;value=BG" in html
    assert "/administration?tab=ratings&amp;block=aggregators" in html
    assert "Настройки площадок и привязки" in html
    assert "shealth__dot--red" in html
    assert all(n == 1 for n in calls.values()), calls
    assert response.headers["Cache-Control"] == "private, no-store"


@pytest.mark.parametrize(
    ("tenant", "role"), [("RS", "admin"), ("RS", "auditor"), ("HQ", "developer")]
)
def test_other_roles_refused_before_data_read(
    monkeypatch: pytest.MonkeyPatch, tenant: str, role: str
) -> None:
    calls = doors(monkeypatch)
    response = page(monkeypatch, tenant, role, "/administration?tab=aggregators&country=BG")
    assert response.status_code == 404
    assert not calls


def test_db_failure_is_not_empty_or_green(monkeypatch: pytest.MonkeyPatch) -> None:
    doors(monkeypatch)

    def fail():
        raise RatingsError("test")

    monkeypatch.setattr(agg_store, "coverage", fail)
    response = page(monkeypatch, "HQ", "admin", "/administration?tab=aggregators")
    html = response.get_data(as_text=True)
    assert "Данные охвата не прочитались" in html
    assert "shealth__dot--green" not in html


def test_country_without_expected_platform_is_not_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    doors(monkeypatch)
    response = page(monkeypatch, "HQ", "control", "/administration?tab=aggregators&country=RS")
    html = response.get_data(as_text=True)
    assert "нет ожидаемых площадок" in html and "нет работающих пиццерий" in html


def test_unknown_country_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    doors(monkeypatch)
    assert (
        page(monkeypatch, "HQ", "admin", "/administration?tab=aggregators&country=XX").status_code
        == 404
    )


def test_partial_success_is_yellow_and_raw_errors_are_not_exposed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    partial = agg_store.LoadState(
        "wolt",
        NOW,
        "ok",
        1,
        (
            "HTTP 429 https://example.invalid/?token=private "
            "owner@example.invalid Authorization: Bearer private"
        ),
        NOW,
    )
    (row,) = screen.build(
        COUNTRIES[:1], [unit("a")], [linked("a", 0)], {"wolt": {"BG"}}, (partial,), (), TODAY
    )
    assert row.tone == "yellow"
    assert row.platforms[0].error_code == "HTTP 429"
    doors(monkeypatch)
    monkeypatch.setattr(agg_store, "load_states", lambda: (partial,))
    html = page(
        monkeypatch, "HQ", "control", "/administration?tab=aggregators&country=BG"
    ).get_data(as_text=True)
    assert "Собрано частично: HTTP 429" in html
    assert "example.invalid" not in html and "Bearer private" not in html
    assert "?token=" not in html
