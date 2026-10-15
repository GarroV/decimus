"""Экран «Страна» у партнёра (D508): тот же экран пиццерии, но строго в пределах его стран.

Граница доступа — ядро: партнёр читает только страны своего пространства
(`space_countries`), чужой код страны в адресе отвечает тем же 404, что и
несуществующий. База не нужна: охват и чтение подменены на границе модулей, а
тест следит, что до чтения чужой страны дело не доходит.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import date

import pytest
from flask.testing import FlaskClient
from test_web_overview import снимок, строка
from web_harness import войти, подменить_двери, собрать

from src.db import directory, unit_profiles
from src.db.reach import Reach
from src.web import country as cn
from src.web import country_page, country_summary, country_units, prescriptions
from src.web import overview as ov

ПАРТНЁР = "GE"


def _охват(*страны: str) -> Callable[[str], Reach]:
    return lambda tenant: Reach(tenant=tenant, tenants=None, countries=страны)


def _вид(code: str = "GE") -> cn.CountryView:
    первая = строка("Батуми-1", 90.0, "B")
    точка = ov.PointRow(
        unit="Батуми-1",
        city="batumi",
        country=code,
        inspection_id=первая.id,
        when=первая.inspection_date,
        grade="B",
        pct=90.0,
        delta=None,
        worst_zone_ru="",
        worst_zone_en="",
        critical=0,
    )
    вид = replace(
        снимок(inspections=(первая,)),
        unit_ids={"Батуми-1": "u-1"},
        points=(точка,),
        countries=((code, 1),),
    )
    return cn.CountryView(
        code=code, snapshot=вид, unit_id="u-1", unit_name="Батуми-1", history=вид.inspections
    )


def _строка() -> country_units.UnitRow:
    return country_units.UnitRow(
        key="u-1",
        name="Батуми-1",
        unit_id="u-1",
        stage="open",
        city="batumi",
        partner="ООО Ромашка",
        address="ул. Руставели, 1",
        opened=date(2024, 5, 1),
        status="Работает",
    )


@pytest.fixture
def чтения(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[str]]:
    """Подмена чтения базы; пишет, какие страны экран пошёл читать."""
    читали: dict[str, list[str]] = {"load": [], "profiles": []}

    def load(**kw: object) -> cn.CountryView:
        читали["load"].append(str(kw["code"]))
        return _вид(str(kw["code"]))

    def профили(code: str) -> tuple[()]:
        читали["profiles"].append(code)
        return ()

    monkeypatch.setattr(cn, "load", load)
    monkeypatch.setattr(unit_profiles, "by_country", профили)
    monkeypatch.setattr(country_summary, "developers_of", lambda _c: ({"Иван": ("GE",)}, {}, False))
    monkeypatch.setattr(
        country_units, "load", lambda **_: country_units.UnitsData(rows=(_строка(),))
    )
    monkeypatch.setattr(country_units, "history", lambda **kw: kw["fallback"])
    monkeypatch.setattr(
        country_page,
        "_country_plans",
        lambda _код: {
            "plans": (), "plans_known": True, "plans_act_path": "/plans",
            "plans_act_country": False,
        },
    )  # fmt: skip
    monkeypatch.setattr(
        prescriptions,
        "country_block",
        lambda _код: {
            "rx_rows": (), "rx_known": True, "rx_hq_path": "/actions/prescriptions",
            "rx_partner_path": "/prescriptions", "rx_act_hq": False,
        },
    )  # fmt: skip
    return читали


def _партнёр(
    monkeypatch: pytest.MonkeyPatch, *страны: str, role: str = "admin"
) -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant=ПАРТНЁР, role=role)
    monkeypatch.setattr("src.web.auth.reach_of", _охват(*страны))
    monkeypatch.setattr(cn, "countries", lambda **_: tuple((c, 1) for c in страны))
    with собрать(tenant=ПАРТНЁР).test_client() as client:
        assert войти(client).status_code == 302
        yield client


@pytest.fixture
def партнёр(monkeypatch: pytest.MonkeyPatch, чтения: dict[str, list[str]]) -> Iterator[FlaskClient]:
    """Партнёр с одной страной — GE."""
    yield from _партнёр(monkeypatch, "GE")


@pytest.fixture
def партнёр_двух_стран(
    monkeypatch: pytest.MonkeyPatch, чтения: dict[str, list[str]]
) -> Iterator[FlaskClient]:
    yield from _партнёр(monkeypatch, "GE", "AM")


def test_партнёр_видит_экран_своей_страны_со_списком_проверок(партнёр: FlaskClient) -> None:
    ответ = партнёр.get("/country/GE?unit=u-1")
    assert ответ.status_code == 200
    страница = ответ.get_data(as_text=True)
    assert "Батуми-1" in страница and "cn-uline" in страница
    # Панель пиццерии: сведения и история проверок, проверка раскрывается в свой разбор.
    assert "data-drawer" in страница and "ООО Ромашка" in страница
    assert f"/inspections/{_вид().snapshot.inspections[0].id}" in страница


def test_у_партнёра_нет_выбора_страны_и_девелопера(партнёр: FlaskClient) -> None:
    страница = партнёр.get("/country/GE").get_data(as_text=True)
    assert 'class="pick"' not in страница and "cn-filters" not in страница
    # Девелопер — понятие УК: ни выбора, ни строки в шапке, даже если справочник их отдаёт.
    assert "Иван" not in страница
    # Старая карточка точки партнёру не нужна: путь к пиццерии один.
    assert "/units/u-1" not in партнёр.get("/country/GE?unit=u-1").get_data(as_text=True)


def test_партнёр_с_несколькими_странами_выбирает_только_из_своих(
    партнёр_двух_стран: FlaskClient,
) -> None:
    страница = партнёр_двух_стран.get("/country/GE").get_data(as_text=True)
    колонка = страница.split("</aside>", 1)[0]
    assert колонка.count('class="pick"') == 1  # только страна, без девелопера
    assert "/country/AM" in страница


@pytest.mark.parametrize("адрес", ["/country/RS", "/country/rs?unit=u-9", "/country/%3Cs%3E"])
def test_чужая_страна_партнёру_404_и_не_читается(
    партнёр: FlaskClient, чтения: dict[str, list[str]], адрес: str
) -> None:
    ответ = партнёр.get(адрес)
    assert ответ.status_code == 404
    # До чтения чужой страны дело не дошло: ни снимка, ни свода пиццерий.
    assert чтения == {"load": [], "profiles": []}


def test_чужая_страна_отвечает_как_несуществующий_адрес(партнёр: FlaskClient) -> None:
    нет = партнёр.get("/nothing-here-at-all")
    ответ = партнёр.get("/country/RS")
    assert ответ.status_code == 404
    assert ответ.data.replace(b"/country/RS", b"") == нет.data.replace(b"/nothing-here-at-all", b"")


def test_вход_без_страны_ведёт_в_единственную_страну_партнёра(партнёр: FlaskClient) -> None:
    ответ = партнёр.get("/country?dev=Иван")
    assert ответ.status_code == 200  # `dev` у партнёра игнорируется, а не сводит страны
    assert 'class="pick"' not in ответ.get_data(as_text=True)
    assert партнёр.get("/country").headers["Location"].endswith("/country/GE")


def test_заведение_пиццерии_под_страной_партнёру_закрыто(партнёр: FlaskClient) -> None:
    assert партнёр.get("/country/GE/units/new").status_code == 404
    страница = партнёр.get("/country/GE").get_data(as_text=True)
    assert "/units/new" not in страница


def test_старая_карточка_точки_ведёт_партнёра_на_экран_страны(
    партнёр: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    точки = [
        directory.Unit(
            id="u-1", name="Батуми-1", code=None, aliases=(), country="GE", city="batumi"
        )
    ]
    monkeypatch.setattr(directory, "list_units", lambda **_: точки)
    ответ = партнёр.get("/units/u-1?lang=en")
    assert ответ.status_code == 302
    assert ответ.headers["Location"].split("?")[0].endswith("/country/GE")
    assert "unit=u-1" in ответ.headers["Location"] and "lang=en" in ответ.headers["Location"]
    # Точка вне охвата справочник партнёру не отдаёт — 404, как у несуществующей.
    monkeypatch.setattr(directory, "list_units", lambda **_: [])
    assert партнёр.get("/units/u-7").status_code == 404


def test_у_уК_ничего_не_изменилось(
    monkeypatch: pytest.MonkeyPatch, чтения: dict[str, list[str]]
) -> None:
    """УК: выбор девелопера и страны на месте, чужие страны открыты, карточка точки жива."""
    подменить_двери(monkeypatch, tenant="HQ", role="admin")
    monkeypatch.setattr("src.web.auth.reach_of", lambda t: Reach(t, None, None))
    monkeypatch.setattr(cn, "countries", lambda **_: (("GE", 1), ("RS", 1)))
    with собрать(tenant="HQ").test_client() as client:
        assert войти(client).status_code == 302
        страница = client.get("/country/GE?unit=u-1").get_data(as_text=True)
        assert страница.split("</aside>", 1)[0].count('class="pick"') == 2  # девелопер и страна
        assert "/units/u-1" in страница
        assert client.get("/country/RS").status_code == 200
