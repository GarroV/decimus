"""Защита пространства партнёра на экране «Пользователи» (D759): права и маршруты.

Ядро доступа: кто может заморозить пространство целиком и кто видит и закрывает
сообщения о новых админах и сменах почты. Слой базы подменён на границе модуля; что
заморозка делает с учётками и событиями — `test_db_partner_space_safety.py`.

- замораживает и размораживает пространство тот, кто ведёт пространства: главный админ
  и админ УК; админ партнёра, контроль — 403; УК заморозить нельзя;
- блок событий видят только они, и отметить «Видел» может только они.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from flask.testing import FlaskClient
from web_harness import войти, подменить_двери, собрать

from src.db import bot_links, partner_events
from src.web import accounts, partner_spaces

ЗАГОЛОВКИ = {"Origin": "http://localhost"}
СОБЫТИЕ = partner_events.PartnerEvent(
    id=7,
    occurred_at=datetime(2026, 11, 12, 9, 30, tzinfo=UTC),
    tenant="GE",
    kind="admin_added",
    login="nino-new",
    role="admin",
    actor="kostya",
)


@pytest.fixture
def зовы(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    журнал: dict[str, list[Any]] = {"freeze": [], "unfreeze": [], "seen": [], "add": []}
    заморожено: dict[str, Any] = {}

    def freeze(code: str, *, by: Any) -> int:
        журнал["freeze"].append((code, by))
        return 3

    def unfreeze(code: str) -> int:
        журнал["unfreeze"].append(code)
        return 3

    def add(login: str, *, tenant: str, role: str = "auditor") -> accounts.Added:
        журнал["add"].append((login, tenant, role))
        return accounts.Added(login=login, role=role, password="одноразовый-пароль-24-знака")

    monkeypatch.setattr(accounts, "everyone", lambda *, tenant: ())
    monkeypatch.setattr(accounts, "spaces", lambda: ("GE", "HQ"))
    monkeypatch.setattr(accounts, "add", add)
    monkeypatch.setattr(bot_links, "live_bindings", dict)
    monkeypatch.setattr(
        partner_spaces,
        "overview",
        lambda: (
            partner_spaces.SpaceRow("GE", "Партнёр Г", ("GE",), 2),
            partner_spaces.SpaceRow("HQ", "", (), 4),
        ),
    )
    monkeypatch.setattr(partner_spaces, "frozen_spaces", lambda: заморожено)
    monkeypatch.setattr(partner_spaces, "freeze_space", freeze)
    monkeypatch.setattr(partner_spaces, "unfreeze_space", unfreeze)
    monkeypatch.setattr(partner_events, "unseen", lambda viewer, **_: ((СОБЫТИЕ,), 1))
    monkeypatch.setattr(
        partner_events, "mark_seen", lambda viewer, event: журнал["seen"].append(event) or True
    )
    журнал["_frozen"] = [заморожено]
    return журнал


def _стенд(monkeypatch: pytest.MonkeyPatch, *, tenant: str, role: str) -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant=tenant, role=role)
    with собрать(tenant="HQ").test_client() as client:
        assert войти(client).status_code == 302
        yield client


@pytest.fixture
def главный(monkeypatch: pytest.MonkeyPatch, зовы: Any) -> Iterator[FlaskClient]:
    yield from _стенд(monkeypatch, tenant="HQ", role="superadmin")


@pytest.fixture
def админ_уК(monkeypatch: pytest.MonkeyPatch, зовы: Any) -> Iterator[FlaskClient]:
    yield from _стенд(monkeypatch, tenant="HQ", role="admin")


@pytest.fixture
def админ_GE(monkeypatch: pytest.MonkeyPatch, зовы: Any) -> Iterator[FlaskClient]:
    yield from _стенд(monkeypatch, tenant="GE", role="admin")


@pytest.fixture
def контроль(monkeypatch: pytest.MonkeyPatch, зовы: Any) -> Iterator[FlaskClient]:
    yield from _стенд(monkeypatch, tenant="HQ", role="control")


def _post(client: FlaskClient, path: str, **data: str) -> Any:
    return client.post(path, data=data, headers=ЗАГОЛОВКИ)


# --- заморозка пространства: кто -------------------------------------------------


@pytest.mark.parametrize("клиент", ["главный", "админ_уК"])
def test_ведущий_пространства_замораживает_и_размораживает(
    клиент: str, зовы: dict[str, list[Any]], request: pytest.FixtureRequest
) -> None:
    c = request.getfixturevalue(клиент)

    assert _post(c, "/users/spaces/freeze", code="GE").status_code == 200
    assert _post(c, "/users/spaces/unfreeze", code="GE").status_code == 200

    assert [x[0] for x in зовы["freeze"]] == ["GE"]
    assert зовы["unfreeze"] == ["GE"]


@pytest.mark.parametrize("клиент", ["админ_GE", "контроль"])
def test_остальные_заморозить_и_разморозить_не_могут(
    клиент: str, зовы: dict[str, list[Any]], request: pytest.FixtureRequest
) -> None:
    c = request.getfixturevalue(клиент)

    assert _post(c, "/users/spaces/freeze", code="GE").status_code == 403
    assert _post(c, "/users/spaces/unfreeze", code="GE").status_code == 403

    assert зовы["freeze"] == [] and зовы["unfreeze"] == [], "заморозка прошла мимо права"


def test_ук_заморозить_нельзя(главный: FlaskClient, зовы: dict[str, list[Any]]) -> None:
    assert _post(главный, "/users/spaces/freeze", code="HQ").status_code == 403
    assert _post(главный, "/users/spaces/freeze", code="NOPE").status_code == 403
    assert зовы["freeze"] == []


def test_кнопка_заморозки_есть_у_ведущего(главный: FlaskClient) -> None:
    html = главный.get("/administration?tab=spaces&space_code=GE").get_data(as_text=True)

    assert 'action="/users/spaces/freeze' in html


def test_кнопки_заморозки_нет_у_админа_партнёра(админ_GE: FlaskClient) -> None:
    html = админ_GE.get("/administration?tab=spaces&space_code=GE").get_data(as_text=True)

    assert "/spaces/freeze" not in html and "/spaces/unfreeze" not in html


def test_замороженное_показывает_кто_и_кнопку_разморозки(
    главный: FlaskClient, зовы: dict[str, list[Any]]
) -> None:
    зовы["_frozen"][0]["GE"] = partner_spaces.FrozenSpace(
        "GE", datetime(2026, 11, 12, 9, 0, tzinfo=UTC), "kostya", 2
    )

    html = главный.get("/administration?tab=spaces&space_code=GE").get_data(as_text=True)

    assert 'action="/users/spaces/unfreeze' in html
    assert "kostya" in html
    assert 'action="/users/spaces/freeze' not in html


def test_заведение_в_замороженном_пространстве_отказ(
    главный: FlaskClient, зовы: dict[str, list[Any]]
) -> None:
    зовы["_frozen"][0]["GE"] = partner_spaces.FrozenSpace(
        "GE", datetime(2026, 11, 12, tzinfo=UTC), None, 2
    )

    ответ = _post(главный, "/users/add", login="newbie", tenant="GE", role="auditor")

    assert ответ.status_code == 409
    assert зовы["add"] == []


# --- события: кто видит и кто отмечает -------------------------------------------


@pytest.mark.parametrize("клиент", ["главный", "админ_уК"])
def test_ведущий_видит_событие_и_отмечает(
    клиент: str, зовы: dict[str, list[Any]], request: pytest.FixtureRequest
) -> None:
    c = request.getfixturevalue(клиент)

    html = c.get("/administration?tab=people&lang=ru").get_data(as_text=True)
    assert "nino-new" in html and "GE" in html and "kostya" in html
    assert 'action="/users/events/seen' in html

    assert _post(c, "/users/events/seen", event="7").status_code == 200
    assert зовы["seen"] == [7]


def test_админ_партнёра_блока_не_видит_и_отметить_не_может(
    админ_GE: FlaskClient, зовы: dict[str, list[Any]]
) -> None:
    html = админ_GE.get("/administration?tab=people&lang=ru").get_data(as_text=True)
    assert "nino-new" not in html and "/users/events/seen" not in html

    assert _post(админ_GE, "/users/events/seen", event="7").status_code == 403
    assert зовы["seen"] == []


def test_контроль_отметить_не_может(контроль: FlaskClient, зовы: dict[str, list[Any]]) -> None:
    assert _post(контроль, "/users/events/seen", event="7").status_code == 403
    assert зовы["seen"] == []
