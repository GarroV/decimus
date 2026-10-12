"""Общий заслон источника: любая запись в админку — только со своей страницы.

До 12.10.2026 каждый POST звал `refuse_foreign_origin` сам, и маршрут, который
забыл это сделать, был открыт чужой странице молча (аудит доступа, п.6).
Здесь заводится как раз такой «забывчивый» маршрут."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from flask.testing import FlaskClient
from web_harness import войти, подменить_двери, собрать

ПРОБА = "/__probe"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant="HQ", role="admin")
    app = собрать(tenant="HQ")
    # Маршрут без собственной проверки источника — то, что заслон и ловит.
    app.add_url_rule(ПРОБА, "probe", lambda: "записано", methods=["POST"])
    with app.test_client() as c:
        assert войти(c).status_code == 302
        yield c


def test_чужая_страница_получает_отказ(client: FlaskClient) -> None:
    ответ = client.post(ПРОБА, headers={"Origin": "https://evil.example"})
    assert ответ.status_code == 403


def test_без_origin_и_referer_отказ(client: FlaskClient) -> None:
    assert client.post(ПРОБА).status_code == 403


def test_понижение_схемы_отказ(client: FlaskClient) -> None:
    ответ = client.post(
        ПРОБА, headers={"Origin": "http://localhost:80", "X-Forwarded-Proto": "https"}
    )
    assert ответ.status_code == 403


def test_своя_страница_проходит(client: FlaskClient) -> None:
    ответ = client.post(ПРОБА, headers={"Origin": "http://localhost"})
    assert ответ.status_code == 200
    assert ответ.get_data(as_text=True) == "записано"


def test_api_сервисов_мимо_заслона(client: FlaskClient) -> None:
    """API опознаёт ключ, а не куку: его POST не 403 заслона, а 405 — записи нет."""
    assert client.post("/api/v1/ratings/scores").status_code == 405
