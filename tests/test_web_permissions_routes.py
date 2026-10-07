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


def test_маршруты_своего_пространства_объявили_код() -> None:
    app = собрать(tenant="HQ")
    ожидание = {
        "methodology_add": ("checklist.edit",),
        "methodology_publish": ("checklist.publish",),
        "checklists_create": ("checklist.manage",),
        "methodology_bot": ("checklist.manage",),
        "rx_send": ("prescription.manage",),
        "order_reply": ("prescription.reply",),
        "actions_new": ("plan.manage",),
        "plans_upload": ("plan.submit",),
        "unit_create": ("unit.create",),
    }
    for эндпоинт, коды in ожидание.items():
        assert getattr(app.view_functions[эндпоинт], guard.ACTIONS_ATTR, ()) == коды, эндпоинт
