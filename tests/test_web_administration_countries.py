"""Вкладка «Администрирование → Страны» (D640, #1251): кто видит, что правит, языки отчёта.

Права не менялись: вкладка открыта тем, у кого есть `space.manage` или `contract.manage`;
ОСБ видит договор и не видит форм девелопера, партнёра и языков. Языки отчёта — запись
в базу только из языков методики и не меньше одного. Двери базы подменены: что держит
сама таблица, проверяет `tests/test_db_country_report_langs.py`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from flask.testing import FlaskClient
from test_web_country import данные, открыть
from web_harness import СВОЙ, войти, подменить_двери, собрать

from src.db import country_contracts as cc
from src.db import country_report_langs as crl
from src.db.errors import DbError
from src.db.reach import Reach
from src.db.spaces import SpaceRow
from src.web import country as cn
from src.web import country_summary, country_units, partner_spaces

ЗАГОЛОВКИ = {"Origin": СВОЙ}
ВКЛАДКА = "/administration?tab=countries"
ЯЗЫКИ = "/country/GE/settings/report-langs"


@pytest.fixture
def записи(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    """Что писали в языки отчёта; чтение базы подменено."""
    журнал: dict[str, list[Any]] = {"save": [], "reset": []}
    monkeypatch.setattr(crl, "read", lambda _c: None)
    monkeypatch.setattr(
        crl, "save", lambda c, langs, *, actor: журнал["save"].append((c, langs, actor))
    )
    monkeypatch.setattr(crl, "reset", lambda c: журнал["reset"].append(c))
    monkeypatch.setattr(cc, "read", lambda _c: ())
    monkeypatch.setattr(crl, "read_all", lambda: {"AM": ("en", "ru")})
    monkeypatch.setattr(cc, "countries_with_contract", lambda: frozenset({"AM"}))
    monkeypatch.setattr(
        partner_spaces,
        "overview",
        lambda: (SpaceRow("HQ", "УК", (), 3), SpaceRow("LOTOS", "Лотос", ("AM",), 1)),
    )
    monkeypatch.setattr(cn, "countries", lambda **_: (("GE", 3), ("AM", 2)))
    monkeypatch.setattr(
        country_summary,
        "developers_of",
        lambda _codes: ({"Иван": ("AM",)}, {"AM": "Иван"}, False),
    )
    monkeypatch.setattr(country_units, "load", lambda **_: country_units.UnitsData())
    return журнал


def _клиент(role: str) -> Callable[..., Iterator[FlaskClient]]:
    def фикстура(
        monkeypatch: pytest.MonkeyPatch, записи: dict[str, list[Any]]
    ) -> Iterator[FlaskClient]:
        подменить_двери(monkeypatch, tenant="HQ", role=role)
        with собрать(tenant="HQ").test_client() as client:
            assert войти(client).status_code == 302
            yield client

    return фикстура


главный = pytest.fixture(_клиент("superadmin"), name="главный")
админ = pytest.fixture(_клиент("admin"), name="админ")
осб = pytest.fixture(_клиент("osb"), name="осб")
девелопер = pytest.fixture(_клиент("developer"), name="девелопер")


def _страница(client: FlaskClient, query: str = "") -> str:
    ответ = client.get(ВКЛАДКА + query)
    assert ответ.status_code == 200, ответ.status_code
    return ответ.get_data(as_text=True)


@pytest.mark.parametrize("кто", ["главный", "админ", "осб"])
def test_вкладку_видят_те_у_кого_есть_управление_страной_или_договором(
    кто: str, request: pytest.FixtureRequest
) -> None:
    клиент: FlaskClient = request.getfixturevalue(кто)
    страница = _страница(клиент)
    assert "tab=countries" in страница and ">Страны</span>" in страница


def test_девелопер_вкладки_не_видит_и_адрес_закрыт(девелопер: FlaskClient) -> None:
    assert девелопер.get(ВКЛАДКА).status_code == 404


def test_список_стран_столбцом_с_партнёром_и_девелопером(главный: FlaskClient) -> None:
    страница = _страница(главный)
    список = страница.split("pk-rail--col")[1]
    assert список.count('<a class="pk-item') == 2, "каждая страна — строка колонки `pick_item`"
    # Армения закреплена за пространством Лотос, девелопер — Иван; у Грузии ни того ни другого.
    строка_am = список[список.index("country=AM") :]
    assert "Лотос" in строка_am and "Иван" in строка_am
    строка_ge = список[список.index("country=GE") : список.index("country=AM")]
    assert "Лотос" not in строка_ge and "Иван" not in строка_ge


def test_список_показывает_что_настроено_у_каждой_страны(главный: FlaskClient) -> None:
    список = _страница(главный).split("pk-rail--col")[1]
    строка_am = список[список.index("country=AM") : список.index("country=GE")]
    строка_ge = список[список.index("country=GE") :]
    assert "EN · RU" in строка_am and "есть" in строка_am
    assert "по умолчанию" in строка_ge and "нет" in строка_ge and "не задан" in строка_ge
    assert список.count("data-drawer-open") == 2, "строка открывает панель справа, не страницу"


def test_язык_и_договор_читаются_одним_запросом_на_все_страны(
    главный: FlaskClient, монкей: pytest.MonkeyPatch
) -> None:
    вызовы: list[str] = []
    монкей.setattr(crl, "read_all", lambda: вызовы.append("langs") or {})
    монкей.setattr(cc, "countries_with_contract", lambda: вызовы.append("contract") or frozenset())
    _страница(главный)
    assert sorted(вызовы) == ["contract", "langs"]


def test_панель_страны_четыре_блока_у_каждого_своя_кнопка(главный: FlaskClient) -> None:
    страница = _страница(главный, "&country=GE")
    панель = страница[страница.index('class="cblocks"') :]
    assert панель.count('<section class="cblock') == 4, "блоков должно быть четыре"
    блоки = панель.split('<section class="cblock')[1:]
    assert len(блоки) == 4
    for блок, заголовок in zip(
        блоки, ("Партнёр", "Девелопер", "Языки отчёта", "Договор"), strict=True
    ):
        assert f">{заголовок}</h3>" in блок, заголовок
        assert 'class="sbtn' in блок.split("</section>")[0] and "<summary" in блок, заголовок


def test_без_выбора_панель_закрыта(главный: FlaskClient) -> None:
    assert "sdrawer__panel" not in _страница(главный)


def test_админ_видит_формы_девелопера_партнёра_и_языков(админ: FlaskClient) -> None:
    страница = _страница(админ, "&country=GE")
    for форма in ("/settings/developer", "/settings/space", "/settings/report-langs"):
        assert f"/country/GE{форма}" in страница, форма
    assert 'name="langs" value="ru"' in страница and 'name="langs" value="en"' in страница
    # Список стран и панель — на одном экране.
    assert "pk-rail--col" in страница and "sdrawer__panel" in страница


def test_осб_видит_договор_и_не_видит_форм_девелопера_партнёра_и_языков(
    осб: FlaskClient,
) -> None:
    страница = _страница(осб, "&country=GE")
    assert "/country/GE/settings/contract" in страница
    for форма in ("/settings/developer", "/settings/space", "/settings/report-langs"):
        assert форма not in страница, форма


def test_чужая_или_неизвестная_страна_во_вкладке_404(главный: FlaskClient) -> None:
    assert главный.get(ВКЛАДКА + "&country=ZZ").status_code == 404


def test_страна_вне_охвата_закрыта_и_для_записи_языков(
    главный: FlaskClient, монкей: pytest.MonkeyPatch, записи: dict[str, list[Any]]
) -> None:
    монкей.setattr(
        "src.web.auth.reach_of",
        lambda tenant: Reach(tenant=tenant, tenants=None, countries=("AM",)),
    )
    ответ = главный.post(ЯЗЫКИ, data={"langs": "en"}, headers=ЗАГОЛОВКИ)
    assert ответ.status_code == 404 and записи["save"] == []


@pytest.fixture
def монкей(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    return monkeypatch


@pytest.mark.parametrize("кто", ["главный", "админ"])
def test_сохранение_языков_пишет_в_порядке_методики_и_ведёт_во_вкладку(
    кто: str, request: pytest.FixtureRequest, записи: dict[str, list[Any]]
) -> None:
    клиент: FlaskClient = request.getfixturevalue(кто)
    ответ = клиент.post(ЯЗЫКИ, data={"langs": ["en", "ru"]}, headers=ЗАГОЛОВКИ)
    assert ответ.status_code == 302
    assert "/administration?tab=countries&country=GE&saved=ok" in ответ.headers["Location"]
    ((страна, языки, кто_правил),) = записи["save"]
    assert (страна, языки) == ("GE", ("ru", "en")) and кто_правил


@pytest.mark.parametrize("ввод", [{}, {"langs": ""}, {"langs": "xx"}, {"langs": ["ru", "xx"]}])
def test_пустой_или_чужой_язык_отказ_и_ничего_не_пишется(
    главный: FlaskClient, записи: dict[str, list[Any]], ввод: dict[str, Any]
) -> None:
    ответ = главный.post(ЯЗЫКИ, data=ввод, headers=ЗАГОЛОВКИ)
    assert ответ.status_code == 302 and "saved=langs_invalid" in ответ.headers["Location"]
    assert записи["save"] == [] and записи["reset"] == []
    страница = _страница(главный, "&country=GE&saved=langs_invalid")
    assert "Языки не сохранены" in страница


def test_как_по_умолчанию_снимает_переопределение(
    главный: FlaskClient, записи: dict[str, list[Any]]
) -> None:
    ответ = главный.post(ЯЗЫКИ, data={"reset": "1"}, headers=ЗАГОЛОВКИ)
    assert "saved=ok" in ответ.headers["Location"]
    assert записи["reset"] == ["GE"] and записи["save"] == []


def test_отказ_базы_отвечает_failed(главный: FlaskClient, монкей: pytest.MonkeyPatch) -> None:
    def сбой(*_a: Any, **_k: Any) -> None:
        raise DbError("база не на связи")

    монкей.setattr(crl, "save", сбой)
    ответ = главный.post(ЯЗЫКИ, data={"langs": "ru"}, headers=ЗАГОЛОВКИ)
    assert "saved=failed" in ответ.headers["Location"]


@pytest.mark.parametrize("кто", ["осб", "девелопер"])
def test_языки_остальным_ролям_закрыты_и_ничего_не_пишут(
    кто: str, request: pytest.FixtureRequest, записи: dict[str, list[Any]]
) -> None:
    клиент: FlaskClient = request.getfixturevalue(кто)
    ответ = клиент.post(ЯЗЫКИ, data={"langs": "ru"}, headers=ЗАГОЛОВКИ)
    assert ответ.status_code in (403, 404)
    assert записи["save"] == [] and записи["reset"] == []


def test_чужой_источник_запроса_отказ(главный: FlaskClient, записи: dict[str, list[Any]]) -> None:
    ответ = главный.post(ЯЗЫКИ, data={"langs": "ru"}, headers={"Origin": "https://evil.example"})
    assert ответ.status_code == 403 and записи["save"] == []


def test_задан_в_базе_перечень_показан_отмеченным_со_сбросом(
    главный: FlaskClient, монкей: pytest.MonkeyPatch
) -> None:
    монкей.setattr(crl, "read", lambda _c: ("en",))
    страница = _страница(главный, "&country=GE")
    assert 'value="en" checked' in страница and 'value="ru" checked' not in страница
    assert 'name="reset"' in страница


def test_страница_страны_без_форм_и_со_ссылкой_изменить(
    админ: FlaskClient, монкей: pytest.MonkeyPatch, записи: dict[str, list[Any]]
) -> None:
    страница = открыть(админ, монкей, данные(), "/country/GE?settings=1")
    assert "Карточка страны" in страница, "карточка не открылась — проверять нечего"
    assert "/country/GE/settings/" not in страница and "ccard__contract" not in страница
    assert 'href="/administration?tab=countries&amp;country=GE"' in страница


def test_у_роли_без_вкладки_ссылки_изменить_нет(
    девелопер: FlaskClient, монкей: pytest.MonkeyPatch, записи: dict[str, list[Any]]
) -> None:
    страница = открыть(девелопер, монкей, данные(), "/country/GE?settings=1")
    assert "Карточка страны" in страница and "tab=countries" not in страница
