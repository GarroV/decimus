"""«Календарь» (D497): сетка месяца с проверками по дням.

Сторожится: неделя с понедельника и полные недели, проверка попадает в свой
день, клетка не растёт сверх предела, длинный период не рисует год, экран
читает свой период и ведёт строку в карточку на «Проверках».
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pytest
from flask import render_template_string
from flask.testing import FlaskClient
from test_web_app import ТЕНАНТ, шапка
from web_harness import войти, подменить_двери, собрать

from src.web import calendar_view, registry_period
from src.web import inspections as data
from src.web.texts import t

СЕГОДНЯ = date(2026, 10, 15)


def test_неделя_с_понедельника_и_полные_недели() -> None:
    месяц = calendar_view.month_grid(date(2026, 10, 1), (), СЕГОДНЯ)

    assert месяц.weeks[0][0].day == date(2026, 9, 28)  # 1 октября 2026 — четверг
    assert месяц.weeks[-1][-1].day == date(2026, 11, 1)
    assert not месяц.weeks[0][0].in_month and месяц.weeks[0][3].in_month
    assert all(len(неделя) == 7 for неделя in месяц.weeks)
    assert [d.day for d in месяц.weeks[2] if d.today] == [СЕГОДНЯ]


def test_проверка_в_своём_дне_а_чужой_месяц_не_считается() -> None:
    строки = (
        шапка(unit_name="Б", inspection_date=date(2026, 10, 7)),
        шапка(unit_name="А", inspection_date=date(2026, 10, 7)),
        шапка(unit_name="В", inspection_date=date(2026, 9, 30)),
    )

    месяц = calendar_view.month_grid(date(2026, 10, 1), строки, СЕГОДНЯ)

    дни = {d.day: d for неделя in месяц.weeks for d in неделя}
    assert [r.unit_name for r in дни[date(2026, 10, 7)].rows] == ["А", "Б"]
    assert месяц.total == 2


def test_клетка_печатает_предел_и_считает_остаток() -> None:
    строки = tuple(шапка(unit_name=f"П-{n}", inspection_date=date(2026, 10, 2)) for n in range(5))

    день = next(
        d
        for неделя in calendar_view.month_grid(date(2026, 10, 1), строки, СЕГОДНЯ).weeks
        for d in неделя
        if d.day == date(2026, 10, 2)
    )

    assert len(день.shown) == calendar_view.DAY_ROWS and день.more == 5 - calendar_view.DAY_ROWS


def test_длинный_период_не_рисует_год() -> None:
    месяцы = calendar_view.months_between(date(2026, 1, 1), date(2026, 12, 31), СЕГОДНЯ)

    assert месяцы == (date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1))
    assert calendar_view.months_between(None, None, СЕГОДНЯ) == (date(2026, 10, 1),)
    assert calendar_view.month_end(date(2026, 2, 1)) == date(2026, 2, 28)


@pytest.fixture
def спросили(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    журнал: list[dict[str, object]] = []

    def читать(**kw: object) -> tuple[object, ...]:
        журнал.append(kw)
        return (шапка(unit_name="Белград-1", inspection_date=date(2026, 9, 10)),)

    monkeypatch.setattr(data, "load_dated", читать)
    return журнал


@pytest.fixture
def стенд(monkeypatch: pytest.MonkeyPatch, спросили: object) -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant=ТЕНАНТ)
    with собрать(tenant=ТЕНАНТ).test_client() as client:
        assert войти(client).status_code == 302
        yield client


def test_экран_читает_свой_период_и_ведёт_в_карточку(
    стенд: FlaskClient, спросили: list[dict[str, object]]
) -> None:
    страница = стенд.get("/calendar?from=2026-09-01&to=2026-09-30").get_data(as_text=True)

    assert (спросили[0]["date_from"], спросили[0]["date_to"]) == (
        date(2026, 9, 1),
        date(2026, 9, 30),
    )
    assert "Белград-1" in страница and "inspection=" in страница
    assert "Где нужно проверить" not in страница  # D497: список снят


def test_без_дат_текущий_месяц(стенд: FlaskClient, спросили: list[dict[str, object]]) -> None:
    стенд.get("/calendar")

    начало = спросили[0]["date_from"]
    assert isinstance(начало, date) and начало.day == 1


def test_период_со_стрелками_и_месяцами_в_меню(стенд: FlaskClient) -> None:
    """D555: стрелки ← → листают месяц; в меню — прошлый, этот и следующий, без «всё время»."""
    страница = стенд.get("/calendar?from=2026-09-01&to=2026-09-30").get_data(as_text=True)

    assert "speriod__arrow" in страница
    assert "from=2026-08-01" in страница and "from=2026-10-01" in страница
    assert t("calendar.period.next_month", "ru") in страница
    assert t("registry.period.all", "ru") not in страница


def test_стрелки_у_других_экранов_остаются() -> None:
    """Макрос периода по умолчанию рисует стрелки; без них — только по `arrows=False`."""
    app = собрать(tenant=ТЕНАНТ)
    вызов = (
        '{{% from "_period.html" import period_picker with context %}}'
        '{{{{ period_picker(p, "x", "/a", "/b", (), "/", {{}}{}) }}}}'
    )
    p = registry_period.read({}, today=СЕГОДНЯ)

    with app.test_request_context("/"):
        со_стрелками = render_template_string(вызов.format(""), p=p)
        без_стрелок = render_template_string(вызов.format(", arrows=False"), p=p)

    assert "speriod__arrow" in со_стрелками
    assert "speriod__arrow" not in без_стрелок


def test_календарь_по_английски(стенд: FlaskClient) -> None:
    страница = стенд.get("/calendar?lang=en&from=2026-09-01&to=2026-09-30").get_data(as_text=True)

    assert "Mon" in страница and "inspections: 1" in страница
