"""Блок «Договор» в карточке страны (D603): кто видит, кто правит, что партнёр не видит.

Ядро — права: почты контактов по ДКК — персональные данные. Блок видит только УК;
правят ОСБ, админ и главный админ (`contract.manage`), а остальную карточку
(девелопер, партнёр страны — `space.manage`) ОСБ по-прежнему не трогает. Двери базы
подменены: что держит сама таблица, проверяет `tests/test_db_country_contracts.py`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from flask.testing import FlaskClient
from test_web_country import (
    данные,
    открыть,
)
from test_web_country import стенд as база_стенд  # noqa: F401
from test_web_country_partner import _партнёр, чтения  # noqa: F401
from web_harness import СВОЙ, войти, подменить_двери, собрать

from src.db import country_contracts as cc
from src.db import ratings_read
from src.web import country as cn
from src.web import partner_spaces

ЗАГОЛОВКИ = {"Origin": СВОЙ}
ПОЧТА = "dkk@ge.example.com"
СТРОКА = cc.Contract(
    id="11111111-1111-1111-1111-111111111111",
    country="GE",
    legal_name="Lotos LLC",
    registration_country="Georgia",
    company_number="405123456",
    address="Rustaveli 1, Batumi",
    agreement="DCA No. 7 of 2024-03-01",
    dkk_emails=ПОЧТА,
    updated_by="osb-anna",
    updated_at=datetime(2026, 10, 20, tzinfo=UTC),
)
ПОЛЯ = {
    "legal_name": "Lotos LLC",
    "registration_country": "Georgia",
    "company_number": "405123456",
    "address": "Rustaveli 1",
    "agreement": "DCA No. 7",
    "dkk_emails": "a@ge.example.com; b@ge.example.com",
}


@pytest.fixture
def записи(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    """Что договор страны читали и писали: база подменена."""
    журнал: dict[str, list[Any]] = {"read": [], "save": [], "remove": []}

    def read(code: str) -> tuple[cc.Contract, ...]:
        журнал["read"].append(code)
        return (СТРОКА,)

    monkeypatch.setattr(cc, "read", read)
    monkeypatch.setattr(cc, "save", lambda *a, **k: журнал["save"].append((a, k)))
    monkeypatch.setattr(cc, "remove", lambda *a, **k: журнал["remove"].append((a, k)))
    monkeypatch.setattr(partner_spaces, "overview", lambda: ())
    return журнал


def _роль(monkeypatch: pytest.MonkeyPatch, role: str) -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant="HQ", role=role)
    monkeypatch.setattr(cn, "countries", lambda **_: (("GE", 1),))
    with собрать(tenant="HQ").test_client() as client:
        assert войти(client).status_code == 302
        yield client


@pytest.fixture
def осб(база_стенд: FlaskClient, монкей: pytest.MonkeyPatch, записи: Any) -> Iterator[FlaskClient]:  # noqa: F811
    yield from _роль(монкей, "osb")


@pytest.fixture
def монкей(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    return monkeypatch


def _клиент(role: str) -> Callable[..., Iterator[FlaskClient]]:
    def фикстура(
        база_стенд: FlaskClient,  # noqa: F811
        монкей: pytest.MonkeyPatch,
        записи: Any,
    ) -> Iterator[FlaskClient]:
        yield from _роль(монкей, role)

    return фикстура


админ = pytest.fixture(_клиент("admin"), name="админ")
главный = pytest.fixture(_клиент("superadmin"), name="главный")
девелопер = pytest.fixture(_клиент("developer"), name="девелопер")
гость = pytest.fixture(_клиент("guest"), name="гость")

ФОРМА = "/country/GE/settings/contract"


def _страница(client: FlaskClient, monkeypatch: pytest.MonkeyPatch, saved: str = "") -> str:
    адрес = "/country/GE?settings=1" + (f"&saved={saved}" if saved else "")
    return открыть(client, monkeypatch, данные(), адрес)


@pytest.mark.parametrize("кто", ["осб", "админ", "главный"])
def test_осб_админ_и_главный_админ_видят_договор_и_правят_его(
    кто: str, request: pytest.FixtureRequest, монкей: pytest.MonkeyPatch
) -> None:
    клиент: FlaskClient = request.getfixturevalue(кто)
    страница = _страница(клиент, монкей)
    assert "Lotos LLC" in страница and ПОЧТА in страница and "DCA No. 7" in страница
    assert "Правил: osb-anna" in страница
    assert ФОРМА in страница, "формы правки у того, кто вправе, нет"


@pytest.mark.parametrize("кто", ["девелопер", "гость"])
def test_остальные_роли_ук_договор_не_видят(
    кто: str, request: pytest.FixtureRequest, монкей: pytest.MonkeyPatch
) -> None:
    """Договор — только тем, кто его ведёт: ОСБ, админ, главный админ (D609)."""
    клиент: FlaskClient = request.getfixturevalue(кто)
    страница = _страница(клиент, монкей)
    assert ПОЧТА not in страница and "Lotos LLC" not in страница
    assert ФОРМА not in страница


def test_партнёр_договор_и_почты_не_видит_и_база_не_читается(
    монкей: pytest.MonkeyPatch,
    записи: dict[str, list[Any]],
    чтения: Any,  # noqa: F811
) -> None:
    for клиент in _партнёр(монкей, "GE"):
        страница = клиент.get("/country/GE?settings=1").get_data(as_text=True)
        assert "Карточка страны" in страница, "карточка не открылась — проверять нечего"
        assert ПОЧТА not in страница and "Lotos LLC" not in страница
        assert "ccard__contract" not in страница and "settings/contract" not in страница
    assert записи["read"] == []


@pytest.mark.parametrize("кто", ["осб", "админ", "главный"])
def test_правка_договора_подписана_вошедшим_и_уходит_в_базу(
    кто: str, request: pytest.FixtureRequest, записи: dict[str, list[Any]]
) -> None:
    клиент: FlaskClient = request.getfixturevalue(кто)
    ответ = клиент.post(ФОРМА, data={**ПОЛЯ, "contract_id": СТРОКА.id}, headers=ЗАГОЛОВКИ)
    assert ответ.status_code == 302 and "saved=ok" in ответ.headers["Location"]
    ((args, kwargs),) = записи["save"]
    assert args[0] == "GE" and args[1].legal_name == "Lotos LLC"
    assert kwargs["contract_id"] == СТРОКА.id and kwargs["actor"]


def test_новая_строка_без_идентификатора(осб: FlaskClient, записи: dict[str, list[Any]]) -> None:
    осб.post(ФОРМА, data=ПОЛЯ, headers=ЗАГОЛОВКИ)
    assert записи["save"][0][1]["contract_id"] is None


@pytest.mark.parametrize("кто", ["девелопер", "гость"])
def test_правка_договора_остальным_ролям_закрыта_и_ничего_не_пишет(
    кто: str, request: pytest.FixtureRequest, записи: dict[str, list[Any]]
) -> None:
    клиент: FlaskClient = request.getfixturevalue(кто)
    for путь in (ФОРМА, f"{ФОРМА}/{СТРОКА.id}/delete"):
        ответ = клиент.post(путь, data=ПОЛЯ, headers=ЗАГОЛОВКИ)
        assert ответ.status_code in (403, 404), путь
    assert записи["save"] == [] and записи["remove"] == []


def test_партнёру_адреса_договора_закрыты(
    монкей: pytest.MonkeyPatch,
    записи: dict[str, list[Any]],
    чтения: Any,  # noqa: F811
) -> None:
    for клиент in _партнёр(монкей, "GE"):
        for путь in (ФОРМА, f"{ФОРМА}/{СТРОКА.id}/delete"):
            ответ = клиент.post(путь, data=ПОЛЯ, headers=ЗАГОЛОВКИ)
            assert ответ.status_code in (403, 404), путь
    assert записи["save"] == [] and записи["remove"] == []


@pytest.mark.parametrize("путь", ["/country/GE/settings/developer", "/country/GE/settings/space"])
def test_осб_правит_договор_но_не_девелопера_и_не_партнёра_страны(
    осб: FlaskClient, монкей: pytest.MonkeyPatch, путь: str
) -> None:
    записано: list[Any] = []
    монкей.setattr(ratings_read, "set_developer", lambda *a, **k: записано.append(a) or True)
    монкей.setattr(partner_spaces, "add_countries", lambda *a: записано.append(a) or ())
    ответ = осб.post(путь, data={"developer": "X", "space": "LOTOS"}, headers=ЗАГОЛОВКИ)
    assert ответ.status_code in (403, 404) and записано == []
    # Страница карточки у неё открыта, но форм девелопера и партнёра в ней нет.
    страница = _страница(осб, монкей)
    assert "/settings/developer" not in страница and "/settings/space" not in страница


def test_неверная_почта_не_доходит_до_базы_и_отвечает_словами(
    осб: FlaskClient, монкей: pytest.MonkeyPatch, записи: dict[str, list[Any]]
) -> None:
    ответ = осб.post(ФОРМА, data={**ПОЛЯ, "dkk_emails": "не-почта"}, headers=ЗАГОЛОВКИ)
    assert ответ.status_code == 302 and "saved=invalid" in ответ.headers["Location"]
    assert записи["save"] == []
    assert "проверьте почты" in _страница(осб, монкей, "invalid")


def test_подмена_заголовка_через_перевод_строки_не_доходит_до_базы(
    осб: FlaskClient, записи: dict[str, list[Any]]
) -> None:
    ввод = f"{ПОЧТА}\r\nBcc: evil@x.example.com"
    ответ = осб.post(ФОРМА, data={**ПОЛЯ, "dkk_emails": ввод}, headers=ЗАГОЛОВКИ)
    assert "saved=invalid" in ответ.headers["Location"] and записи["save"] == []


def test_отказ_базы_отвечает_failed(осб: FlaskClient, монкей: pytest.MonkeyPatch) -> None:
    def сбой(*_a: Any, **_k: Any) -> None:
        raise cc.CountryContractError("база не на связи")

    монкей.setattr(cc, "save", сбой)
    ответ = осб.post(ФОРМА, data=ПОЛЯ, headers=ЗАГОЛОВКИ)
    assert "saved=failed" in ответ.headers["Location"]


def test_снятие_строки(осб: FlaskClient, записи: dict[str, list[Any]]) -> None:
    ответ = осб.post(f"{ФОРМА}/{СТРОКА.id}/delete", headers=ЗАГОЛОВКИ)
    assert ответ.status_code == 302 and "saved=ok" in ответ.headers["Location"]
    assert записи["remove"] == [(("GE", СТРОКА.id), {})]


def test_чужой_источник_запроса_отказ(осб: FlaskClient, записи: dict[str, list[Any]]) -> None:
    ответ = осб.post(ФОРМА, data=ПОЛЯ, headers={"Origin": "https://evil.example"})
    assert ответ.status_code == 403 and записи["save"] == []


def test_договор_не_прочитался_блок_говорит_об_этом(
    осб: FlaskClient, монкей: pytest.MonkeyPatch
) -> None:
    def сбой(_c: str) -> tuple[cc.Contract, ...]:
        raise cc.CountryContractError("база не на связи")

    монкей.setattr(cc, "read", сбой)
    страница = _страница(осб, монкей)
    assert "Договор не прочитался" in страница
    assert "не заполнен" not in страница and ФОРМА not in страница
