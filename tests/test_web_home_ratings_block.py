"""Блок «Рейтинги» на «Главной» (D418): числа те же, что на странице «Рейтинги».

Главное, что сторожится: блок ничего не считает сам. Его значения обязаны
совпадать со строками сводки, которые строит `report.build` для того же среза и
периода, — на подменённых фактах, вместе с движением к прошлому периоду. Второе —
выбор страны сужает блок до одной колонки, третье — отказ чтения называется
строкой, а не пустотой.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import date
from typing import Any

import pytest
from flask.testing import FlaskClient
from test_web_overview import снимок
from web_harness import войти, подменить_двери, собрать

from src.db import agg_store, maps_store
from src.db import ratings_read as read
from src.db.errors import RatingsError
from src.db.ratings_read import CountryRow
from src.ratings import maps as rmaps
from src.ratings import report
from src.web import home_ratings_block as block
from src.web import overview as overview_data
from src.web.registry_period import Period
from src.web.texts import t

СЕНТЯБРЬ = Period(date(2026, 9, 1), date(2026, 9, 30))
СЕГОДНЯ = date(2026, 10, 12)

СТРАНЫ = (
    CountryRow("RS", "Сербия", "Serbia", None, True, "CEE"),
    CountryRow("GE", "Грузия", "Georgia", None, True, "CEE"),
    CountryRow("TR", "Турция", "Turkey", None, True, "OTHER"),
    CountryRow("CY", "Кипр", "Cyprus", None, False, "OTHER"),
)

# (unit, unit_name, country, rating_type, period_id, begin_on, score, end_on)
ФАКТЫ: tuple[tuple[Any, ...], ...] = (
    ("rs1", "Белград-1", "RS", "rs", 2, date(2026, 9, 1), 90.0, date(2026, 9, 30)),
    ("ge1", "Тбилиси-1", "GE", "rs", 2, date(2026, 9, 1), 80.0, date(2026, 9, 30)),
    ("tr1", "Анталья-1", "TR", "rs", 2, date(2026, 9, 1), 70.0, date(2026, 9, 30)),
    ("rs1", "Белград-1", "RS", "rko", 5, date(2026, 9, 1), 96.0, date(2026, 9, 30)),
    ("rs1", "Белград-1", "RS", "rs", 1, date(2026, 8, 1), 80.0, date(2026, 8, 31)),
    ("ge1", "Тбилиси-1", "GE", "rs", 1, date(2026, 8, 1), 80.0, date(2026, 8, 31)),
    ("tr1", "Анталья-1", "TR", "rs", 1, date(2026, 8, 1), 75.0, date(2026, 8, 31)),
)


def _факты(
    *, countries: Sequence[str], begin: date, end: date, period_ids: Sequence[int] = ()
) -> Any:
    return [f for f in ФАКТЫ if f[2] in countries and f[5] <= end and (f[7] or f[5]) >= begin]


@pytest.fixture
def рейтинги(monkeypatch: pytest.MonkeyPatch) -> None:
    """Слой чтения рейтингов и карт подменён фактами выше; база не нужна."""
    monkeypatch.setattr(read, "countries", lambda: СТРАНЫ)
    monkeypatch.setattr(read, "rs_periods", lambda: ())
    monkeypatch.setattr(read, "score_facts", _факты)
    # Остальное, что читает `report.build` для полной страницы, — пустое.
    monkeypatch.setattr(
        read, "settings", lambda: {"top_threshold": 85.0, "risk_threshold": 80.0, "risk_periods": 3}
    )
    monkeypatch.setattr(read, "hard_rules", lambda: ())
    monkeypatch.setattr(read, "rko_violation_facts", lambda **_: ([], {}))
    monkeypatch.setattr(read, "rs_remark_facts", lambda **_: ([], {}))
    monkeypatch.setattr(read, "last_period_ids", lambda *_, **__: ())
    monkeypatch.setattr(read, "last_loaded", lambda: {})
    monkeypatch.setattr(
        maps_store,
        "latest",
        lambda countries, until=None: tuple(
            maps_store.LatestRating(
                c, 2, 4.5 if until and until.month == 9 else 4.4, 100, date(2026, 9, 30)
            )
            for c in countries
            if until is None or until.month in (8, 9)
        ),
    )
    monkeypatch.setattr(
        agg_store,
        "latest",
        lambda countries, until=None: tuple(
            agg_store.LatestRating(c, "wolt", c + "-1", 9.0, 10, 50, date(2026, 9, 30))
            for c in countries
        ),
    )


def _экран(country: str = "") -> report.Summary:
    """То, что считает страница «Рейтинги» для того же среза и периода."""
    args = {"from": "2026-09-01", "to": "2026-09-30"}
    if country:
        args |= {"group": "country", "value": country}
    selection, _ = report.select(args, today=СЕГОДНЯ)
    return report.build(selection)


def test_числа_блока_совпадают_со_страницей_рейтингов(рейтинги: None) -> None:
    # Act
    итог = block.load(scope=None, country="", period=СЕНТЯБРЬ, today=СЕГОДНЯ)
    экран = _экран()

    # Assert — те же значения и то же движение, что в строках сводки «Рейтингов».
    assert [c.key for c in итог.columns] == ["CEE", "OTHER"]
    assert [(c.rs, c.rs_delta, c.rko, c.rko_delta) for c in итог.columns] == [
        (g.rs, g.rs_delta, g.rko, g.rko_delta) for g in экран.groups
    ]
    # И руками: CEE = среднее средних пиццерий (90 и 80), в августе — 80; OTHER — 70 и 75.
    cee, other = итог.columns
    assert (cee.rs, cee.rs_delta, cee.rko) == (85.0, 5.0, 96.0)
    assert (other.rs, other.rs_delta, other.rko) == (70.0, -5.0, None)


def test_выбранная_страна_даёт_одну_колонку_её_числами(рейтинги: None) -> None:
    # Act
    итог = block.load(scope=None, country="RS", period=СЕНТЯБРЬ, today=СЕГОДНЯ)
    экран = _экран("RS")

    # Assert
    assert len(итог.columns) == 1
    колонка = итог.columns[0]
    assert (колонка.key, колонка.is_cluster) == ("RS", False)
    assert (колонка.rs, колонка.rs_delta) == (экран.groups[0].rs, экран.groups[0].rs_delta)
    assert колонка.rs == 90.0
    assert dict(итог.link)["group"] == "country" and dict(итог.link)["value"] == "RS"


def test_колонка_без_стран_охвата_не_показывается(рейтинги: None) -> None:
    """Партнёр одной страны CEE: колонки «Другие страны» у него нет."""
    # Act
    итог = block.load(scope=("GE",), country="", period=СЕНТЯБРЬ, today=СЕГОДНЯ)

    # Assert
    assert [c.key for c in итог.columns] == ["CEE"]
    assert итог.columns[0].rs == 80.0  # только его страна, а не весь CEE


def test_страна_вне_рейтингов_не_подменяется_чужой(рейтинги: None) -> None:
    """Кипр не в IMF: `select` подставил бы первую страну, а блок покажет пустоту."""
    итог = block.load(scope=None, country="CY", period=СЕНТЯБРЬ, today=СЕГОДНЯ)

    assert итог.columns == () and not итог.failed


def test_карты_берутся_теми_же_оценками_с_движением(рейтинги: None) -> None:
    итог = block.load(scope=None, country="", period=СЕНТЯБРЬ, today=СЕГОДНЯ)

    google = next(m for m in итог.columns[0].maps if m.provider == 2)
    assert (google.avg, google.delta) == (4.5, 0.1)  # сентябрь 4.5 против августа 4.4


def test_отказ_чтения_рейтингов_называется(рейтинги: None, monkeypatch: pytest.MonkeyPatch) -> None:
    def отказ() -> tuple[CountryRow, ...]:
        raise RatingsError("нет связи")

    monkeypatch.setattr(read, "countries", отказ)

    итог = block.load(scope=None, country="", period=СЕНТЯБРЬ, today=СЕГОДНЯ)

    assert итог.failed and итог.columns == ()


def test_отказ_карт_не_убирает_рейтинги(рейтинги: None, monkeypatch: pytest.MonkeyPatch) -> None:
    def отказ(*_: object, **__: object) -> tuple[Any, ...]:
        raise RatingsError("нет связи")

    monkeypatch.setattr(rmaps, "compare", отказ)

    итог = block.load(scope=None, country="", period=СЕНТЯБРЬ, today=СЕГОДНЯ)

    assert итог.maps_failed and len(итог.columns) == 2 and итог.columns[0].rs == 85.0


def test_всё_время_берёт_период_по_умолчанию_рейтингов(рейтинги: None) -> None:
    """У рейтингов «всего времени» нет: без границ в адрес не идут `from` и `to`."""
    итог = block.load(scope=None, country="", period=Period(None, None), today=СЕГОДНЯ)

    assert dict(итог.link) == {}


# ── показ на странице ─────────────────────────────────────────────────────


@pytest.fixture
def стенд(monkeypatch: pytest.MonkeyPatch) -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant="HQ")
    with собрать(tenant="HQ").test_client() as client:
        assert войти(client).status_code == 302
        monkeypatch.setattr(overview_data, "load", lambda **_: снимок())
        yield client


def _блок() -> block.Block:
    return block.Block(
        columns=(
            block.Column("CEE", True, 85.0, 5.0, 96.0, -1.5, (block.MapScore(2, 4.5, 0.1, 100),)),
            block.Column("OTHER", True, None, None, 70.0, None, ()),
        ),
        link=(("from", "2026-10-01"), ("to", "2026-10-31")),
    )


def test_страница_показывает_блок_по_двум_кластерам(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    monkeypatch.setattr(block, "load", lambda **_: _блок())

    # Act
    страница = стенд.get("/overview").get_data(as_text=True)

    # Assert
    assert t("home.rb.rs", "ru") in страница and t("home.rb.rko", "ru") in страница
    assert t("home.rb.maps", "ru") in страница
    assert ">CEE<" in страница and "Остальные страны" in страница
    assert "85.0" in страница and "96.0" in страница and "4.50" in страница
    assert "▼-1.5" in страница and "▲+5.0" in страница
    assert 'href="/ratings?lang=ru&amp;from=2026-10-01&amp;to=2026-10-31"' in страница


def test_страница_без_данных_ставит_прочерки_и_работает_по_английски(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(block, "load", lambda **_: _блок())

    страница = стенд.get("/overview?lang=en").get_data(as_text=True)

    assert "Standards · RS" in страница and "Other countries" in страница


def test_страница_называет_отказ_рейтингов(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(block, "load", lambda **_: block.Block(failed=True))

    страница = стенд.get("/overview").get_data(as_text=True)

    assert t("home.rb.failed", "ru") in страница


def test_страница_передаёт_блоку_страну_и_период(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    спросили: dict[str, object] = {}
    monkeypatch.setattr(block, "load", lambda **kw: спросили.update(kw) or block.Block())
    monkeypatch.setattr(overview_data, "load", lambda **_: снимок(countries=(("RS", 3), ("GE", 2))))

    стенд.get("/overview?country=RS&from=2026-09-01&to=2026-09-30")

    assert спросили["country"] == "RS"
    assert спросили["period"] == СЕНТЯБРЬ


def test_агрегаторы_в_колонке_кластера_в_родной_шкале(рейтинги: None) -> None:
    """D557: в блоке кластеров — и агрегаторы, тем же подсчётом, что на «Рейтингах»."""
    итог = block.load(scope=None, country="", period=СЕНТЯБРЬ, today=СЕГОДНЯ)

    assert not итог.aggs_failed
    assert [(a.code, a.avg, a.scale) for a in итог.columns[0].aggs] == [("wolt", 9.0, 10)]


def test_отказ_агрегаторов_не_убирает_рейтинги(
    рейтинги: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    def отказ(*_: object, **__: object) -> tuple[Any, ...]:
        raise RatingsError("нет связи")

    monkeypatch.setattr(agg_store, "latest", отказ)

    итог = block.load(scope=None, country="", period=СЕНТЯБРЬ, today=СЕГОДНЯ)

    assert итог.aggs_failed and итог.columns[0].rs == 85.0 and итог.columns[0].aggs == ()
