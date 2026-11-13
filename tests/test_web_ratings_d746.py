"""D746: actual scoped pages and browser actions, with synthetic source data only."""

# ruff: noqa: F811
from __future__ import annotations

import base64
import csv
import html as html_module
import mimetypes
import re
from contextlib import contextmanager
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
from html.parser import HTMLParser
from io import StringIO
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from ratings_page import подготовить, сводка
from test_web_proofread_browser import browser_page  # noqa: F401
from web_harness import войти, подменить_двери, собрать

from src.db import web_own_profile
from src.db.ratings_read import CountryRow, SourceRatingPeriod
from src.db.ratings_violations import Occurrence
from src.ratings import report, source_periods, violations_view
from src.ratings.model import RKO, RS
from src.ratings.summary import CountryLine, ViolationBlock
from src.web import country_filter
from src.web import ratings as screen

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src/web/static"
PRIVATE = Path.home() / "Documents/workbench/private/decimus/ratings-d746-qa-20261111"
_REAL_SELECT = report.select
_REAL_LOAD = source_periods.load
U_A, U_B = "a" * 32, "b" * 32
CHECK = "c" * 32
COUNTRIES = (
    CountryRow("AA", "Страна А", "Country A", "Developer A", True, "CEE"),
    CountryRow("BB", "Страна Б", "Country B", "Developer B", True, "CAUCASUS"),
)
LOADED = datetime(2026, 11, 2, tzinfo=timezone.utc)
OBSERVED = datetime(2026, 10, 6, tzinfo=timezone.utc)


def _source_rows():
    rows = []
    for code, unit, values in (("AA", U_A, (92, 84, 83, 91)), ("BB", U_B, (64, 70, 72, 74))):
        for kind, begin, end, score in (
            (RS, date(2026, 9, 29), date(2026, 10, 12), values[0]),
            (RS, date(2026, 10, 13), date(2026, 10, 26), values[1]),
            (RKO, date(2026, 9, 28), date(2026, 10, 4), values[2]),
            (RKO, date(2026, 10, 5), date(2026, 10, 11), values[3]),
        ):
            rows.append(
                SourceRatingPeriod(
                    unit, "Demo-" + code, code, kind, begin, end, score, "Published", 1
                )
            )
    return tuple(rows)


def _occurrences(kind):
    return (
        Occurrence(
            1,
            kind,
            U_A,
            "Demo-AA",
            "AA",
            "Product handling",
            "Product",
            "violation",
            "K1",
            2,
            CHECK,
            OBSERVED,
            None,
            LOADED,
        ),
        Occurrence(
            2,
            kind,
            U_B,
            "Demo-BB",
            "BB",
            "Product handling",
            "Product",
            "violation",
            "K1",
            3,
            CHECK,
            OBSERVED,
            None,
            LOADED,
        ),
        Occurrence(
            3,
            kind,
            U_A,
            "Demo-AA",
            "AA",
            "Service issue",
            "Service",
            "violation",
            "K2",
            1,
            CHECK,
            OBSERVED,
            None,
            LOADED,
        ),
    )


@contextmanager
def surface(
    monkeypatch,
    *,
    saved=("AA",),
    lang="en",
    tenant="HQ",
    role="admin",
    source_rows=None,
    available=COUNTRIES,
    violation_text=None,
    hard_known=False,
):
    подготовить(monkeypatch)
    state = {"saved": saved, "source_calls": [], "summary_calls": [], "saved_calls": []}
    monkeypatch.setattr(screen.report, "select", _REAL_SELECT)
    monkeypatch.setattr(screen.read, "countries", lambda: available)
    # This synthetic sheet half-month differs from the true API windows on purpose.
    monkeypatch.setattr(
        screen.read,
        "rs_periods",
        lambda: ((77, date(2026, 10, 1), date(2026, 10, 15), "Legacy", "Legacy"),),
    )
    monkeypatch.setattr(screen.read, "score_facts", lambda **_kw: ())
    monkeypatch.setattr(country_filter, "saved", lambda: state["saved"])

    def actual_rows(*, countries, rating_type, begin, end):
        state["source_calls"].append((tuple(countries), rating_type, begin, end))
        return tuple(
            r
            for r in (source_rows if source_rows is not None else _source_rows())
            if r.country in countries
            and r.rating_type == rating_type
            and r.end_on >= begin
            and r.begin_on <= end
        )

    monkeypatch.setattr(screen.read, "source_rating_periods", actual_rows)
    monkeypatch.setattr(screen.source_periods, "load", _REAL_LOAD)
    monkeypatch.setattr(screen.source_periods, "previous_for", lambda *_a: None)

    def summary(selection, **kw):
        codes = tuple(kw.get("only", tuple(c.code for c in available)))
        state["summary_calls"].append((selection, kw))
        empty = ViolationBlock(0, 1 if hard_known else 0, 0.0 if hard_known else None, ())
        return сводка(
            selection=selection,
            countries=codes,
            lines=tuple(CountryLine(c, 10, 10, None, None) for c in codes),
            total=CountryLine("", 10, 10, None, None),
            rs_units={c: 1 for c in codes},
            rko_units={c: 1 for c in codes},
            rs_by_country={c: empty for c in codes},
            rko_by_country={c: empty for c in codes},
            rs_cluster=empty,
            rko_cluster=empty,
            rs_top=(),
            rs_bottom=(),
        )

    monkeypatch.setattr(screen.report, "build", summary)

    def violations(kind, countries, period, *, previous=None, criterion=None):
        facts = tuple(
            f for f in _occurrences(kind) if period.begin <= f.occurred_at.date() <= period.end
        )
        if violation_text is not None and facts:
            facts = (replace(facts[0], text=violation_text), *facts[1:])
        return violations_view.assemble(
            kind,
            countries,
            period,
            facts,
            previous=previous,
            before=tuple(
                f
                for f in _occurrences(kind)
                if previous.begin <= f.occurred_at.date() <= previous.end
            )
            if previous
            else (),
            criterion=criterion,
        )

    monkeypatch.setattr(screen.violations_view, "build", violations)

    def save(token, countries):
        state["saved_calls"].append((token, tuple(countries)))
        state["saved"] = tuple(countries)
        return True

    monkeypatch.setattr(web_own_profile, "set_country_filter", save)
    подменить_двери(monkeypatch, tenant=tenant, role=role)
    with собрать(tenant=tenant, ui_lang=lang).test_client() as client:
        assert войти(client).status_code == 302
        yield client, state


def page_html(client, path):
    response = client.get(path)
    assert response.status_code == 200, response.get_data(as_text=True)[:300]
    html = response.get_data(as_text=True)
    assert 'class="rt rt-d746"' in html, "Request did not render the actual ratings page"
    return html


def country_links(html):
    return set(re.findall(r'href="/ratings/country/([A-Z]{2})/', html))


def overview_scores(html):
    return [float(x) for x in re.findall(r'rt-overview-card__score">\s*([0-9.]+)', html)]


def test_my_countries_narrows_scores_queries_and_country_links_but_all_is_available(monkeypatch):
    with surface(monkeypatch) as (client, state):
        mine = page_html(client, "/ratings/overview?period=2026-Q4&lang=en")
        assert overview_scores(mine) == [88.0, 87.0]
        assert country_links(mine) == {"AA"}
        assert all(tuple(kw["only"]) == ("AA",) for _, kw in state["summary_calls"])
        assert all(codes == ("AA",) for codes, *_ in state["source_calls"])
        state["summary_calls"].clear()
        whole = page_html(client, "/ratings/overview?period=2026-Q4&lang=en&scope=all")
        assert overview_scores(whole) == [77.5, 80.0]
        assert country_links(whole) == {"AA", "BB"}
        assert all(tuple(kw["only"]) == ("AA", "BB") for _, kw in state["summary_calls"])


def test_shared_country_preference_post_changes_subsequent_ratings(monkeypatch):
    with surface(monkeypatch) as (client, state):
        page_html(client, "/ratings/overview?period=2026-Q4")
        response = client.post(
            "/country/filter",
            data={"countries": "BB", "next": "/ratings/overview?period=2026-Q4&scope=mine"},
            headers={"Origin": "http://localhost"},
        )
        assert response.status_code == 302
        assert state["saved_calls"] and state["saved_calls"][-1][1] == ("BB",)
        html = page_html(client, response.headers["Location"])
        assert overview_scores(html) == [67.0, 73.0]
        assert country_links(html) == {"BB"}


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_navigation_keeps_slice_period_personal_scope_and_language(monkeypatch, lang):
    with surface(monkeypatch, lang=lang) as (client, _state):
        html = page_html(
            client, f"/ratings/rs?period=2026-Q4&group=country&value=BB&scope=all&lang={lang}"
        )
        links = re.findall(r'<a[^>]*href="([^"]+)"[^>]*data-rt-nav', html)
        assert links
        for link in links:
            query = parse_qs(urlparse(html_module.unescape(link)).query)
            assert {k: query.get(k) for k in ("group", "value", "period", "scope", "lang")} == {
                "group": ["country"],
                "value": ["BB"],
                "period": ["2026-Q4"],
                "scope": ["all"],
                "lang": [lang],
            }
        rko = next(html_module.unescape(link) for link in links if "/ratings/rko?" in link)
        landed = page_html(client, rko)
        assert country_links(landed) == {"BB"}
        assert 'value="2026-10-01"' in landed and 'value="2026-12-31"' in landed


def test_real_rs_window_links_and_each_rko_week_has_its_result(monkeypatch, browser_page):
    page = browser_page
    with surface(monkeypatch) as (client, _state):
        html = page_html(client, "/ratings/rs?period=2026-Q4&lang=en")
        page.set_content(html)
        tile = page.locator('[data-source-period="2026-09-29..2026-10-12"]')
        query = parse_qs(urlparse(tile.get_attribute("href")).query)
        assert query["period"] == ["2026-09-29..2026-10-12"]
        assert query["actual_period"] == ["rs"]
        assert "29.09" in tile.inner_text() and "12.10" in tile.inner_text()
        assert query["period_context"] == ["2026-Q4"]
        # Selection changes the score while the quarter's neighboring source periods stay usable.
        selected = page_html(client, tile.get_attribute("href"))
        page.set_content(selected)
        assert page.locator("[data-source-period]").count() == 2
        assert page.locator(".pk-tile__value").first.inner_text().strip().startswith("92.0")
        rko = page_html(client, "/ratings/rko?period=2026-Q4&lang=en")
        page.set_content(rko)
        weeks = page.locator(".rt-week")
        assert weeks.count() == 2
        assert [n.inner_text().strip() for n in weeks.locator("strong").all()] == ["83.0", "91.0"]


def test_control_country_rating_profile_does_not_grant_private_registry_access(monkeypatch):
    with surface(monkeypatch, role="control") as (client, _state):
        html = page_html(client, "/ratings/country/BB/rko?period=2026-Q4&scope=all&lang=en")
        assert "Country B" in html and country_links(html) == {"BB"}
        assert client.get("/ratings/country/BB/inspections?period=2026-Q4").status_code == 404
        assert client.get("/inspections").status_code == 404
        assert client.get("/country/BB").status_code == 404


def test_violation_drilldown_uses_same_country_scope_and_discloses_missing_source_photos(
    monkeypatch,
):
    with surface(monkeypatch) as (client, _state):
        html = page_html(
            client, "/ratings/violations?period=2026-Q4&lang=en&kind=rs&criterion=rs:criterion:K1"
        )
        assert "Demo-AA" in html and "Demo-BB" not in html
        assert "66.7%" in html
        assert "saved source data contains no photos" in html
        assert "checkupId=" + CHECK in html
        assert country_links(html) == {"AA"}


def test_violation_expands_in_place_under_its_row_with_countries_units_and_check_links(
    monkeypatch,
):
    url = "/ratings/violations?period=2026-Q4&lang=en&kind=rs&scope=all"
    with surface(monkeypatch) as (client, _state):
        html = page_html(client, url + "&criterion=rs:criterion:K1")
        table = html[html.index("rt-violations-table") :]
        table = table[: table.index("</table>")]
        # The violation column comes first and the expansion sits right under its own row.
        assert table.index("<th>Violation</th>") < table.index('class="num">Share')
        row, detail = table.index('id="rt-violation-open"'), table.index("rt-violation-detail")
        assert row < detail < table.index("Service issue")
        opened = table[detail:]
        assert opened.index("Country A") < opened.index("Demo-AA")
        assert opened.index("Country B") < opened.index("Demo-BB")
        assert "<details" in opened and "checkupId=" + CHECK in opened
        assert 'target="_blank"' in opened
        # No separate detail block is left below the table.
        assert html.count("saved source data contains no photos") == 1
        # Pressing the open violation again collapses it (plain link, works without JS).
        collapse = re.search(r'<a href="([^"]+)" aria-expanded="true"', table).group(1)
        assert "criterion=" not in collapse
        closed = page_html(client, collapse.replace("&amp;", "&"))
        assert "rt-violation-detail" not in closed and 'aria-expanded="false"' in closed


def test_violation_expansion_shows_only_the_scoped_countries(monkeypatch):
    with surface(monkeypatch) as (client, _state):
        html = page_html(
            client, "/ratings/violations?period=2026-Q4&lang=en&kind=rs&criterion=rs:criterion:K1"
        )
        detail = html[html.index("rt-violation-detail") :]
        assert "Demo-AA" in detail and "Demo-BB" not in detail and "Country B" not in detail


class Stylesheets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "link" and values.get("rel") == "stylesheet":
            self.hrefs.append(values["href"])
        if tag == "script" and values.get("src"):
            self.scripts.append(values["src"])


def local_static(url):
    path = urlparse(url).path
    if not path.startswith("/static/"):
        return None
    candidate = (STATIC / path.removeprefix("/static/")).resolve()
    return candidate if candidate.is_relative_to(STATIC) and candidate.is_file() else None


def load_browser(page, html, width):
    """Render the actual shell and every locally included asset; never use a server."""
    styles = Stylesheets()
    styles.feed(html)
    assert styles.hrefs and all(local_static(href) for href in (*styles.hrefs, *styles.scripts))
    page.set_viewport_size({"width": width, "height": 900})
    page.unroute("**/*")
    loaded = []

    def resource(route):
        parsed = urlparse(route.request.url)
        if parsed.netloc != "decimus-qa.invalid":
            route.abort()
            return
        local = local_static(route.request.url)
        if local is not None:
            loaded.append(parsed.path)
            route.fulfill(
                path=str(local),
                content_type=mimetypes.guess_type(local.name)[0] or "application/octet-stream",
            )
        elif route.request.is_navigation_request():
            route.fulfill(body=html, content_type="text/html; charset=utf-8")
        else:
            route.abort()

    page.route("**/*", resource)
    page.goto("http://decimus-qa.invalid/ratings/preview", wait_until="load")
    page.evaluate("document.fonts.ready")
    # This includes the table foundation and pick controls from the real base shell.
    assert "/static/decimus-pick.css" in loaded
    assert [urlparse(href).path for href in styles.hrefs] == page.locator(
        'link[rel="stylesheet"]'
    ).evaluate_all("nodes => nodes.map(n => new URL(n.href).pathname)")
    assert all(urlparse(href).path in loaded for href in (*styles.hrefs, *styles.scripts))


@pytest.mark.parametrize("width", [390, 1280])
@pytest.mark.parametrize("lang", ["ru", "en"])
def test_dialog_keyboard_focus_and_responsive_rating_controls(
    monkeypatch, browser_page, width, lang
):
    page = browser_page
    with surface(monkeypatch, lang=lang) as (client, _state):
        html = page_html(client, f"/ratings/rs?period=2026-Q4&lang={lang}")
    load_browser(page, html, width)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
    trigger = page.locator("[data-open-violations]")
    trigger.click()
    panel = page.locator('[role="dialog"]')
    page.wait_for_function("document.querySelector('[data-violations-dialog]').open")
    first = panel.locator('a[href],button,input,select,textarea,[tabindex="0"]').first
    close = panel.locator("[data-close-violations]")
    page.wait_for_function(
        "document.activeElement===document.querySelector('[data-close-violations]')"
    )
    assert close.evaluate("e=>e===document.activeElement")
    bounds = panel.bounding_box()
    assert bounds and bounds["x"] >= 0 and bounds["x"] + bounds["width"] <= width
    PRIVATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    page.screenshot(path=str(PRIVATE / f"ratings-dialog-{lang}-{width}.png"), full_page=True)
    first.press("Shift+Tab")
    last = panel.locator("a[href]").last
    assert last.evaluate("e=>e===document.activeElement")
    last.press("Tab")
    assert first.evaluate("e=>e===document.activeElement")
    first.press("Escape")
    assert not page.locator("[data-violations-dialog]").evaluate("e=>e.open")
    assert trigger.evaluate("e=>e===document.activeElement")
    PRIVATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    page.screenshot(path=str(PRIVATE / f"ratings-rs-{lang}-{width}.png"), full_page=True)
    artifact = PRIVATE / f"ratings-rs-{lang}-{width}.html"
    artifact.write_text(standalone_html(html))
    artifact.chmod(0o600)


def test_dialog_binds_after_partial_ratings_navigation(monkeypatch, browser_page):
    page = browser_page
    with surface(monkeypatch) as (client, _state):
        html = page_html(client, "/ratings/rs?period=2026-Q4&lang=en")
    load_browser(page, html, 1280)
    # Ratings navigation replaces server HTML without reloading its already loaded script.
    page.evaluate("""() => {
      const old = document.querySelector('[data-violations-dialog]');
      const fresh = old.cloneNode(true);
      delete fresh.dataset.dialogBound;
      old.replaceWith(fresh);
      document.dispatchEvent(new CustomEvent('decimus:ratings'));
    }""")
    page.locator("[data-open-violations]").click()
    page.wait_for_function(
        "document.activeElement===document.querySelector('[data-close-violations]')"
    )
    page.keyboard.press("Escape")
    assert not page.locator("[data-violations-dialog]").evaluate("e=>e.open")
    assert page.locator("[data-open-violations]").evaluate("e=>e===document.activeElement")


def gallery_contracts(monkeypatch):
    """Explicit synthetic data contracts for the visual gallery; never read a real database."""
    from src.db.agg_store import UnitRow
    from src.db.inspection_timeline import Day
    from src.ratings import compare, coverage
    from src.ratings.aggregators.summary import AggScore
    from src.ratings.clients import Line, Score
    from src.ratings.maps import CountryMaps, MapScore
    from src.ratings.risk_sources import RiskRow, Source
    from src.web import inspection_timeline, ratings_clients, ratings_platforms, ratings_risk

    day = date(2026, 10, 31)
    unit = UnitRow(U_A, "AA", "Demo-AA", 0, 0, True, None, date(2026, 1, 1))
    google = coverage.Cell(coverage.SCORE, 4.3, 5, day)
    missing = coverage.Cell(coverage.ABSENT)
    map_rows = coverage.Coverage(
        (coverage.Platform("2", "map"), coverage.Platform("1", "map")),
        (coverage.Row(unit, False, {"2": google, "1": missing}),),
        0,
        0,
    )
    monkeypatch.setattr(
        screen,
        "_maps",
        lambda *_a: (
            CountryMaps("AA", {2: MapScore(4.3, 31, 1, 0.1), 1: MapScore(None, 0, 0)}, day),
        ),
    )
    monkeypatch.setattr(ratings_platforms, "build_maps", lambda *_a, **_kw: map_rows)
    agg_score = AggScore(9.1, 10, 120, 1)
    agg_row = coverage.Row(unit, False, {"wolt": coverage.Cell(coverage.SCORE, 9.1, 10, day)})
    agg = ratings_platforms.AggView(
        ("wolt",),
        (ratings_platforms.Tile("wolt", agg_score, 1, 1),),
        (ratings_platforms.CountryBlock("AA", {"wolt": agg_score}, (agg_row,)),),
        (),
        day,
        False,
    )
    monkeypatch.setattr(ratings_platforms, "build_agg", lambda *_a, **_kw: agg)
    risk = ratings_risk.CombinedRisk(
        (
            RiskRow(
                U_A,
                "Demo-AA",
                "AA",
                (
                    Source("rs", (68.0, 65.0, 60.0)),
                    Source("wolt", (8.8, 8.5, 8.1, 8.0)),
                ),
            ),
        ),
        (),
    )
    monkeypatch.setattr(ratings_risk, "build", lambda *_a, **_kw: risk)
    score = Score(Decimal("4.6"), 10)
    clients = ratings_clients.View(
        Line("", "", "", score, score, Score(Decimal("4.6"), 20)),
        (Line(U_A, "Demo-AA", "AA", score, score, Score(Decimal("4.6"), 20)),),
        date(2026, 10, 1),
        day,
        (date(2026, 10, 1),),
        date(2026, 10, 1),
        LOADED,
    )
    monkeypatch.setattr(ratings_clients, "load", lambda *_a, **_kw: clients)
    comparison = compare.Comparison(
        (compare.Line("Developer A", ("AA",), 1, 88.0, None, 87.0, None),),
        (compare.Line("AA", ("AA",), 1, 88.0, None, 87.0, None),),
    )
    monkeypatch.setattr(screen.rcompare, "build", lambda *_a, **_kw: comparison)
    monkeypatch.setattr(
        inspection_timeline.store,
        "days",
        lambda **_kw: (
            Day(date(2026, 9, 1), 1, 86.0),
            Day(date(2026, 10, 1), 1, 91.0),
            Day(date(2026, 10, 30), 1, 87.0),
        ),
    )


def standalone_html(html):
    """Portable HTML embeds the exact shell CSS, fonts and visible local images."""

    def encoded(local):
        media = mimetypes.guess_type(local.name)[0] or "application/octet-stream"
        return "data:" + media + ";base64," + base64.b64encode(local.read_bytes()).decode()

    def css(match):
        tag = match.group(0)
        href = re.search(r'href="([^"]+)"', tag)
        if 'rel="manifest"' in tag:
            return ""
        if not href or 'rel="stylesheet"' not in tag:
            local = local_static(html_module.unescape(href.group(1))) if href else None
            return tag.replace(href.group(1), encoded(local)) if local else tag
        local = local_static(html_module.unescape(href.group(1)))
        assert local is not None

        def asset(reference):
            value = reference.group(1).strip("\"'")
            if value.startswith(("data:", "#", "http:", "https:")):
                return reference.group(0)
            target = (local.parent / value).resolve()
            assert target.is_relative_to(STATIC) and target.is_file()
            return "url('" + encoded(target) + "')"

        content = re.sub(r"url\(([^)]+)\)", asset, local.read_text())
        return '<style data-local-source="' + local.name + '">' + content + "</style>"

    result = re.sub(r"<link\b[^>]*>", css, html)
    result = re.sub(r"<script\b[^>]*src=[^>]*>\s*</script>", "", result)

    def image(match):
        local = local_static(html_module.unescape(match.group(1)))
        return 'src="' + encoded(local) + '"' if local else match.group(0)

    result = re.sub(r'src="(/static/[^"]+)"', image, result)
    banner = (
        '<aside id="qa-preview-note" style="background:#fff3d4;color:#573900;'
        'padding:12px 20px;font:14px/1.5 system-ui">Синтетическое превью интерфейса. '
        "Данные вымышлены. Диалог, сортировка и CSV доступны; "
        "серверные фильтры, переходы и сохранение требуют приложения.</aside>"
    )
    result = result.replace("<body>", "<body>" + banner)
    preview_guard = """
    document.addEventListener('submit', function(e) {
      e.preventDefault();
      document.getElementById('qa-preview-note').textContent =
        'Синтетическое превью: сохранение и серверные фильтры доступны в приложении.';
    });
    document.addEventListener('click', function(e) {
      var a=e.target.closest('a[href]');
      if(a && !a.getAttribute('href').startsWith('#') &&
         !a.href.startsWith('blob:') && !a.href.startsWith('data:')) {
        e.preventDefault();
        document.getElementById('qa-preview-note').textContent =
          'Синтетическое превью: навигация и ссылки на данные доступны в приложении.';
      }
    });
    """
    interactive = (STATIC / "decimus-rt-d746.js").read_text()
    map_filters = STATIC / "decimus-rt-map-filters.js"
    if map_filters.is_file():
        interactive += "\n" + map_filters.read_text()
    result = result.replace(
        "</body>",
        "<script>" + interactive + preview_guard + "</script></body>",
    )
    return result


@pytest.mark.parametrize(
    "topic",
    ["overview", "rko", "violations", "maps", "risk", "clients", "agg", "compare", "inspections"],
)
@pytest.mark.parametrize("width", [390, 1280])
@pytest.mark.parametrize("lang", ["ru", "en"])
def test_new_rating_pages_fit_viewport(monkeypatch, browser_page, topic, width, lang):
    page = browser_page
    with surface(monkeypatch, lang=lang) as (client, _state):
        gallery_contracts(monkeypatch)
        html = page_html(client, f"/ratings/{topic}?period=2026-Q4&lang={lang}")
    load_browser(page, html, width)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
    PRIVATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    page.screenshot(path=str(PRIVATE / f"ratings-{topic}-{lang}-{width}.png"), full_page=True)
    artifact = PRIVATE / f"ratings-{topic}-{lang}-{width}.html"
    artifact.write_text(standalone_html(html))
    artifact.chmod(0o600)


def test_overview_sort_keeps_missing_scores_last_and_preserves_a_real_zero(
    monkeypatch, browser_page
):
    countries = (
        *COUNTRIES,
        CountryRow("CC", "Страна В", "Country C", None, True, "CEE"),
        CountryRow("DD", "Страна Г", "Country D", None, True, "CEE"),
    )
    rows = tuple(r for r in _source_rows() if not (r.country == "BB" and r.rating_type == RKO))
    rows += (
        replace(rows[0], country="CC", unit="d" * 32, unit_name="Demo-CC", score=95),
        replace(
            next(r for r in rows if r.rating_type == RKO),
            country="CC",
            unit="d" * 32,
            unit_name="Demo-CC",
            score=0,
        ),
    )
    with surface(monkeypatch, saved=(), source_rows=rows, available=countries) as (client, _):
        html = page_html(client, "/ratings/overview?period=2026-Q4&lang=en&scope=all")
    page = browser_page
    load_browser(page, html, 1280)
    table = page.locator("[data-overview-sort] tbody")
    assert table.locator("th a").all_text_contents() == [
        "Country C",
        "Country A",
        "Country B",
        "Country D",
    ]
    page.locator("[data-overview-order]").select_option("rko")
    assert table.locator("th a").all_text_contents() == [
        "Country A",
        "Country C",
        "Country B",
        "Country D",
    ]
    assert table.locator("tr").nth(1).get_attribute("data-rko") == "0.0"
    assert table.locator("tr").nth(2).get_attribute("data-rko") == ""


def test_source_violation_kpi_opens_keyboard_accessible_modal(monkeypatch, browser_page):
    with surface(monkeypatch) as (client, _):
        html = page_html(client, "/ratings/rko?period=2026-Q4&lang=en")
    page = browser_page
    load_browser(page, html, 1280)
    page.locator("[data-open-violations]").click()
    page.wait_for_function("document.querySelector('[data-violations-dialog]').open")
    page.wait_for_function(
        "document.activeElement===document.querySelector('[data-close-violations]')"
    )


def test_modal_country_slice_preserves_rko_source_actual_window_and_scope(
    monkeypatch, browser_page
):
    with surface(monkeypatch, lang="ru") as (client, _):
        html = page_html(
            client,
            "/ratings/rko?period=2026-10-05..2026-10-11&actual_period=rko&period_context=2026-Q4&lang=ru&scope=all",
        )
        page = browser_page
        load_browser(page, html, 1280)
        page.locator("[data-open-violations]").click()
        country = page.locator(".rt-violations__country select option", has_text="Страна Б")
        href = country.get_attribute("value")
        query = parse_qs(urlparse(href).query)
        assert {
            key: query[key]
            for key in (
                "group",
                "value",
                "period",
                "actual_period",
                "period_context",
                "lang",
                "scope",
                "show_violations",
            )
        } == {
            "group": ["country"],
            "value": ["BB"],
            "period": ["2026-10-05..2026-10-11"],
            "actual_period": ["rko"],
            "period_context": ["2026-Q4"],
            "lang": ["ru"],
            "scope": ["all"],
            "show_violations": ["1"],
        }
        selected = page_html(client, href)
        page.set_content(selected)
        all_link = page.locator(".rt-violations__panel > a").get_attribute("href")
        assert urlparse(all_link).path == "/ratings/violations"
        all_query = parse_qs(urlparse(all_link).query)
        assert all_query["kind"] == ["rko"] and all_query["value"] == ["BB"]
        assert all_query["period"] == query["period"] and all_query["scope"] == ["all"]
        detail = page_html(client, all_link)
        assert 'data-rt-section="violations"' in detail
        assert "Demo-AA" not in detail


@pytest.mark.parametrize(
    "text", ['=SUM(1,2) "Кухня"\nстрока', '+check, "Фасад"', "-3+1", "@SUM(1,2)"]
)
def test_violation_csv_keeps_display_unicode_quotes_and_neutralizes_formulas(
    monkeypatch, browser_page, text
):
    with surface(monkeypatch, violation_text=text) as (client, _):
        html = page_html(client, "/ratings/rs?period=2026-Q4&lang=ru")
    page = browser_page
    load_browser(page, html, 1280)
    page.locator("[data-open-violations]").click()
    displayed = page.locator(".rt-violations-table tbody tr th").first.inner_text().strip()
    assert displayed.startswith(text.replace("\n", " "))
    with page.expect_download() as result:
        page.locator("[data-export-violations]").click()
    download = result.value
    assert download.suggested_filename == "ratings-violations.csv"
    raw = Path(download.path()).read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    cells = list(csv.reader(StringIO(raw.decode("utf-8-sig"))))
    assert cells[1][0] == "'" + displayed


@pytest.mark.parametrize(
    "topic",
    [
        "overview",
        "rs",
        "rko",
        "violations",
        "maps",
        "risk",
        "clients",
        "agg",
        "compare",
        "inspections",
    ],
)
def test_desktop_reference_width_gallery(monkeypatch, browser_page, topic):
    with surface(monkeypatch, lang="ru") as (client, _):
        gallery_contracts(monkeypatch)
        html = page_html(client, f"/ratings/{topic}?period=2026-Q4&lang=ru")
    page = browser_page
    load_browser(page, html, 1440)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
    PRIVATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    page.screenshot(path=str(PRIVATE / f"ratings-{topic}-ru-1440.png"), full_page=True)
    artifact = PRIVATE / f"ratings-{topic}-ru-1440.html"
    artifact.write_text(standalone_html(html))
    artifact.chmod(0o600)
    if topic in ("rs", "rko"):
        page.locator("[data-open-violations]").click()
        page.wait_for_function(
            "document.activeElement===document.querySelector('[data-close-violations]')"
        )
        assert ("РС" if topic == "rs" else "РКО") in page.locator(
            ".rt-violations__panel header h2"
        ).inner_text()
        page.screenshot(path=str(PRIVATE / f"ratings-dialog-{topic}-ru-1440.png"), full_page=True)
        page.keyboard.press("Escape")


def test_map_filters_initialize_after_partial_source_to_maps_navigation(monkeypatch, browser_page):
    with surface(monkeypatch, lang="en") as (client, _):
        gallery_contracts(monkeypatch)
        rs_html = page_html(client, "/ratings/rs?period=2026-Q4&lang=en")
        maps_html = page_html(client, "/ratings/maps?period=2026-Q4&lang=en")
    page = browser_page
    load_browser(page, rs_html, 1280)
    assert page.locator("[data-map-filters]").count() == 0
    page.evaluate(
        """html => {
      const parsed = new DOMParser().parseFromString(html, 'text/html');
      document.querySelector('.rt-d746').replaceWith(parsed.querySelector('.rt-d746'));
      document.dispatchEvent(new CustomEvent('decimus:ratings'));
      document.dispatchEvent(new CustomEvent('decimus:navigation'));
    }""",
        maps_html,
    )
    root = page.locator("[data-map-filters]")
    assert root.locator(".rt-map-filters").is_visible()
    assert root.locator("[data-map-row]:visible").count() == 1
    root.locator('[data-map-filter="low"]').click()
    assert root.locator("[data-map-row]:visible").count() == 0
    assert root.locator('[data-map-filter="low"]').get_attribute("aria-pressed") == "true"
    root.locator('[data-map-filter="all"]').click()
    assert root.locator("[data-map-row]:visible").count() == 1


@pytest.mark.parametrize("known", [False, True])
@pytest.mark.parametrize("kind", ["rs", "rko"])
@pytest.mark.parametrize("lang", ["ru", "en"])
def test_unknown_hard_coverage_is_distinct_from_a_known_zero(monkeypatch, known, kind, lang):
    with surface(monkeypatch, lang=lang, hard_known=known) as (client, _):
        html = page_html(client, f"/ratings/{kind}?period=2026-Q4&lang={lang}")
    # A present standards score must not be described as absent merely because the
    # separate severity-classification export was not observed.
    first_score = re.search(r'pk-tile__value">\s*([0-9.]+)', html)
    assert first_score and float(first_score.group(1)) == (88.0 if kind == "rs" else 87.0)
    block = re.search(r"<section\b[^>]*\bdata-rt-hard[^>]*>(.*?)</section>", html, re.S)
    assert block
    unavailable = {
        "ru": "Данных о хард-нарушениях за выбранный период нет",
        "en": "Hard-violation data is unavailable for the selected period",
    }[lang]
    if known:
        assert unavailable not in block.group(1)
        assert '<span class="pk-block__count">0</span>' in block.group(1)
    else:
        assert unavailable in block.group(1)
        assert 'class="pk-block__count"' not in block.group(1)


def test_violation_escape_closes_when_focus_is_still_outside_modal(monkeypatch, browser_page):
    """Opening from an external KPI must not depend on the delayed details toggle event."""
    with surface(monkeypatch, lang="ru") as (client, _state):
        html = page_html(client, "/ratings/rko?period=2026-Q4&lang=ru")
    page = browser_page
    load_browser(page, html, 390)
    opener = page.locator("[data-open-violations]")
    opener.click()
    page.wait_for_function("document.querySelector('[data-violations-dialog]').open")
    # Model the race: the outside KPI retains focus until the native toggle callback runs.
    opener.focus()
    page.keyboard.press("Escape")
    page.wait_for_function("!document.querySelector('[data-violations-dialog]').open")


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_period_tiles_are_compact_and_summary_tiles_carry_no_service_text(monkeypatch, lang):
    """D766: у плитки периода нет «завершился» и служебных подписей, «Нарушений» — сама ссылка."""
    with surface(monkeypatch, lang=lang) as (client, _state):
        html = page_html(client, f"/ratings/rko?period=2026-Q4&lang={lang}")
    for gone in ("Даты периодов Dodo IS", "Dodo IS period dates", "завершился", "ended"):
        assert gone not in html
    assert 'class="rt-week' in html and "<strong>" in html
    # Служебное про происхождение оценок — под «?», а не подписью внизу блока.
    assert "rt-periods__source" not in html
    assert 'id="info-periods-rko"' in html
    # Длинное пояснение плитки «Пиццерий с оценкой» лежит под «?», не в самой плитке.
    assert 'id="info-tile-scored"' in html
    assert 'pk-tile__sub">Число обязательных' not in html
    assert 'pk-tile__sub">The number' not in html
    # Плитка «Нарушений» открывает разбор сама, кнопки рядом с ней нет.
    assert re.search(r'<a class="pk-tile pk-tile--link"[^>]*data-open-violations', html)
    assert '<summary class="btn' not in html
