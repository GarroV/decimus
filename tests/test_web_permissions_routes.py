"""Маршруты своего пространства спрашивают can — по таблице ролей (D310, D311)."""

from __future__ import annotations

from typing import Any

import pytest
from flask.testing import FlaskClient
from web_harness import СВОЙ, войти, подменить_двери, собрать

from src.web import guard
from src.web import methodology as method

МЕТОДИКА = ("/admin/items", "/admin/zones", "/admin/route", "/admin/scoring", "/admin/publish")


def _клиент(monkeypatch: pytest.MonkeyPatch, *, tenant: str, role: str) -> FlaskClient:
    подменить_двери(monkeypatch, tenant=tenant, role=role)
    client = собрать(tenant="HQ").test_client()
    assert войти(client).status_code == 302
    return client


@pytest.mark.parametrize("путь", МЕТОДИКА)
def test_сотрудник_страны_не_правит_методику(monkeypatch: pytest.MonkeyPatch, путь: str) -> None:
    клиент = _клиент(monkeypatch, tenant="GE", role="auditor")
    assert клиент.post(путь, headers={"Origin": СВОЙ}).status_code == 403


@pytest.mark.parametrize("путь", МЕТОДИКА)
def test_сотрудник_уК_правит_методику(monkeypatch: pytest.MonkeyPatch, путь: str) -> None:
    # Хранилище методики не задано (autouse-фикстура conftest): заслон пропустил,
    # и вид ответил своей страницей «не настроено» — 200, а не отказ.
    клиент = _клиент(monkeypatch, tenant="HQ", role="auditor")
    assert клиент.post(путь, headers={"Origin": СВОЙ}).status_code == 200


def test_админ_страны_заводит_чек_лист_в_своём_пространстве(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    заведено: list[dict[str, Any]] = []

    def завести(_store: Any, **kw: Any) -> Any:
        заведено.append(kw)
        return type("Заведён", (), {"code": kw["code"]})()

    monkeypatch.setattr(method, "load_store", lambda: type("С", (), {"store": object()})())
    monkeypatch.setattr(method, "create_checklist", завести)
    # После заведения вид рисует перечень (`_render_checklists`) — он читает
    # хранилище, а здесь вместо него заглушка.
    monkeypatch.setattr(method, "checklists_overview", lambda *_a, **_k: [])
    клиент = _клиент(monkeypatch, tenant="GE", role="admin")
    ответ = клиент.post(
        "/admin/checklists",
        data={"code": "ge_audit", "name_ru": "Аудит GE", "name_en": "GE audit"},
        headers={"Origin": СВОЙ},
    )
    assert ответ.status_code == 200
    assert [з["tenant"] for з in заведено] == ["GE"]


def test_сотрудник_страны_чек_лист_не_заводит(monkeypatch: pytest.MonkeyPatch) -> None:
    клиент = _клиент(monkeypatch, tenant="GE", role="auditor")
    ответ = клиент.post("/admin/checklists", data={"code": "x"}, headers={"Origin": СВОЙ})
    assert ответ.status_code == 403


#: Единственная таблица «эндпоинт → код»: 25 маршрутов блока (Task 8).
КОДЫ: dict[str, str] = {
    **dict.fromkeys(
        (
            "methodology_add",
            "methodology_edit",
            "methodology_disable",
            "methodology_restore",
            "methodology_zone_add",
            "methodology_zone_shares",
            "methodology_zone_rename",
            "methodology_zone_remove",
            "methodology_route",
            "methodology_scoring",
        ),
        "checklist.edit",
    ),
    "methodology_publish": "checklist.publish",
    **dict.fromkeys(
        ("checklists_create", "checklists_state", "methodology_bot", "checklists_apply"),
        "checklist.manage",
    ),
    **dict.fromkeys(("rx_create", "rx_update", "rx_send", "rx_close"), "prescription.manage"),
    "order_reply": "prescription.reply",
    **dict.fromkeys(("actions_review", "actions_due", "actions_new"), "plan.manage"),
    "plans_upload": "plan.submit",
    "unit_create": "unit.create",
}


def test_таблица_кодов_полна() -> None:
    assert len(КОДЫ) == 25


@pytest.mark.parametrize("эндпоинт", sorted(КОДЫ))
def test_маршрут_объявил_свой_код(эндпоинт: str) -> None:
    app = собрать(tenant="HQ")
    объявлено = getattr(app.view_functions[эндпоинт], guard.ACTIONS_ATTR, ())
    assert объявлено == (КОДЫ[эндпоинт],), эндпоинт


@pytest.mark.parametrize(
    "путь", ("/admin/checklists/x/state", "/admin/checklists/x/apply", "/admin/bot/x")
)
def test_сотрудник_страны_не_управляет_чек_листами(
    monkeypatch: pytest.MonkeyPatch, путь: str
) -> None:
    клиент = _клиент(monkeypatch, tenant="GE", role="auditor")
    assert клиент.post(путь, headers={"Origin": СВОЙ}).status_code == 403
