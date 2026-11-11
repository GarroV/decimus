"""D746: readable source histories and calm missing map data, without a server."""

# ruff: noqa: F811
from __future__ import annotations

import math
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask, render_template
from test_web_proofread_browser import browser_page  # noqa: F401

from src.db.agg_store import UnitRow
from src.ratings.coverage import ABSENT, MISSING, SCORE, Cell, Platform, Row
from src.ratings.maps import CountryMaps, MapScore
from src.ratings.risk_sources import RiskRow, Source
from src.web.ratings_trends import build
from src.web.texts import t

ROOT = Path(__file__).resolve().parents[1]


def test_missing_points_do_not_become_zero_or_connect_unobserved_changes():
    view = build((90.0, None, 80.0, 70.0, math.nan))
    assert [point.value for point in view.points] == [90.0, 80.0, 70.0]
    assert [point.delta for point in view.scores] == [None, None, None, -10.0, None]
    assert len(view.paths) == 1
    assert view.paths[0].startswith(f"M {view.points[1].x:g}")
    assert len(view.paths[0].split("L")) == 2


def test_single_and_constant_histories_are_finite_without_fabricated_movements():
    single = build((4.2,))
    assert single.paths == () and len(single.points) == 1
    assert single.scores[0].delta is None and single.scores[0].arrow == ""
    same = build((76.0, 76.0, 76.0))
    assert len({point.y for point in same.points}) == 1
    assert all(math.isfinite(point.y) for point in same.points)
    assert [point.delta for point in same.scores] == [None, 0, 0]


def test_displayed_delta_and_direction_agree_after_rounding():
    view = build((80.0, 79.999, 79.0))
    assert [point.formatted for point in view.scores] == ["80.0", "80.0", "79.0"]
    assert view.scores[1].delta_text == "+0.0" and view.scores[1].arrow == "▲"
    assert view.scores[2].tone == "down" and view.scores[2].arrow == "▼"
    assert max(point.y for point in view.points) < view.height
    assert min(point.y for point in view.points) > 0


def component(name: str, lang: str = "en", *, risk_rows=None, map_rows=None) -> str:
    app = Flask(__name__, template_folder=str(ROOT / "src/web/templates"))
    unit = UnitRow("demo-unit", "AA", "Demo pizzeria", 0, 0, True, None, date(2026, 11, 1))
    values = {
        "t": lambda key, **kw: t(key, lang, **kw),
        "country_name": lambda code: {"AA": "Country A", "BB": "Country B"}[code],
        "country_topic_url": lambda code, topic: f"/ratings/country/{code}/{topic}",
        "unit_url": lambda code, kind: f"/original/{code}/{kind}",
        "unit_profile_url": lambda row: f"/units/{row.dodo_id}",
        "grouped": str,
        "delta_note": None,
        "map_names": ("Country A", "Country B"),
        "map_country_codes": ("AA", "BB"),
        "map_providers": (2, 1),
        "maps": (
            CountryMaps("AA", {2: MapScore(4.3, 31, 2, 0.1), 1: MapScore(None, 0, 0)}, None),
            CountryMaps("BB", {2: MapScore(4.4, 22, 1), 1: MapScore(4.5, 14, 1)}, None),
        ),
        "map_units": SimpleNamespace(
            platforms=(Platform("2", "map"), Platform("1", "map")),
            rows=map_rows
            if map_rows is not None
            else (Row(unit, False, {"2": Cell(SCORE, 4.3, 5), "1": Cell(ABSENT)}),),
        ),
        "risk": SimpleNamespace(
            rows=risk_rows
            if risk_rows is not None
            else (RiskRow("demo-unit", "Demo pizzeria", "AA", (Source("rs", (80, 76, 76)),)),)
        ),
        "risk_sources": {"rs": "Standards rating"},
        "trend": build,
    }
    with app.test_request_context("/"):
        return render_template("ratings/" + name, **values)


def styles(page):
    for name in (
        "dodo-ds.css",
        "decimus-domain.css",
        "decimus-web.css",
        "decimus-rt.css",
        "decimus-rt-trends.css",
    ):
        page.add_style_tag(path=str(ROOT / "src/web/static" / name))


@pytest.mark.parametrize("width", [390, 1280])
def test_maps_links_and_missing_yandex_remain_usable_at_phone_and_desktop(browser_page, width):
    page = browser_page
    page.set_viewport_size({"width": width, "height": 900})
    page.set_content(component("_s_maps.html"))
    styles(page)
    cards = page.locator(".rt-map-country")
    assert cards.count() == 2
    first = cards.first
    assert first.locator("h3 a").get_attribute("href") == "/ratings/country/AA/maps"
    assert first.locator("meter").count() == 1
    assert first.locator(".is-empty").inner_text() == "—"
    providers = cards.nth(1).locator(".rt-map-score")
    google, yandex = providers.nth(0).bounding_box(), providers.nth(1).bounding_box()
    assert google and yandex and google["y"] + google["height"] <= yandex["y"]
    colors = providers.evaluate_all(
        "nodes=>nodes.map(node=>getComputedStyle(node.querySelector('meter')).accentColor)"
    )
    assert colors[0] != colors[1]
    assert page.locator(".rt-map-cell meter").count() == 1
    assert (
        page.get_by_role("link", name="Demo pizzeria", exact=True).get_attribute("href")
        == "/units/demo-unit"
    )
    for card in cards.all():
        bounds = card.bounding_box()
        assert bounds and bounds["x"] >= 0 and bounds["x"] + bounds["width"] <= width


def test_risk_has_a_real_bright_graph_and_readable_values_not_only_arrows(browser_page):
    page = browser_page
    page.set_content(component("_s_risk.html"))
    styles(page)
    chart = page.get_by_role("img", name="Standards rating: 80.0, 76.0, 76.0")
    assert chart.locator("path").count() == 1
    assert chart.locator("circle").count() == 3
    assert page.locator(".rt-risk-source__values").inner_text().split() == [
        "80.0",
        "76.0",
        "▼",
        "76.0",
        "▲",
    ]
    assert chart.locator("path").evaluate("e=>parseFloat(getComputedStyle(e).strokeWidth)") >= 3
    assert (
        page.get_by_role("link", name="Country A", exact=True).get_attribute("href")
        == "/ratings/country/AA/risk"
    )


def test_risk_groups_count_pizzerias_once_and_keep_sources_in_their_own_columns(browser_page):
    page = browser_page
    page.set_content(
        component(
            "_s_risk.html",
            risk_rows=(
                RiskRow(
                    "demo-unit",
                    "Demo pizzeria",
                    "AA",
                    (
                        Source("rs", (80, 76, 76)),
                        Source("rko", (79, 78, 77)),
                        Source("wolt", (8.5, 8.4, 8.3, 8.2)),
                        Source("glovo", (88, 87, 88, 86)),
                    ),
                ),
                RiskRow("demo-second", "Other pizzeria", "AA", (Source("inspections", (80, 70)),)),
            ),
        )
    )
    styles(page)
    assert page.locator("[data-risk-count='total']").inner_text() == "2"
    for group in ("ratings", "aggregators", "inspections"):
        assert page.locator(f"[data-risk-count='{group}']").inner_text() == "1"
    assert page.locator(".rt-risk-group--ratings .rt-risk-source").count() == 2
    assert page.locator(".rt-risk-group--aggregators .rt-risk-source").count() == 2
    assert page.locator(".rt-risk-group--inspections .rt-risk-source").count() == 1
    assert page.locator(".rt-sparkline").count() == 5


def test_maps_filters_use_real_cells_and_keep_boundary_and_missing_states_distinct(browser_page):
    page = browser_page

    def row(code, google, yandex):
        unit = UnitRow(code, "AA", code, 0, 0, True, None, date(2026, 11, 1))
        return Row(unit, False, {"2": google, "1": yandex})

    rows = (
        row(
            "Low",
            Cell(SCORE, 3.99, 5, date(2026, 10, 1), True),
            Cell(SCORE, 4.5, 5, date(2026, 10, 1), True),
        ),
        row("Boundary", Cell(SCORE, 4.0, 5), Cell(ABSENT)),
        row("Missing", Cell(MISSING), Cell(ABSENT)),
        row("Absent", Cell(ABSENT), Cell(ABSENT)),
    )
    page.set_content(component("_s_maps.html", map_rows=rows))
    styles(page)
    page.add_script_tag(path=str(ROOT / "src/web/static/decimus-rt-map-filters.js"))
    low_meter = page.locator("[data-map-row]").first.locator("meter").first
    assert low_meter.get_attribute("min") == "4"
    assert low_meter.get_attribute("value") == "4"
    assert low_meter.get_attribute("aria-valuetext") == "3.99"
    for kind in ("low", "stale", "missing"):
        assert page.locator(f".rt-map-alert--{kind} h3 b").inner_text() == "1"
    assert page.locator("[data-map-row]").first.locator("td").last.inner_text() == "+0.51"
    assert page.locator("[data-map-row]").nth(1).locator("td").last.inner_text() == "—"
    for kind, expected in (("low", "Low"), ("stale", "Low"), ("missing", "Missing")):
        button = page.locator(f"[data-map-filter='{kind}']")
        button.click()
        visible = page.locator("[data-map-row]:visible")
        assert visible.count() == 1
        assert visible.locator("th > a").inner_text() == expected
        assert button.get_attribute("aria-pressed") == "true"
    page.locator("[data-map-filter='all']").click()
    assert page.locator("[data-map-row]:visible").count() == 4
    # Loading the initializer twice must remain harmless.
    page.add_script_tag(path=str(ROOT / "src/web/static/decimus-rt-map-filters.js"))
    page.locator("[data-map-filter='missing']").click()
    assert page.locator("[data-map-row]:visible").count() == 1


@pytest.mark.parametrize(
    "lang, label", [("ru", "Нет привязки Google"), ("en", "Google not linked")]
)
def test_maps_attention_localization_does_not_claim_missing_google_card(lang, label):
    html = component("_s_maps.html", lang)
    assert label in html
    assert "ratings.d746.maps." not in html
