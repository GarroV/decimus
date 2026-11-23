"""Экран «Страна» (D467): шапка, сегменты, панель пиццерии, отбор «Девелопер»."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from datetime import date

import pytest
from flask.testing import FlaskClient
from test_web_app import ТЕНАНТ
from test_web_overview import снимок, строка
from web_harness import войти, подменить_двери, собрать

from src.db.directory import Unit
from src.web import country as cn
from src.web import country_page, country_summary, country_units, prescriptions
from src.web import overview as ov


@pytest.fixture
def стенд(monkeypatch: pytest.MonkeyPatch) -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant=ТЕНАНТ)
    # Список стран, девелоперы, таблица пиццерий, планы и предписания — база;
    # экрану в этих тестах она не нужна, отдельные наборы подменяют своё сами.
    monkeypatch.setattr(cn, "countries", lambda **_: (("GE", 1),))
    monkeypatch.setattr(country_summary, "developers_of", lambda _codes: ({}, {}, False))
    monkeypatch.setattr(cn, "rail_stats", lambda **_: {})
    monkeypatch.setattr(country_units, "load", lambda **_: country_units.UnitsData())
    monkeypatch.setattr(country_units, "history", lambda **kw: kw["fallback"])
    monkeypatch.setattr(
        country_page,
        "_country_plans",
        lambda _код: {
            "plans": (), "plans_known": True, "plans_act_path": "/actions",
            "plans_act_country": True,
        },
    )  # fmt: skip
    monkeypatch.setattr(
        prescriptions,
        "country_block",
        lambda _код: {
            "rx_rows": (), "rx_known": True, "rx_hq_path": "/actions/prescriptions",
            "rx_partner_path": "/orders", "rx_act_hq": True,
        },
    )  # fmt: skip
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
    точка = ov.PointRow(
        unit="Батуми-1",
        city="batumi",
        country="GE",
        inspection_id=последняя.id,
        when=последняя.inspection_date,
        grade="B",
        pct=90.0,
        delta=None,
        worst_process_ru="",
        worst_process_en="",
        critical=0,
    )
    return replace(вид, snapshot=replace(вид.snapshot, points=(точка,)))


def открыть(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch, вид: cn.CountryView, адрес: str
) -> str:
    monkeypatch.setattr(cn, "load", lambda **_: вид)
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

    monkeypatch.setattr(cn, "load", load)
    assert стенд.get("/country/ge").status_code == 200
    assert стенд.get("/country/%3Cs%3E").status_code == 200
    assert видели == ["GE", ""]


def строка_таблицы(**поля: object) -> country_units.UnitRow:
    основа: dict[str, object] = {
        "key": "u-1", "name": "Батуми-1", "unit_id": "u-1", "stage": "open", "city": "batumi",
        "partner": "ООО Ромашка", "address": "ул. Руставели, 1", "opened": date(2024, 5, 1),
        "status": "Работает",
    }  # fmt: skip
    основа.update(поля)
    return country_units.UnitRow(**основа)  # type: ignore[arg-type]


def с_таблицей(monkeypatch: pytest.MonkeyPatch, *строки: country_units.UnitRow) -> None:
    monkeypatch.setattr(
        country_units, "load", lambda **_: country_units.UnitsData(rows=tuple(строки))
    )


def test_страна_и_пиццерия_выбираются_фильтрами_без_второй_колонки(стенд, monkeypatch):
    с_таблицей(monkeypatch, строка_таблицы())
    monkeypatch.setattr(
        cn,
        "rail_stats",
        lambda **kw: pytest.fail("Filter must not aggregate every country's history"),
    )
    страница = открыть(стенд, monkeypatch, с_точкой(данные()), "/country/GE")
    assert 'class="pk-rail"' not in страница
    assert 'aria-label="Страна"' in страница and 'aria-label="Пиццерия"' in страница
    assert "Батуми-1" in страница and "pk-tiles" in страница


def test_закрытая_пиццерия_доступна_в_фильтре_с_пометкой(стенд, monkeypatch):
    с_таблицей(
        monkeypatch,
        строка_таблицы(),
        строка_таблицы(key="u-2", name="Тбилиси-2", unit_id="u-2", stage="closed"),
    )
    страница = открыть(стенд, monkeypatch, с_точкой(данные()), "/country/GE")
    assert "Тбилиси-2 ·" in страница and "Батуми-1" in страница
    assert "Руставели" not in страница


def test_выбранная_точка_показывает_справа_сведения_и_свои_проверки(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    вид = с_точкой(данные())
    вид = replace(вид, unit_id="u-1", unit_name="Батуми-1", history=вид.snapshot.inspections)
    с_таблицей(monkeypatch, строка_таблицы())
    страница = открыть(стенд, monkeypatch, вид, "/country/GE?unit=u-1")
    # D536: сведения и цифры пиццерии — в рабочей области, а не в панели; панель — для проверки.
    справа = страница.split('<section class="pk-work">', 1)[1]
    assert "Руставели" in справа and "ООО Ромашка" in справа and "cn-facts" in справа
    # D539: кнопки «Карточка пиццерии» нет — пиццерия открыта здесь же.
    assert "/units/u-1" not in справа
    assert f"inspection={вид.snapshot.inspections[0].id}" in справа
    assert "data-drawer>" not in страница and 'id="sdrawer-title"' not in страница


def test_точка_только_из_свода_открывается_без_карточки(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    ключ = country_units.SVOD_KEY + "pipe-1"
    с_таблицей(monkeypatch, строка_таблицы(key=ключ, name="Pipe-1", unit_id="", stage="pipeline"))
    страница = открыть(стенд, monkeypatch, данные(), f"/country/GE?unit={ключ}")
    assert "/units/u-" not in страница and "/units/pipe" not in страница
    assert "Pipe-1" in страница.split('<section class="pk-work">', 1)[1]


def test_ссылки_пиццерий_сохраняют_период_и_язык(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    с_таблицей(monkeypatch, строка_таблицы())
    страница = открыть(
        стенд,
        monkeypatch,
        с_точкой(данные()),
        "/country/GE?from=2026-09-01&to=2026-09-30&lang=en",
    )
    ссылка = next(ч for ч in страница.split('"') if "unit=u-1" in ч)
    assert "from=2026-09-01" in ссылка and "lang=en" in ссылка


def test_пустая_страна_одна_тихая_строка_без_пустых_рамок(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    вид = replace(
        данные(),
        snapshot=replace(
            данные().snapshot,
            points=(), inspections=(), inspections_total=0, systemic=(),
        ),
    )  # fmt: skip
    страница = открыть(стенд, monkeypatch, вид, "/country/GE")
    assert страница.count('class="pk-empty"') == 1
    assert "За период проверок не было" in страница and "period=all" in страница
    assert "pk-tiles" not in страница and "cn-hurt" not in страница


def test_где_болит_одним_блоком_и_только_при_проверках(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    страница = открыть(стенд, monkeypatch, данные(), "/country/GE")
    assert страница.count('cn-hurt"') == 1 and "K-041" in страница and "Чистота" in страница


def test_смена_языка_оставляет_страну_и_раскрытую_точку(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    вид = с_точкой(данные())
    вид = replace(вид, unit_id="u-1", unit_name="Батуми-1", history=вид.snapshot.inspections)
    страница = открыть(стенд, monkeypatch, вид, "/country/GE?unit=u-1&period=d90")
    # У вошедшего язык сохраняется в профиль (D447): пилюля шлёт POST и
    # возвращает на эту же страницу со страной, точкой и периодом.
    assert 'action="/settings/lang"' in страница
    assert 'name="next" value="/country/GE?unit=u-1&amp;period=d90"' in страница


def test_фильтр_страны_сохраняет_текущий_выбор(стенд, monkeypatch):
    monkeypatch.setattr(cn, "countries", lambda **kw: (("GE", 3), ("RS", 2)))
    страница = открыть(стенд, monkeypatch, данные(), "/country/GE")
    фильтр = страница.split('aria-label="Страна"', 1)[1].split("</select>", 1)[0]
    assert "/country/GE" in фильтр and "/country/RS" in фильтр
    assert "selected>Грузия" in фильтр


def test_без_страны_в_адресе_справа_первая_страна_а_не_пустота(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Рабочая зона не пустует (владелец 30.09.2026, скриншот пустого «Выберите
    страну»): справа первая страна колонки, и в колонке она выделена."""
    monkeypatch.setattr(cn, "countries", lambda **_: (("GE", 3), ("RS", 2)))
    просили: list[str] = []

    def load(**kw: object) -> cn.CountryView:
        просили.append(str(kw["code"]))
        return данные()

    monkeypatch.setattr(cn, "load", load)
    ответ = стенд.get("/country")
    assert ответ.status_code == 200, ответ.status_code
    страница = ответ.get_data(as_text=True)
    assert просили == ["GE"]
    assert "Выберите страну" not in страница and "Choose a country" not in страница
    фильтр = страница.split('aria-label="Страна"', 1)[1].split("</select>", 1)[0]
    assert "selected>Грузия" in фильтр


def test_обрезанный_срез_страны_экран_называет_вслух(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    вид = данные()
    обрезан = replace(вид, snapshot=replace(вид.snapshot, truncated=True))

    assert "В срезе больше 100 проверок" in открыть(стенд, monkeypatch, обрезан, "/country/GE")
    assert "В срезе больше" not in открыть(стенд, monkeypatch, вид, "/country/GE")


def test_шапка_страны_держит_кнопки_и_счётчики(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    страница = открыть(стенд, monkeypatch, данные(), "/country/GE")
    шапка = страница.split('class="cn-head__actions"', 1)[1].split("</div>", 1)[0]
    assert "cn-count" in шапка and "Экшн-планы" in шапка and "Предписания" in шапка


def test_девелопер_в_колонке_и_сводка_его_стран(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cn, "countries", lambda **_: (("GE", 3), ("RS", 2)))
    monkeypatch.setattr(
        country_summary,
        "developers_of",
        lambda _c: ({"Иван": ("RS",)}, {"RS": "Иван"}, False),
    )
    видели: list[str] = []

    def load(**kw: object) -> cn.CountryView:
        видели.append(str(kw["code"]))
        return replace(данные(), code=str(kw["code"]))

    monkeypatch.setattr(cn, "load", load)
    без = стенд.get("/country/GE").get_data(as_text=True)
    assert "Девелопер" in без and "dev=" in без
    сводка = стенд.get("/country?dev=Иван").get_data(as_text=True)
    колонка, справа = сводка.split('class="pk-work"', 1)
    assert видели[-1] == "RS" and "/country/GE" not in колонка
    assert 'pk-kicker">Страна<' not in справа.split("<h1", 1)[0]
    # D527: строки сводки группы не уводят на другую страницу.
    assert "/country/RS" in справа.split('aria-label="Страна"', 1)[1].split("</select>", 1)[0]
    таблица = справа.split('class="ov-table cn-countries"', 1)[1].split("</div>", 1)[0]
    assert 'href="/country/RS' not in таблица
    # Неизвестный девелопер не сужает ничего.
    assert "/country/GE" in стенд.get("/country?dev=нет").get_data(as_text=True)


def test_среднее_нескольких_стран_взвешено_числом_проверок() -> None:
    a = replace(снимок(inspections=()), inspections_total=1, average=60.0, grades=(("D", 1),))
    b = replace(снимок(inspections=()), inspections_total=3, average=100.0, grades=(("A", 3),))
    итог = country_summary.summarize([a, b])
    assert итог.average == 90.0 and итог.inspections == 4
    assert итог.grades == (("A", 3), ("D", 1))


def test_строки_таблицы_сводят_справочник_и_свод_по_коду_а_свод_без_пары_остаётся() -> None:
    from src.db.unit_profiles import Profile

    точки = [Unit(id="u-1", name="Батуми-1", code="C1", aliases=(), country="GE", city="batumi")]
    свод = [
        Profile(country_code="GE", name="Батуми-1", stage="closed", status="x", dodo_id="C1",
                partner="П"),
        Profile(country_code="GE", name="Новая", stage="pipeline", status="y", name_normalized="n"),
    ]  # fmt: skip
    строки = country_units.build_rows(точки, свод, {}, {"C1": (91.0, 88.0)}, {"C1": {2: 4.6}})
    by = {r.name: r for r in строки}
    assert by["Батуми-1"].is_closed and by["Батуми-1"].partner == "П"
    assert (by["Батуми-1"].rs, by["Батуми-1"].maps) == (91.0, {2: 4.6})
    assert by["Новая"].unit_id == "" and by["Новая"].key == "svod:n"
