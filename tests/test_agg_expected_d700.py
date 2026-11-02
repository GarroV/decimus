"""Охват агрегаторов: «нет на площадке» не пробел, а сведение (D700).

Ядро (данные, которые читают как факт): привязка точек к пиццериям (закрепления,
дубли карточки, 400 м), состояния ячеек охвата, ожидаемые страны, тестовые
пиццерии, тон страны на экране администрирования. Чистый Python, без базы.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from src.db import agg_store
from src.db.agg_store import CoverageRow, OpenPoint, UnitRow
from src.db.ratings_read import CountryRow
from src.ratings import coverage
from src.ratings.aggregators import base, collect
from src.web import aggregators_admin as screen
from src.web import ratings_platforms

TODAY = date(2026, 11, 2)
NOW = datetime(2026, 11, 2, tzinfo=UTC)


def unit(key: str, country: str = "TR", lat: float = 41.0, lng: float = 29.0) -> UnitRow:
    return UnitRow(key * 32 if len(key) == 1 else key, country, key, lat, lng, True, None, TODAY)


def rated(key: str, score: float = 4.5) -> CoverageRow:
    return CoverageRow("wolt", key, "TR", score, 5, TODAY)


# --- привязка точек ---------------------------------------------------------


def test_закреплённая_пара_берётся_первой_даже_дальше_400_м() -> None:
    # Trendyol геокодирует плохо: точка `374489` в 1500 м от Adana-3, зато в 30 м от чужой
    # пиццерии. Закрепление держит её за Adana-3, а чужая пиццерия остаётся без пары.
    pairs = [("374489", "adana3", 1500.0), ("374489", "other", 30.0)]

    assert collect.assign(pairs) == {"374489": ("other", 30)}
    assert collect.assign(pairs, {"374489": "adana3"}) == {"374489": ("adana3", 1500)}


def test_закреплённые_точка_и_пиццерия_выпадают_из_расчёта_по_расстоянию() -> None:
    pairs = [("p1", "u1", 1000.0), ("p2", "u1", 20.0), ("p1", "u2", 10.0)]

    assert collect.assign(pairs, {"p1": "u1"}) == {"p1": ("u1", 1000)}


def test_закрепление_без_пары_в_этом_сборе_пропускается() -> None:
    assert collect.assign([("a", "u1", 10.0)], {"gone": "u1", "a": "nobody"}) == {"a": ("u1", 10)}


def test_пиццерия_дальше_400_м_без_закрепления_не_привязывается() -> None:
    assert collect.assign([("a", "u1", 401.0)]) == {}


def test_дубль_карточки_отдаёт_привязку_той_что_с_оценкой() -> None:
    # `dodo_pwsfq` ближе, но без оценки; `dodo_bgp2m` в пределах 50 м и с оценкой (Yerevan-2).
    pairs = [("dodo_pwsfq", "yer2", 5.0), ("dodo_bgp2m", "yer2", 20.0)]
    quality = {"dodo_pwsfq": (False, 0), "dodo_bgp2m": (True, 1170)}

    assert collect.assign(pairs) == {"dodo_pwsfq": ("yer2", 5)}
    assert collect.assign(pairs, quality=quality) == {"dodo_bgp2m": ("yer2", 20)}


def test_из_двух_точек_с_оценкой_берётся_с_большим_числом_оценок() -> None:
    pairs = [("a", "u1", 5.0), ("b", "u1", 40.0)]

    got = collect.assign(pairs, quality={"a": (True, 10), "b": (True, 900)})

    assert got == {"b": ("u1", 40)}


def test_оценка_не_перебивает_расстояние_за_пределами_дубля() -> None:
    # Вторая точка в 120 м — уже не дубль, а другая карточка: ближайшая остаётся ближайшей.
    pairs = [("near", "u1", 10.0), ("far", "u1", 120.0)]

    assert collect.assign(pairs, quality={"far": (True, 5000)}) == {"near": ("u1", 10)}


def test_качество_точки_из_найденного() -> None:
    def found(score: float | None, votes: int | None) -> tuple[base.Found, str]:
        return base.Found("k", "n", None, 1.0, 1.0, score, 5, votes, True, None, {}), "AM"

    assert collect._quality({"a": found(4.6, 1170), "b": found(None, None)}) == {
        "a": (True, 1170),
        "b": (False, 0),
    }


def test_поиск_держит_закрепление_и_дубль_через_весь_сбор() -> None:
    adana = collect.DodoUnit("a" * 32, "Adana-3", 37.0, 35.3, "TR")

    def found(key: str, lat: float, lng: float, score: float | None) -> base.Found:
        return base.Found(key, key, None, lat, lng, score, 5, 10 if score else None, True, None, {})

    def search(http: object, lat: float, lng: float, country: str, cache: object) -> list[object]:
        return [found("374489", 37.05, 35.3, 4.4), found("dup", 37.0, 35.3, None)]

    module = SimpleNamespace(KEY="trendyol_go", GAP_SEC=0, COUNTRIES={"TR": "tr"}, search=search)

    plain, _, _, _, _ = collect._search_one(module, [adana], TODAY)
    pinned, _, _, _, _ = collect._search_one(module, [adana], TODAY, {"374489": adana.dodo_id})

    assert {p.point_key: p.dodo_id for p in plain} == {"374489": None, "dup": adana.dodo_id}
    assert {p.point_key: p.dodo_id for p in pinned} == {"374489": adana.dodo_id, "dup": None}


# --- состояния ячеек охвата -------------------------------------------------


def cells(
    units: list[UnitRow],
    linked: list[CoverageRow],
    hints: coverage.Hints,
    expected: dict[str, set[str]] | None = None,
) -> dict[str, coverage.Cell]:
    cov = coverage.build(units, (), linked, expected or {"wolt": {"TR"}}, TODAY, hints=hints)
    return {row.unit.name: row.cells["wolt"] for row in cov.rows}


def test_поисковая_площадка_без_точки_и_без_кандидата_это_нет_на_площадке() -> None:
    got = cells([unit("a")], [], coverage.Hints(searched=frozenset({"wolt"})))

    assert got["a"].state == coverage.NOT_LISTED and not got["a"].marked


def test_старое_поведение_без_подсказок_осталось() -> None:
    assert cells([unit("a")], [], coverage.Hints())["a"].state == coverage.MISSING


def test_кандидат_рядом_делает_пробел_а_не_нет_на_площадке() -> None:
    candidate = coverage.Candidate("pt", "Dodo", "https://x", 900)
    hints = coverage.Hints(frozenset({"wolt"}), near={("wolt", unit("a").dodo_id): (candidate,)})

    got = cells([unit("a")], [], hints)["a"]

    assert got.state == coverage.MISSING and got.candidates == (candidate,)


def test_площадка_без_поиска_без_отметки_это_пробел_с_отметкой_сведение() -> None:
    a = unit("a")

    open_gap = cells([a], [], coverage.Hints())["a"]
    marked = cells([a], [], coverage.Hints(absent=frozenset({("wolt", a.dodo_id)})))["a"]

    assert open_gap.state == coverage.MISSING
    assert marked.state == coverage.NOT_LISTED and marked.marked


def test_привязанная_точка_сильнее_любой_отметки() -> None:
    a = unit("a")
    hints = coverage.Hints(frozenset({"wolt"}), frozenset({("wolt", a.dodo_id)}))

    assert cells([a], [rated(a.dodo_id)], hints)["a"].state == coverage.SCORE


def test_страна_вне_ожидаемых_остаётся_нет_в_стране() -> None:
    # Колонка есть (в Турции Wolt ожидается), а у сербской пиццерии ячейка пустая.
    got = cells([unit("a", "RS"), unit("b")], [], coverage.Hints(searched=frozenset({"wolt"})))

    assert got["a"].state == coverage.ABSENT and got["b"].state == coverage.NOT_LISTED


def test_нет_на_площадке_не_считается_пропущенной_пиццерией() -> None:
    cov = coverage.build(
        [unit("a"), unit("b")],
        (),
        [],
        {"wolt": {"TR"}},
        TODAY,
        hints=coverage.Hints(searched=frozenset({"wolt"})),
    )

    assert cov.unlinked == 0


def test_кандидаты_только_той_же_страны_в_пределах_3_км_ближайшие_первыми() -> None:
    a = unit("a", "TR", 41.0, 29.0)
    points = [
        OpenPoint("wolt", "near", "TR", "N", None, 41.0, 29.001),  # ~84 м
        OpenPoint("wolt", "mid", "TR", "M", None, 41.01, 29.0),  # ~1,1 км
        OpenPoint("wolt", "far", "TR", "F", None, 41.1, 29.0),  # ~11 км
        OpenPoint("wolt", "abroad", "GE", "G", None, 41.0, 29.0),
        OpenPoint("glovo", "other", "TR", "O", None, 41.0, 29.0),
    ]

    got = coverage.nearby([a], points)

    assert [c.point_key for c in got[("wolt", a.dodo_id)]] == ["near", "mid"]
    assert [c.point_key for c in got[("glovo", a.dodo_id)]] == ["other"]


# --- ожидаемые страны -------------------------------------------------------


def test_ожидаемые_страны_поисковой_площадки_там_где_есть_точки(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    has = {"wolt": frozenset({"EE"}), "bolt_food": frozenset(), "glovo": frozenset({"NG"})}
    monkeypatch.setattr(agg_store, "point_countries", lambda key: has.get(key, frozenset()))

    got = ratings_platforms.agg_countries()

    assert got["wolt"] == {"EE"}  # прежде — все страны сборщика (RS, HR…)
    assert got["bolt_food"] == frozenset()
    assert got["glovo"] == {"NG"}


# --- тестовые пиццерии ------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "is_test"),
    [("TEST-1", True), ("test-12", True), (" Test-3 ", True), ("Bishkek-1", False),
     ("TEST-", False), ("TEST-1A", False), ("Latest-1", False)],
)  # fmt: skip
def test_тестовая_пиццерия_по_имени(name: str, is_test: bool) -> None:
    assert agg_store.is_test_unit(name) is is_test


# --- экран администрирования -----------------------------------------------

COUNTRIES = (CountryRow("TR", "Турция", "Turkey", None, True),)


def load() -> agg_store.LoadState:
    return agg_store.LoadState("wolt", NOW, "ok", 4, None, NOW)


def tone(units: list[UnitRow], linked: list[CoverageRow], hints: coverage.Hints) -> str:
    (row,) = screen.build(COUNTRIES, units, linked, {"wolt": {"TR"}}, (load(),), (), TODAY, hints)
    return row.tone


def test_страна_зелёная_когда_кроме_нет_на_площадке_и_без_оценки_ничего_нет() -> None:
    a, b, c = unit("a"), unit("b"), unit("c")
    hints = coverage.Hints(searched=frozenset({"wolt"}))

    assert (
        tone(
            [a, b, c],
            [rated(a.dodo_id), CoverageRow("wolt", b.dodo_id, "TR", None, None, None)],
            hints,
        )
        == "green"
    )


def test_страна_жёлтая_пока_есть_кандидат_рядом_или_неотмеченная_площадка() -> None:
    a, b = unit("a"), unit("b")
    candidate = coverage.Candidate("pt", None, None, 1500)
    near = {("wolt", b.dodo_id): (candidate,)}

    assert (
        tone([a, b], [rated(a.dodo_id)], coverage.Hints(frozenset({"wolt"}), near=near)) == "yellow"
    )
    assert tone([a, b], [rated(a.dodo_id)], coverage.Hints()) == "yellow"
    marked = coverage.Hints(absent=frozenset({("wolt", b.dodo_id)}))
    assert tone([a, b], [rated(a.dodo_id)], marked) == "green"


def test_нет_на_площадке_идёт_в_сведения_а_не_в_ожидаемое() -> None:
    a, b = unit("a"), unit("b")

    (row,) = screen.build(
        COUNTRIES,
        [a, b],
        [rated(a.dodo_id)],
        {"wolt": {"TR"}},
        (load(),),
        (),
        TODAY,
        coverage.Hints(searched=frozenset({"wolt"})),
    )
    (p,) = row.platforms

    assert (p.expected, p.linked, p.missing) == (1, 1, 0)
    assert [(g.unit, g.state) for g in p.gaps] == [("b", "not_listed")]
