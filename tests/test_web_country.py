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


def test_справа_блоки_а_пиццерии_слева_без_вкладок(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D504: вкладок «Сводка / Пиццерии» нет — справа блоки, пиццерии в колонке слева."""
    с_таблицей(monkeypatch, строка_таблицы())
    страница = открыть(стенд, monkeypatch, с_точкой(данные()), "/country/GE")
    колонка, справа = страница.split("</aside>", 1)
    assert "pk-tiles" in справа and 'class="seg"' not in страница
    assert "Батуми-1" in колонка and "pk-item--sub" in колонка


def test_пиццерии_слева_закрытые_свёрнуты(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    с_таблицей(
        monkeypatch,
        строка_таблицы(),
        строка_таблицы(key="u-2", name="Тбилиси-2", unit_id="u-2", stage="closed"),
    )
    страница = открыть(стенд, monkeypatch, с_точкой(данные()), "/country/GE")
    колонка = страница.split("</aside>", 1)[0]
    открытые, закрытые = колонка.split('class="pk-closed"', 1)
    assert "Батуми-1" in открытые and "Тбилиси-2" not in открытые
    assert "Тбилиси-2" in закрытые
    # Адрес и партнёр в строку не выносятся — они в панели пиццерии.
    assert "Руставели" not in страница


def test_выбранная_точка_показывает_справа_сведения_и_свои_проверки(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    вид = с_точкой(данные())
    вид = replace(вид, unit_id="u-1", unit_name="Батуми-1", history=вид.snapshot.inspections)
    с_таблицей(monkeypatch, строка_таблицы())
    страница = открыть(стенд, monkeypatch, вид, "/country/GE?unit=u-1")
    # D536: сведения и цифры пиццерии — в рабочей области, а не в панели; панель — для проверки.
    справа = страница.split("</aside>", 1)[1]
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
    assert "Pipe-1" in страница.split("</aside>", 1)[1]


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


def test_страна_выбирается_в_списке_слева_и_выбранная_отмечена(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D474, D527: страны — списком слева (не выпадающим), выбранная отмечена."""
    monkeypatch.setattr(cn, "countries", lambda **_: (("GE", 3), ("RS", 2)))
    страница = открыть(стенд, monkeypatch, данные(), "/country/GE")
    колонка = страница.split('class="pk-rail"', 1)[1].split("</aside>", 1)[0]
    assert "/country/GE" in колонка and "/country/RS" in колонка
    отмеченная = колонка.split("pk-item is-on", 1)[1].split("</a>", 1)[0]
    assert "Грузия" in отмеченная or "GE" in отмеченная
    # Без девелопера строки «сводка по всем странам» нет; «Мои страны» — свой отбор (D536).
    assert 'class="pick"' not in колонка and "Σ" not in колонка


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
    колонка = страница.split('class="pk-rail"', 1)[1].split("</aside>", 1)[0]
    assert (
        "pk-item is-on" in колонка and "/country/GE" in колонка.split("pk-item is-on", 1)[1][:200]
    )


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
    assert "/country/RS" not in справа
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


def test_последняя_проверка_в_колонке_это_последняя_вообще_а_не_за_период(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D474: дата — последней проверки за всё время; нет за период — пометка рядом."""
    с_таблицей(
        monkeypatch,
        строка_таблицы(last_ever=date(2026, 8, 3)),
        строка_таблицы(key="u-2", name="Тбилиси-2", unit_id="u-2"),
    )
    колонка = открыть(стенд, monkeypatch, данные(), "/country/GE").split("</aside>", 1)[0]
    батуми, тбилиси = колонка.split("Тбилиси-2")
    assert "2026-08-03" in батуми and "за период нет" in батуми
    assert "не проверяли" in тбилиси


def test_над_пиццериями_сколько_проверены_хоть_раз_а_закрытые_не_в_счёт(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D549: «ни разу не проверяли» живёт в карточке страны, а не галочкой реестра."""
    с_таблицей(
        monkeypatch,
        строка_таблицы(last_ever=date(2026, 8, 3)),
        строка_таблицы(key="u-2", name="Тбилиси-2", unit_id="u-2"),
        строка_таблицы(key="u-3", name="Кутаиси-1", unit_id="u-3"),
        строка_таблицы(key="u-4", name="Гори-1", unit_id="u-4", stage="closed"),
    )
    колонка = открыть(стенд, monkeypatch, данные(), "/country/GE").split("</aside>", 1)[0]
    assert "Проверены хоть раз: 1 из 3 · ни разу: 2" in колонка


def test_поиск_в_колонке_сужает_пиццерии_а_выбранная_страна_остаётся(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    с_таблицей(
        monkeypatch,
        строка_таблицы(),
        строка_таблицы(key="u-2", name="Тбилиси-2", unit_id="u-2", city="tbilisi"),
    )
    колонка = открыть(стенд, monkeypatch, данные(), "/country/GE?q=тбил").split("</aside>", 1)[0]
    assert "Тбилиси-2" in колонка and "Батуми-1" not in колонка
    assert "/country/GE" in колонка
