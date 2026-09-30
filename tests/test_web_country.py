"""Экран «Страна»: пиццерии страны, раскрытие истории, фильтры в адресе."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace

import pytest
from flask.testing import FlaskClient
from test_web_app import ТЕНАНТ
from test_web_overview import снимок, строка
from web_harness import войти, подменить_двери, собрать

from src.web import app as app_mod
from src.web import country as cn


@pytest.fixture
def стенд(monkeypatch: pytest.MonkeyPatch) -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant=ТЕНАНТ)
    # Список стран шапки — справочник базы; экрану в этих тестах база не нужна.
    monkeypatch.setattr(app_mod.country_data, "countries", lambda **_: (("GE", 1),))
    with собрать(tenant=ТЕНАНТ).test_client() as client:
        assert войти(client).status_code == 302
        yield client


def данные() -> cn.CountryView:
    первая = строка("Батуми-1", 90.0, "B")
    return cn.CountryView(
        code="GE",
        snapshot=replace(
            снимок(inspections=(первая,)),
            unit_ids={"Батуми-1": "u-1"},
            points=(),
            countries=(("GE", 1),),
        ),
    )


def с_точкой(вид: cn.CountryView) -> cn.CountryView:
    """Тот же вид, но в таблице пиццерий есть строка Батуми-1.

    История раскрывается ПОД строкой точки: без строки раскрывать нечего.
    """
    последняя = вид.snapshot.inspections[0]
    точка = app_mod.overview_data.PointRow(
        unit="Батуми-1",
        city="batumi",
        country="GE",
        inspection_id=последняя.id,
        when=последняя.inspection_date,
        grade="B",
        pct=90.0,
        delta=None,
        worst_zone_ru="",
        worst_zone_en="",
        critical=0,
    )
    return replace(вид, snapshot=replace(вид.snapshot, points=(точка,)))


def открыть(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch, вид: cn.CountryView, адрес: str
) -> str:
    monkeypatch.setattr(app_mod.country_data, "load", lambda **_: вид)
    ответ = client.get(адрес)
    assert ответ.status_code == 200, ответ.status_code
    return ответ.get_data(as_text=True)


def test_экран_страны_называет_страну_словом(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    страница = открыть(стенд, monkeypatch, данные(), "/country/GE")
    assert "Грузия" in страница or "Georgia" in страница


def test_мусорный_код_страны_не_роняет_экран(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    видели: list[str] = []

    def load(**kw: object) -> cn.CountryView:
        видели.append(str(kw["code"]))
        return replace(данные(), code=str(kw["code"]))

    monkeypatch.setattr(app_mod.country_data, "load", load)
    assert стенд.get("/country/ge").status_code == 200
    assert стенд.get("/country/%3Cs%3E").status_code == 200
    assert видели == ["GE", ""]


def test_раскрытая_точка_показывает_историю_и_карточку(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    вид = с_точкой(данные())
    вид = replace(вид, unit_id="u-1", unit_name="Батуми-1", history=вид.snapshot.inspections)
    страница = открыть(стенд, monkeypatch, вид, "/country/GE?unit=u-1")
    assert 'id="unit-u-1"' in страница
    assert 'class="ov-history"' in страница
    assert "/units/u-1" in страница
    assert f"/inspections/{вид.history[0].id}" in страница


def test_ссылки_строк_сохраняют_фильтры_и_язык(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    вид = с_точкой(данные())
    страница = открыть(стенд, monkeypatch, вид, "/country/GE?period=d90&grade=B&lang=en")
    assert "unit=u-1" in страница
    строка_ссылки = next(ч for ч in страница.split('"') if "unit=u-1" in ч)
    assert (
        "period=d90" in строка_ссылки and "grade=B" in строка_ссылки and "lang=en" in строка_ссылки
    )


def test_пустая_страна_говорит_словами(стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch) -> None:
    вид = replace(
        данные(),
        snapshot=replace(данные().snapshot, points=(), inspections=(), systemic=(), zone_losses=()),
    )
    страница = открыть(стенд, monkeypatch, вид, "/country/GE")
    assert "проверок нет" in страница or "No inspections" in страница


def test_список_стран_с_одной_страной_сразу_ведёт_в_неё(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_mod.country_data, "countries", lambda **_: (("GE", 3),))
    ответ = стенд.get("/country")
    assert ответ.status_code == 302
    assert ответ.headers["Location"].endswith("/country/GE")


def test_список_стран_показывает_все(стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_mod.country_data, "countries", lambda **_: (("GE", 3), ("RS", 2)))
    страница = открыть(стенд, monkeypatch, данные(), "/country")
    assert "/country/GE" in страница and "/country/RS" in страница


def test_смена_языка_оставляет_страну_и_раскрытую_точку(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    вид = с_точкой(данные())
    вид = replace(вид, unit_id="u-1", unit_name="Батуми-1", history=вид.snapshot.inspections)
    страница = открыть(стенд, monkeypatch, вид, "/country/GE?unit=u-1&period=d90")
    assert 'action="/country/GE"' in страница
    assert '<input type="hidden" name="unit" value="u-1">' in страница
    assert '<input type="hidden" name="period" value="d90">' in страница


def test_на_экране_страны_слева_колонка_всех_стран_и_выбранная_отмечена(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Раскладка как у «Методики»: слева страны, справа выбранная (владелец 30.09.2026)."""
    monkeypatch.setattr(app_mod.country_data, "countries", lambda **_: (("GE", 3), ("RS", 2)))
    страница = открыть(стенд, monkeypatch, данные(), "/country/GE")
    колонка = страница.split('class="mx-rail', 1)[1].split("</aside>", 1)[0]
    assert "/country/GE" in колонка and "/country/RS" in колонка
    отмеченная = колонка.split('aria-current="page"', 1)[0].rsplit("<a ", 1)[1]
    assert "/country/GE" in отмеченная
    # Выбор страны живёт в колонке — чипа «Страна» в отборе больше нет.
    assert "Все страны" not in страница.split('class="mx-main', 1)[1]


def test_без_страны_в_адресе_справа_первая_страна_а_не_пустота(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Рабочая зона не пустует, как в «Методике» (владелец 30.09.2026, скриншот
    пустого «Выберите страну»): справа первая страна колонки, экран помечен
    выбором — на телефоне первым идёт список стран."""
    monkeypatch.setattr(app_mod.country_data, "countries", lambda **_: (("GE", 3), ("RS", 2)))
    просили: list[str] = []

    def load(**kw: object) -> cn.CountryView:
        просили.append(str(kw["code"]))
        return данные()

    monkeypatch.setattr(app_mod.country_data, "load", load)
    ответ = стенд.get("/country")
    assert ответ.status_code == 200, ответ.status_code
    страница = ответ.get_data(as_text=True)
    assert просили == ["GE"]
    assert "Выберите страну" not in страница and "Choose a country" not in страница
    assert "mx-shell--pick" in страница
    assert "mx-shell--pick" not in стенд.get("/country/GE").get_data(as_text=True)
