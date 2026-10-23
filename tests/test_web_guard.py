"""Заслон прав веба: каждый пишущий маршрут — через матрицу, разделы — по `view.*`.

Полнота — главное: пишущий маршрут без кода действия не должен существовать
молча. Он закрыт запретом по умолчанию (403), а этот набор называет его по имени.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from flask import Flask
from flask.testing import FlaskClient
from web_harness import СВОЙ, войти, подменить_двери, собрать

from src.domain.permissions import ACTION_CODES
from src.web import guard

ПУБЛИЧНЫЕ = {"admin_public_url": СВОЙ, "mcp_public_url": "https://mcp.example.test"}


@pytest.fixture
def app() -> Flask:
    # С публичными адресами ставится и OAuth (D417): его маршруты тоже в счёт.
    return собрать(tenant="HQ", **ПУБЛИЧНЫЕ)


def _клиент(
    monkeypatch: pytest.MonkeyPatch, app: Flask, *, tenant: str, role: str
) -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant=tenant, role=role)
    with app.test_client() as client:
        войти(client)
        yield client


def test_каждый_пишущий_маршрут_объявил_действие(app: Flask) -> None:
    assert guard.uncovered(app) == []


def test_объявленные_коды_все_из_каталога(app: Flask) -> None:
    for правило in app.url_map.iter_rules():
        коды = getattr(app.view_functions[правило.endpoint], guard.ACTIONS_ATTR, ())
        assert set(коды) <= ACTION_CODES, правило.endpoint


def test_исключения_существуют_в_приложении(app: Flask) -> None:
    """Исключение без маршрута — мёртвая строка, за которой может спрятаться новый."""
    есть = {п.endpoint for п in app.url_map.iter_rules()}
    assert set(guard.EXEMPT_ENDPOINTS) <= есть
    assert set(guard.ENDPOINT_VIEWS) <= есть
    assert set(guard.READ_BY_ACTION) <= есть


def test_полнота_ловит_маршрут_без_кода() -> None:
    """Прогон на сломанном приложении: новый POST без `action` обязан всплыть."""
    app = собрать(tenant="HQ")

    @app.post("/inspections/<inspection_id>/telepathy")
    def telepathy(inspection_id: str) -> str:
        return inspection_id

    assert guard.uncovered(app) == ["telepathy (/inspections/<inspection_id>/telepathy)"]


def test_маршрут_без_кода_закрыт_запретом_по_умолчанию(monkeypatch: pytest.MonkeyPatch) -> None:
    app = собрать(tenant="HQ")
    зовы: list[str] = []

    @app.post("/inspections/<inspection_id>/telepathy")
    def telepathy(inspection_id: str) -> str:
        зовы.append(inspection_id)
        return "ok"

    for client in _клиент(monkeypatch, app, tenant="HQ", role="superadmin"):
        ответ = client.post("/inspections/x/telepathy", headers={"Origin": СВОЙ})
    assert ответ.status_code == 403
    assert зовы == []


def test_маршрут_с_объектом_обязан_спросить_матрицу(monkeypatch: pytest.MonkeyPatch) -> None:
    app = собрать(tenant="HQ")

    @app.post("/inspections/<inspection_id>/forgot")
    @guard.action("inspection.accept", object_in_route=True)
    def forgot(inspection_id: str) -> str:
        return "записано без границы"

    app.config.update(PROPAGATE_EXCEPTIONS=True)
    for client in _клиент(monkeypatch, app, tenant="HQ", role="admin"):
        with pytest.raises(RuntimeError, match="не спросил матрицу"):
            client.post("/inspections/x/forgot", headers={"Origin": СВОЙ})


def test_объявление_без_кода_и_с_чужим_кодом_ошибка_сборки() -> None:
    with pytest.raises(ValueError, match="без кода"):
        guard.action()
    with pytest.raises(ValueError, match="object_in_route"):
        guard.action("checklist.edit", "checklist.master")
    with pytest.raises(Exception, match=r"inspection\.telepathy"):
        guard.action("inspection.telepathy")


@pytest.mark.parametrize(
    ("tenant", "role", "путь", "код"),
    [
        ("HQ", "control", "/inspections", 404),  # D420: проверок у контроля нет
        ("HQ", "control", "/ratings", 200),
        ("HQ", "guest", "/admin", 404),  # гостю методики нет (D440)
        ("HQ", "guest", "/inspections", 200),
        ("HQ", "control", "/units/u1", 404),  # карточка пиццерии — история проверок
    ],
)
def test_разделы_по_матрице(
    monkeypatch: pytest.MonkeyPatch,
    app: Flask,
    tenant: str,
    role: str,
    путь: str,
    код: int,
) -> None:
    from src.web import inspections as data
    from src.web import ratings as ratings_screen

    monkeypatch.setattr(data, "load_registry", lambda **_: data.Registry((), True))
    monkeypatch.setattr(ratings_screen, "render_summary", lambda *_a, **_k: "<p>сводка</p>")
    for client in _клиент(monkeypatch, app, tenant=tenant, role=role):
        ответ = client.get(путь)
    assert ответ.status_code == код, ответ.get_data(as_text=True)[:300]


@pytest.mark.parametrize(
    ("role", "путь"),
    [
        ("guest", "/users/add"),
        ("guest", "/admin/items"),
        ("guest", "/inspections/x/retract"),
        ("control", "/admin/items"),
        ("control", "/users/role"),
        ("developer", "/users/add"),
        ("developer", "/admin/checklists/hq/apply"),
    ],
)
def test_запись_без_клетки_403_до_маршрута(
    monkeypatch: pytest.MonkeyPatch, app: Flask, role: str, путь: str
) -> None:
    for client in _клиент(monkeypatch, app, tenant="HQ", role=role):
        ответ = client.post(путь, headers={"Origin": СВОЙ})
    assert ответ.status_code == 403


def test_свои_дела_открыты_гостю(monkeypatch: pytest.MonkeyPatch, app: Flask) -> None:
    """Свой пароль — не запись в сеть: гость меняет его сам (ответ формы, не 403)."""
    for client in _клиент(monkeypatch, app, tenant="HQ", role="guest"):
        ответ = client.post("/users/password", data={}, headers={"Origin": СВОЙ})
    assert ответ.status_code != 403


@pytest.mark.parametrize("role", ["admin", "control", "guest"])
def test_скрытый_экран_отвечает_404(monkeypatch: pytest.MonkeyPatch, app: Flask, role: str) -> None:
    """Ключи API — экран главного админа: остальным его снаружи нет вовсе (404)."""
    for client in _клиент(monkeypatch, app, tenant="HQ", role=role):
        ответ = client.post("/users/connections/issue", headers={"Origin": СВОЙ})
    assert ответ.status_code == 404


# --- Граница пространств выводится из объявлений (аудит 12.10, F-004) ---------

ПАРТНЁР = "GE"


def _ок() -> str:
    return "ok"


@pytest.mark.parametrize("публичные", [{}, ПУБЛИЧНЫЕ], ids=["стенд", "с публичными адресами"])
def test_каждый_маршрут_объявлен_в_матрице(публичные: dict[str, str]) -> None:
    """Маршрут, который матрица не объявила ничем, партнёру закрыт — и назван здесь."""
    assert guard.undeclared(собрать(tenant="HQ", **публичные)) == []


def test_полнота_ловит_необъявленный_маршрут() -> None:
    """Прогон на сломанном приложении: новый GET вне разделов без объявления обязан всплыть."""
    app = собрать(tenant="HQ")
    app.add_url_rule("/zzz-new", endpoint="zzz_new", view_func=_ок)
    assert guard.undeclared(app) == ["zzz_new (/zzz-new)"]


@pytest.mark.parametrize(("tenant", "ожидание"), [(ПАРТНЁР, 404), ("HQ", 200)])
def test_необъявленный_маршрут_партнёру_закрыт_УК_открыт(
    monkeypatch: pytest.MonkeyPatch, tenant: str, ожидание: int
) -> None:
    подменить_двери(monkeypatch, tenant=tenant, role="admin")
    app = собрать(tenant=tenant)
    app.add_url_rule("/zzz-new", endpoint="zzz_new", view_func=_ок)
    with app.test_client() as client:
        войти(client)
        assert client.get("/zzz-new").status_code == ожидание


def test_маршрут_с_действием_только_УК_партнёру_закрыт_и_вне_префикса(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Граница — по коду матрицы, а не по пути: префикс раздела тут ни при чём."""
    from src.web import inspections as data

    подменить_двери(monkeypatch, tenant=ПАРТНЁР, role="admin")
    monkeypatch.setattr(data, "load_dated", lambda **_: ())
    app = собрать(tenant=ПАРТНЁР)
    app.add_url_rule("/zzz-hq", endpoint="zzz_hq", view_func=guard.action("unit.create")(_ок))
    with app.test_client() as client:
        войти(client)
        assert client.get("/zzz-hq").status_code == 404
        assert client.get("/calendar").status_code == 200  # объявленный раздел открыт


def test_разделы_только_УК_партнёру_закрыты_по_матрице() -> None:
    app = собрать(tenant="HQ", **ПУБЛИЧНЫЕ)
    закрытые = {
        rule.endpoint
        for rule in app.url_map.iter_rules()
        if not guard.open_to_tenant(app, rule.endpoint, rule.rule, ПАРТНЁР)
    }
    assert {"unit_new", "unit_create"} <= закрытые
    # «Действия» (D526) открыты партнёру, а запись УК в них — нет: 404, не 403.
    assert {
        "actions_review",
        "actions_due",
        "actions_new",
        "plan_accept",
        "plan_return",
        "plan_row_confirm",
        "plan_row_reject",
        "plan_count_from",
        "rx_create",
        "rx_update",
        "rx_send",
        "rx_close",
    } <= закрытые
    assert not закрытые & {
        "actions",
        "plans_upload",
        "plan_row_save",
        "plan_submit",
        "plan_row_start",
        "plan_row_done",
        "order_reply",
        "plan_file",
        "order_file",
        "plans",
        "orders",
        "order",
        "plan_file_legacy",
        "order_file_legacy",
    }
    # «Страна» (D508) открыта партнёру; заведение пиццерии под ней — по-прежнему нет.
    assert not закрытые & {
        "country",
        "country_index",
        "overview",
        "registry",
        "card",
        "ratings",
        "settings_page",
        "home",
    }
