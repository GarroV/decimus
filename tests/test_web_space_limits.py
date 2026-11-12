"""D759 п.5 (#1670): раздел «Лимиты» карточки пространства — права и экран.

Правка лимитов — главный админ и админ УК; админ партнёра видит значения и расход на
чтение, ни сохранить, ни обойти формой (поддельный POST — 403) не может. Предупреждение
от 80 % потолка — только на экране. База подменена на границе модуля; настоящие запросы —
`tests/test_db_space_limits.py`.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from flask.testing import FlaskClient
from web_harness import СВОЙ, войти, подменить_двери, собрать

from src.db import bot_links, space_limits
from src.domain.space_limits import DEFAULTS, Limits, spend_level
from src.web import accounts, partner_spaces, space_limits_view
from src.web.space_limits_view import LimitView

ЗАГОЛОВКИ = {"Origin": СВОЙ}
ФОРМА = {"code": "GE", "inspections": "7", "spend": "123,45"}


def _вид(spent: str, cap: str | None = "50", *, default: bool = False) -> LimitView:
    лимиты = Limits(5, None if cap is None else Decimal(cap)) if not default else DEFAULTS
    return LimitView(
        code="GE",
        limits=лимиты,
        is_default=default,
        spent=Decimal(spent),
        partial=False,
        level=spend_level(Decimal(spent), лимиты.monthly_spend_usd),
        updated_by=None if default else "kostya",
        updated_at=None if default else datetime(2026, 11, 12, 9, 30, tzinfo=UTC),
    )


@pytest.fixture
def записи(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    сохранено: list[tuple[str, dict[str, Any]]] = []

    def set_limits(code: str, **kw: Any) -> Limits:
        сохранено.append((code, kw))
        return Limits(kw["inspections_per_unit"], kw["monthly_spend_usd"])

    monkeypatch.setattr(space_limits, "set_limits", set_limits)
    monkeypatch.setattr(accounts, "everyone", lambda *, tenant: ())
    monkeypatch.setattr(accounts, "spaces", lambda: ("GE", "HQ"))
    monkeypatch.setattr(
        partner_spaces,
        "overview",
        lambda: (
            partner_spaces.SpaceRow("GE", "Партнёр Г", ("GE",), 2),
            partner_spaces.SpaceRow("HQ", "", (), 4),
        ),
    )
    monkeypatch.setattr(bot_links, "live_bindings", dict)
    monkeypatch.setattr(space_limits_view, "build", lambda code, **_k: _вид("18.4"))
    return сохранено


def _стенд(monkeypatch: pytest.MonkeyPatch, *, tenant: str, role: str) -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant=tenant, role=role)
    with собрать(tenant="HQ").test_client() as client:
        assert войти(client).status_code == 302
        yield client


@pytest.fixture
def уК(monkeypatch: pytest.MonkeyPatch, записи: Any) -> Iterator[FlaskClient]:
    yield from _стенд(monkeypatch, tenant="HQ", role="admin")


@pytest.fixture
def партнёр(monkeypatch: pytest.MonkeyPatch, записи: Any) -> Iterator[FlaskClient]:
    yield from _стенд(monkeypatch, tenant="GE", role="admin")


КАРТОЧКА = "/administration?tab=spaces&space_code=GE&lang=ru"


def test_админ_ук_видит_форму_и_расход_словами(уК: FlaskClient) -> None:
    страница = уК.get(КАРТОЧКА).get_data(as_text=True)

    assert 'action="/users/spaces/limits' in страница
    assert "18,40 $ из 50 $ в этом месяце" in страница
    assert 'name="inspections"' in страница and 'name="spend"' in страница


def test_английский_экран_с_точкой_и_долларом_впереди(уК: FlaskClient) -> None:
    страница = уК.get(КАРТОЧКА.replace("lang=ru", "lang=en")).get_data(as_text=True)

    assert "$18.40 of $50 this month" in страница


def test_админ_уК_сохраняет_лимиты_запятая_как_точка(
    уК: FlaskClient, записи: list[tuple[str, dict[str, Any]]]
) -> None:
    ответ = уК.post("/users/spaces/limits", data=ФОРМА, headers=ЗАГОЛОВКИ)

    assert ответ.status_code == 200
    ((код, значения),) = записи
    assert код == "GE"
    assert значения["inspections_per_unit"] == 7
    assert значения["monthly_spend_usd"] == Decimal("123.45")
    assert значения["by"]  # кто менял — логин вошедшего


def test_пустые_поля_значат_без_лимита(
    уК: FlaskClient, записи: list[tuple[str, dict[str, Any]]]
) -> None:
    уК.post(
        "/users/spaces/limits",
        data={"code": "GE", "inspections": "", "spend": ""},
        headers=ЗАГОЛОВКИ,
    )

    ((_, значения),) = записи
    assert значения["inspections_per_unit"] is None and значения["monthly_spend_usd"] is None


@pytest.mark.parametrize("spend", ["много", "nan", "inf"])
def test_негодное_число_не_сохраняется_и_говорит_словами(
    уК: FlaskClient, записи: list[tuple[str, dict[str, Any]]], spend: str
) -> None:
    ответ = уК.post(
        "/users/spaces/limits",
        data={"code": "GE", "inspections": "5", "spend": spend},
        headers=ЗАГОЛОВКИ,
    )

    assert ответ.status_code == 400
    assert "Лимиты не сохранены" in ответ.get_data(as_text=True)
    assert записи == []


def test_админ_партнёра_поддельный_post_403_и_ничего_не_записано(
    партнёр: FlaskClient, записи: list[tuple[str, dict[str, Any]]]
) -> None:
    ответ = партнёр.post("/users/spaces/limits", data=ФОРМА, headers=ЗАГОЛОВКИ)

    assert ответ.status_code == 403
    assert записи == []


def test_админ_партнёра_видит_расход_но_формы_нет(партнёр: FlaskClient) -> None:
    страница = партнёр.get(КАРТОЧКА).get_data(as_text=True)

    assert "18,40 $ из 50 $ в этом месяце" in страница
    assert 'action="/users/spaces/limits' not in страница
    assert "Лимиты меняет главный админ или админ УК" in страница


def test_от_восьмидесяти_процентов_предупреждение_админу_партнёра_на_обеих_вкладках(
    партнёр: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(space_limits_view, "build", lambda code, **_k: _вид("41"))

    for адрес in ("/administration?tab=people&lang=ru", КАРТОЧКА):
        страница = партнёр.get(адрес).get_data(as_text=True)
        assert "больше 80 % месячного потолка" in страница, адрес


def test_до_восьмидесяти_процентов_предупреждения_нет(партнёр: FlaskClient) -> None:
    страница = партнёр.get("/administration?tab=people&lang=ru").get_data(as_text=True)

    assert "80 %" not in страница


def test_потолок_достигнут_админ_партнёра_читает_отказ_словами(
    партнёр: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(space_limits_view, "build", lambda code, **_k: _вид("50"))

    страница = партнёр.get("/administration?tab=people&lang=ru").get_data(as_text=True)

    assert "Месячный лимит расхода пространства исчерпан" in страница


def test_база_молчит_экран_говорит_а_не_рисует_нули(
    уК: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(space_limits_view, "build", lambda code, **_k: None)

    страница = уК.get(КАРТОЧКА).get_data(as_text=True)

    assert "Лимиты и расход не загрузились" in страница
    assert 'action="/users/spaces/limits' not in страница
