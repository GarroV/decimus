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

# Стенд подменяет `load` пустым блоком; страницам, что ходят в настоящий, он нужен целиком.
НАСТОЯЩАЯ_ЗАГРУЗКА = block.load

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


def _факты_пиццерии(countries: Sequence[str]) -> list[tuple[Any, ...]]:
    """Вторая пиццерия Сербии с РС 60 — худшая в стране."""
    if "RS" not in countries:
        return []
    return [("rs2", "Белград-2", "RS", "rs", 2, date(2026, 9, 1), 60.0, date(2026, 9, 30))]


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


@pytest.fixture
def по_пиццериям(monkeypatch: pytest.MonkeyPatch) -> None:
    """Оценки карт и агрегаторов отдельных пиццерий: у Белграда-1 есть всё, у Тбилиси — ничего."""
    monkeypatch.setattr(
        maps_store,
        "unit_scores",
        lambda provider, *, until: (
            {"rs1": (4.8 if until.month == 9 else 4.6, 40)} if provider == 2 else {}
        ),
    )
    monkeypatch.setattr(
        agg_store,
        "latest",
        lambda countries, until=None: tuple(
            agg_store.LatestRating(c, "wolt", "rs1", 9.5, 10, 20, date(2026, 9, 30))
            for c in countries
            if c == "RS"
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


def test_выбранная_страна_даёт_итог_её_числами(рейтинги: None) -> None:
    # Act
    итог = block.load(scope=None, country="RS", period=СЕНТЯБРЬ, today=СЕГОДНЯ)
    экран = _экран("RS")

    # Assert
    колонка = итог.columns[0]
    assert (колонка.is_total, колонка.is_cluster) == (True, False)
    assert (колонка.rs, колонка.rs_delta) == (экран.groups[0].rs, экран.groups[0].rs_delta)
    assert колонка.rs == 90.0
    assert dict(итог.link)["group"] == "country" and dict(итог.link)["value"] == "RS"


def test_кластер_разворачивается_итогом_и_странами(рейтинги: None) -> None:
    # Act
    итог = block.load(scope=None, country="", cluster="CEE", period=СЕНТЯБРЬ, today=СЕГОДНЯ)

    # Assert — итог кластера те же 85.0, что в строке «Рейтингов», и по колонке на страну.
    assert [(c.key, c.is_total) for c in итог.columns] == [
        (block.TOTAL, True),
        ("RS", False),
        ("GE", False),
    ]
    итого, сербия, грузия = итог.columns
    assert (итого.rs, итого.rs_delta) == (85.0, 5.0)
    assert (сербия.rs, сербия.rs_delta, сербия.rko) == (90.0, 10.0, 96.0)
    assert (грузия.rs, грузия.rko) == (80.0, None)
    assert dict(итог.link)["group"] == "cluster" and dict(итог.link)["value"] == "CEE"
    # Карты считаются по каждой стране отдельно, а не берутся с итога.
    assert all(c.map_of(2) is not None for c in итог.columns)


def test_страна_разворачивается_пиццериями_худшие_первыми(
    рейтинги: None, по_пиццериям: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — в Сербии две пиццерии: Белград-1 с РС 90 и Белград-2 с РС 60.
    monkeypatch.setattr(
        read,
        "score_facts",
        lambda **kw: [
            *_факты(**kw),
            *_факты_пиццерии(kw["countries"]),
        ],
    )

    # Act
    итог = block.load(scope=None, country="RS", period=СЕНТЯБРЬ, today=СЕГОДНЯ)

    # Assert
    assert [c.unit for c in итог.columns] == ["", "Белград-2", "Белград-1"]
    итого, худшая, лучшая = итог.columns
    assert итого.is_total and худшая.rs == 60.0 and лучшая.rs == 90.0
    # У Белграда-2 карт и агрегаторов нет — прочерки, а не нули и не чужие числа.
    assert [m.avg for m in худшая.maps] == [None, None] and худшая.aggs == ()
    google = лучшая.map_of(2)
    assert google is not None and (google.avg, google.delta) == (4.8, 0.2)
    wolt = лучшая.agg_of("wolt")
    assert wolt is not None and wolt.avg == 9.5


def test_порядок_пиццерий_идёт_за_сортировкой_экрана(
    рейтинги: None, по_пиццериям: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        read, "score_facts", lambda **kw: [*_факты(**kw), *_факты_пиццерии(kw["countries"])]
    )

    по_названию = block.load(scope=None, country="RS", period=СЕНТЯБРЬ, today=СЕГОДНЯ, sort="unit")
    по_дате = block.load(
        scope=None,
        country="RS",
        period=СЕНТЯБРЬ,
        today=СЕГОДНЯ,
        sort="date",
        inspected={"rs2": date(2026, 9, 28), "rs1": date(2026, 9, 3)},
    )

    assert [c.unit for c in по_названию.columns[1:]] == ["Белград-1", "Белград-2"]
    assert [c.unit for c in по_дате.columns[1:]] == ["Белград-2", "Белград-1"]


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
    assert ">РС<" in страница and ">РКО<" in страница
    assert "Стандарты · РС" not in страница and "Клиентский опыт" not in страница
    assert t("ratings.maps.provider.2", "ru") in страница
    assert ">CEE<" in страница and "Остальные страны" in страница
    assert "85.0" in страница and "96.0" in страница and "4.50" in страница
    assert "▼-1.5" in страница and "▲+5.0" in страница
    assert 'href="/ratings?lang=ru&amp;from=2026-10-01&amp;to=2026-10-31"' in страница


def test_страница_без_данных_ставит_прочерки_и_работает_по_английски(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(block, "load", lambda **_: _блок())

    страница = стенд.get("/overview?lang=en").get_data(as_text=True)

    assert ">RS<" in страница and ">CX<" in страница and "Other countries" in страница


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


def test_страница_с_кластером_показывает_колонку_на_страну_и_короткие_подписи(
    стенд: FlaskClient,
    рейтинги: None,
    по_пиццериям: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setattr(block, "load", НАСТОЯЩАЯ_ЗАГРУЗКА)

    # Act
    страница = стенд.get("/overview?cluster=CEE&from=2026-09-01&to=2026-09-30").get_data(
        as_text=True
    )
    таблица = страница[страница.index('class="hm-rb"') :]
    таблица = таблица[: таблица.index("</section>")]

    # Assert — итог и по колонке на страну; подписи строк короткие; прокрутка вбок внутри блока.
    assert 'style="--hm-rb-cols: 3"' in таблица
    assert ">Итого<" in таблица and "Сербия" in таблица and "Грузия" in таблица
    assert 'class="hm-rb__label">РС<' in таблица and 'class="hm-rb__label">РКО<' in таблица
    assert "data-rb-view" in страница


def test_страница_со_страной_показывает_колонку_на_пиццерию_со_ссылкой(
    стенд: FlaskClient,
    рейтинги: None,
    по_пиццериям: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setattr(block, "load", НАСТОЯЩАЯ_ЗАГРУЗКА)
    monkeypatch.setattr(
        read, "score_facts", lambda **kw: [*_факты(**kw), *_факты_пиццерии(kw["countries"])]
    )
    monkeypatch.setattr(
        overview_data,
        "load",
        lambda **_: снимок(
            countries=(("RS", 2), ("GE", 1)),
            unit_codes={"Белград-1": "rs1"},
            unit_ids={"Белград-1": "u-1"},
        ),
    )

    # Act
    страница = стенд.get("/overview?country=RS&from=2026-09-01&to=2026-09-30").get_data(
        as_text=True
    )
    таблица = страница[страница.index('class="hm-rb"') :]
    таблица = таблица[: таблица.index("</section>")]

    # Assert — итог, потом худшая пиццерия; у проверенной заголовок ведёт в «Страны».
    assert 'style="--hm-rb-cols: 3"' in таблица
    assert таблица.index("Белград-2") < таблица.index("Белград-1")
    assert "unit=u-1" in таблица
