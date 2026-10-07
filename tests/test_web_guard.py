"""Заслон прав веба: пишущий маршрут объявляет код и спрашивает can."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace

import pytest
from flask import Flask
from flask.testing import FlaskClient
from web_harness import СВОЙ, войти, подменить_двери, собрать

from src.web import guard


def _стенд(monkeypatch: pytest.MonkeyPatch, *, tenant: str, role: str) -> Flask:
    подменить_двери(monkeypatch, tenant=tenant, role=role)
    app = собрать(tenant="HQ")
    # `собрать` ставит TESTING=True, и Flask пробрасывает исключение вида и
    # `after_request` в тестовый клиент. Здесь проверяется ответ продукта — 500,
    # каким его увидит человек, — поэтому проброс выключен.
    app.config["PROPAGATE_EXCEPTIONS"] = False

    @app.post("/_t/own")
    @guard.action("checklist.edit")
    def _own() -> str:
        return "ok"

    @app.post("/_t/object/<tenant>/<author>")
    @guard.action("inspection.retract", object_in_route=True)
    def _object(tenant: str, author: str) -> str | tuple[str, int]:
        автор = None if author == "none" else author
        отказ = guard.permit("inspection.retract", tenant, object_author=автор)
        return отказ if отказ is not None else "ok"

    @app.post("/_t/no-author")
    @guard.action("inspection.retract", object_in_route=True)
    def _no_author() -> str | tuple[str, int]:
        отказ = guard.permit("inspection.retract", "HQ")
        return отказ if отказ is not None else "ok"

    @app.post("/_t/forgot")
    @guard.action("inspection.retract", object_in_route=True)
    def _forgot() -> str:
        return "записал без границы"

    @app.post("/_t/bare")
    def _bare() -> str:
        return "без кода"

    return app


@pytest.fixture
def вошедший(
    monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> Iterator[FlaskClient]:
    tenant, role = request.param
    with _стенд(monkeypatch, tenant=tenant, role=role).test_client() as client:
        assert войти(client).status_code == 302
        yield client


def _post(client: FlaskClient, путь: str) -> int:
    return client.post(путь, headers={"Origin": СВОЙ}).status_code


МОЙ = "22222222-2222-2222-2222-222222222222"


@pytest.mark.parametrize("вошедший", [("GE", "auditor")], indirect=True)
def test_сотрудник_страны_не_правит_методику(вошедший: FlaskClient) -> None:
    assert _post(вошедший, "/_t/own") == 403


@pytest.mark.parametrize("вошедший", [("GE", "admin")], indirect=True)
def test_админ_страны_правит_свою_методику(вошедший: FlaskClient) -> None:
    assert _post(вошедший, "/_t/own") == 200


@pytest.mark.parametrize("вошедший", [("HQ", "admin")], indirect=True)
def test_уК_действует_над_объектом_партнёра(вошедший: FlaskClient) -> None:
    assert _post(вошедший, "/_t/object/GE/none") == 200


@pytest.mark.parametrize("вошедший", [("GE", "admin")], indirect=True)
def test_страна_не_действует_над_объектом_уК(вошедший: FlaskClient) -> None:
    assert _post(вошедший, f"/_t/object/HQ/{МОЙ}") == 403


@pytest.mark.parametrize("вошедший", [("HQ", "auditor")], indirect=True)
def test_сотрудник_уК_действует_только_над_своим(вошедший: FlaskClient) -> None:
    assert _post(вошедший, f"/_t/object/HQ/{МОЙ}") == 200
    assert _post(вошедший, "/_t/object/HQ/u-other") == 403
    assert _post(вошедший, "/_t/object/HQ/none") == 403


@pytest.mark.parametrize("вошедший", [("HQ", "admin")], indirect=True)
def test_маршрут_с_объектом_без_permit_падает_500(вошедший: FlaskClient) -> None:
    assert _post(вошедший, "/_t/forgot") == 500


@pytest.mark.parametrize("вошедший", [("HQ", "admin")], indirect=True)
def test_действие_над_проверкой_без_автора_падает_500(вошедший: FlaskClient) -> None:
    assert _post(вошедший, "/_t/no-author") == 500


def test_незнакомый_код_падает_на_объявлении() -> None:
    with pytest.raises(ValueError, match=r"inspection\.delete"):
        guard.action("inspection.delete")


def test_действие_над_проверкой_требует_объекта_в_маршруте() -> None:
    with pytest.raises(ValueError, match="object_in_route"):
        guard.action("inspection.move")


def test_полнота_называет_маршрут_без_кода(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _стенд(monkeypatch, tenant="HQ", role="admin")
    assert "_bare (/_t/bare)" in guard.uncovered(app)
    assert not any(строка.startswith("_own ") for строка in guard.uncovered(app))


def test_учётка_без_id_получает_отказ_а_не_500(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.web import auth

    with _стенд(monkeypatch, tenant="HQ", role="admin").test_client() as client:
        assert войти(client).status_code == 302
        настоящий = auth.current_actor

        def без_id() -> object:
            return replace(настоящий(), user_id=None)

        monkeypatch.setattr(auth, "current_actor", без_id)
        assert _post(client, "/_t/own") == 403
        assert _post(client, "/_t/object/GE/none") == 403
