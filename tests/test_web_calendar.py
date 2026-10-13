"""«Календарь» (D477): проверки по дням месяца, без стрелок и без списка «Где нужно проверить».

Сторожится: проверка стоит в клетке своего дня, больше трёх в дне уходят в «+N»,
ждущая приёмки отличима, период шире месяца даёт несколько сеток, период
календаря не листается стрелками, скрытый список не читается и не рисуется.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pytest
from flask.testing import FlaskClient
from test_web_app import ТЕНАНТ, шапка
from web_harness import войти, подменить_двери, собрать

from src.web import calendar_grid, to_inspect
from src.web import inspections as data
from src.web.registry_period import Period
from src.web.texts import t

СЕНТЯБРЬ = Period(date(2026, 9, 1), date(2026, 9, 30))
СЕГОДНЯ = date(2026, 9, 15)


def _день(месяцы: tuple[calendar_grid.Month, ...], число: int) -> calendar_grid.Day:
    return next(d for w in месяцы[0].weeks for d in w if d.in_month and d.day.day == число)


def test_проверка_стоит_в_клетке_своего_дня() -> None:
    # Arrange
    строки = (шапка(id="a", unit_name="Белград-1", inspection_date=date(2026, 9, 18)),)

    # Act
    месяцы = calendar_grid.build(СЕНТЯБРЬ, строки, today=СЕГОДНЯ)

    # Assert
    assert [c.unit for c in _день(месяцы, 18).chips] == ["Белград-1"]
    assert not _день(месяцы, 17).chips and not _день(месяцы, 19).chips
    assert месяцы[0].count == 1


def test_неделя_с_понедельника_и_сегодня_отмечено() -> None:
    месяцы = calendar_grid.build(СЕНТЯБРЬ, (), today=СЕГОДНЯ)

    первая = месяцы[0].weeks[0]
    assert len(первая) == 7 and первая[0].day.weekday() == 0  # 1 сентября 2026 — вторник
    assert next(d.day for d in первая if d.in_month) == date(2026, 9, 1)
    assert [d.day for w in месяцы[0].weeks for d in w if d.is_today] == [СЕГОДНЯ]


def test_больше_трёх_в_дне_остаток_числом() -> None:
    строки = tuple(
        шапка(id=str(n), unit_name=f"П-{n}", inspection_date=date(2026, 9, 10)) for n in range(5)
    )

    день = _день(calendar_grid.build(СЕНТЯБРЬ, строки, today=СЕГОДНЯ), 10)

    assert len(день.chips) == calendar_grid.MAX_CHIPS and день.more == 2 and день.total == 5


def test_ждущая_приёмки_отличима_и_идёт_после_принятых() -> None:
    строки = (
        шапка(id="r", unit_name="А", inspection_date=date(2026, 9, 10), on_review=True),
        шапка(id="p", unit_name="Я", inspection_date=date(2026, 9, 10)),
    )

    день = _день(calendar_grid.build(СЕНТЯБРЬ, строки, today=СЕГОДНЯ), 10)

    assert [(c.id, c.on_review) for c in день.chips] == [("p", False), ("r", True)]


def test_проверка_вне_периода_в_сетку_не_попадает() -> None:
    строки = (шапка(inspection_date=date(2026, 8, 31)),)

    месяцы = calendar_grid.build(СЕНТЯБРЬ, строки, today=СЕГОДНЯ)

    assert месяцы[0].count == 0


def test_период_шире_месяца_несколько_сеток_и_предел() -> None:
    три = calendar_grid.build(Period(date(2026, 8, 20), date(2026, 10, 5)), (), today=СЕГОДНЯ)
    длинный = calendar_grid.clamp(Period(date(2020, 1, 1), date(2026, 9, 30)))

    assert [m.first for m in три] == [date(2026, 8, 1), date(2026, 9, 1), date(2026, 10, 1)]
    assert len(calendar_grid.build(длинный, (), today=СЕГОДНЯ)) == calendar_grid.MAX_MONTHS


@pytest.fixture
def стенд(monkeypatch: pytest.MonkeyPatch) -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant=ТЕНАНТ)
    строки = (
        шапка(id="id-ok", unit_name="Белград-1", grade="A", inspection_date=date(2026, 9, 18)),
        шапка(id="id-ge", unit_name="Тбилиси-1", grade="C", inspection_date=date(2026, 9, 18)),
    )
    ждёт = (
        шапка(
            id="id-rev",
            unit_name="Ниш-1",
            grade="B",
            inspection_date=date(2026, 9, 21),
            on_review=True,
        ),
    )
    monkeypatch.setattr(data, "load_registry", lambda **_: data.Registry(строки, True, review=ждёт))
    monkeypatch.setattr(
        data,
        "load_geography",
        lambda **_: {"Белград-1": ("RS", ""), "Тбилиси-1": ("GE", ""), "Ниш-1": ("RS", "")},
    )
    with собрать(tenant=ТЕНАНТ).test_client() as client:
        assert войти(client).status_code == 302
        yield client


def test_экран_рисует_проверку_в_её_день_ссылкой_в_реестр(стенд: FlaskClient) -> None:
    страница = стенд.get("/calendar?from=2026-09-01&to=2026-09-30").get_data(as_text=True)

    assert "Белград-1" in страница and "inspection=id-ok" in страница
    assert "from=2026-09-18" in страница
    assert t("calendar.chip.review", "ru") in страница and "Ниш-1" in страница


def test_экран_без_стрелок_периода_и_без_списка_где_проверить(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D477: стрелок ← → нет; блок «Где нужно проверить» не рисуется и не читается."""
    читали: list[object] = []
    monkeypatch.setattr(to_inspect, "load", lambda **kw: читали.append(kw) or to_inspect.Block())

    страница = стенд.get("/calendar?from=2026-09-01&to=2026-09-30").get_data(as_text=True)

    assert "speriod__arrow" not in страница
    assert t("registry.tocheck.title", "ru") not in страница
    assert t("calendar.tocheck.empty", "ru") not in страница
    assert not читали


def test_стрелки_у_других_экранов_остаются(стенд: FlaskClient) -> None:
    assert "speriod__arrow" in стенд.get("/inspections").get_data(as_text=True)


def test_страна_сужает_сетку(стенд: FlaskClient) -> None:
    страница = стенд.get("/calendar?from=2026-09-01&to=2026-09-30&country=GE").get_data(
        as_text=True
    )

    assert "Тбилиси-1" in страница and "Белград-1" not in страница and "Ниш-1" not in страница


def test_по_умолчанию_текущий_месяц_и_открытый_период_не_роняет(стенд: FlaskClient) -> None:
    сегодня = date.today()
    заголовок = f"{t(f'registry.month.{сегодня.month}', 'ru')} {сегодня.year}"

    assert заголовок in стенд.get("/calendar").get_data(as_text=True)
    assert заголовок in стенд.get("/calendar?period=all").get_data(as_text=True)


def test_месяц_без_проверок_говорит_об_этом(стенд: FlaskClient) -> None:
    страница = стенд.get("/calendar?from=2026-01-01&to=2026-01-31").get_data(as_text=True)

    assert t("calendar.month.empty", "ru") in страница and "Белград-1" not in страница
