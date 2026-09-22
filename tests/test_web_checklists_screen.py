"""T347: экраны чек-листов — перечень, заведение с нуля, состояние, применение.

Что здесь предмет проверки, а что нет. Разметку глазами эти тесты не сторожат.
Сторожат они то, чья ошибка молчит:

* без входа раздел не открывается — это отдельный реестр маршрутов, и забыть
  вписать его в заслон легко;
* заведение с экрана даёт ЧЕРНОВИК, а не готовый к употреблению чек-лист;
* применение к проду идёт через показ разницы, и заслоны двери доезжают до
  страницы текстом, а не пятисоткой (пустой чек-лист даёт 100% и высшую
  оценку — #339);
* оба языка интерфейса отвечают ключами `checklists.*`, а не заглушкой.

Хранилище настоящее (файлы на `tmp_path`, движок подпроцессом) — как и в
соседнем наборе экранов методики.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from flask.testing import FlaskClient
from mcp_checklist_harness import build_edition
from web_harness import СВОЙ, войти, подменить_двери, собрать

from src.web import auth
from src.web import methodology as method

ТЕНАНТ = "default"


@pytest.fixture
def двери(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    return подменить_двери(monkeypatch, tenant=ТЕНАНТ)


@pytest.fixture
def клиент(
    monkeypatch: pytest.MonkeyPatch, двери: dict[str, list[Any]], tmp_path: Path
) -> Iterator[FlaskClient]:
    методика = tmp_path / "живая-методика"
    build_edition(методика, name="imf", day="2026-09-01")
    monkeypatch.setenv(method.STORE_VAR, str(tmp_path / "хранилище"))
    monkeypatch.setenv(method.DATA_VAR, str(методика))
    with собрать(tenant=ТЕНАНТ).test_client() as client:
        yield client


def test_без_входа_чеклисты_не_открываются(клиент: FlaskClient) -> None:
    ответ = клиент.get("/admin/checklists")

    assert ответ.status_code == 302
    assert auth.LOGIN_PATH in (ответ.headers.get("Location") or "")


def test_перечень_показывает_чеклист_прода(клиент: FlaskClient) -> None:
    войти(клиент)

    страница = клиент.get("/admin/checklists").get_data(as_text=True)

    assert "bizdev" in страница
    assert "в проде" in страница


def test_заведение_с_экрана_даёт_черновик(клиент: FlaskClient) -> None:
    """Только что заведённый чек-лист не задаёт ни одного вопроса. Пометить его
    годным к употреблению значило бы предложить считать по нему проверку."""
    войти(клиент)

    ответ = клиент.post(
        "/admin/checklists",
        data={"code": "rnd", "name_ru": "Аудит РНД", "name_en": "RnD audit"},
        headers={"Origin": СВОЙ},
    )

    страница = ответ.get_data(as_text=True)
    assert ответ.status_code == 200
    assert "rnd" in страница and "Аудит РНД" in страница
    assert "черновик" in страница


def test_пустой_чеклист_к_проду_не_применяется_и_говорит_почему(клиент: FlaskClient) -> None:
    """Заслон двери (#339) доезжает до экрана текстом, а не пятисоткой: пустая
    методика даёт партнёру 100% и высшую оценку, не задав ни одного вопроса."""
    войти(клиент)
    клиент.post(
        "/admin/checklists",
        data={"code": "rnd", "name_ru": "Аудит РНД", "name_en": "RnD audit"},
        headers={"Origin": СВОЙ},
    )

    ответ = клиент.post("/admin/checklists/rnd/apply", headers={"Origin": СВОЙ})

    страница = ответ.get_data(as_text=True)
    assert ответ.status_code == 200
    assert "нет ни одного пункта" in страница
    assert "в проде" in страница


def test_разница_показывается_до_применения(клиент: FlaskClient) -> None:
    """Ролей нет (D182): ошибку применения ловит показ «сейчас вот этот, будет
    вот этот», а не право. Значит цифры обязаны быть на экране до кнопки."""
    войти(клиент)
    клиент.post(
        "/admin/checklists",
        data={"code": "rnd", "name_ru": "Аудит РНД", "name_en": "RnD audit"},
        headers={"Origin": СВОЙ},
    )

    страница = клиент.get("/admin/checklists/rnd/apply").get_data(as_text=True)

    assert "Сейчас в проде" in страница
    assert "Будет в проде" in страница
    assert "Вопросов с нарушениями" in страница


def test_состояние_меняется_с_экрана(клиент: FlaskClient) -> None:
    войти(клиент)
    клиент.post(
        "/admin/checklists",
        data={"code": "rnd", "name_ru": "Аудит РНД", "name_en": "RnD audit"},
        headers={"Origin": СВОЙ},
    )

    ответ = клиент.post(
        "/admin/checklists/rnd/state", data={"state": "active"}, headers={"Origin": СВОЙ}
    )

    assert ответ.status_code == 200
    assert "в работе" in ответ.get_data(as_text=True)


def test_применённый_к_проду_не_снимается_с_экрана(клиент: FlaskClient) -> None:
    """Иначе продукт считал бы по снятой методике."""
    войти(клиент)

    ответ = клиент.post(
        "/admin/checklists/bizdev/state", data={"state": "retired"}, headers={"Origin": СВОЙ}
    )

    assert "применён к проду" in ответ.get_data(as_text=True)


def test_экран_отвечает_на_английском(клиент: FlaskClient) -> None:
    """Язык — параметр, а не константа: раздел обязан говорить на обоих."""
    войти(клиент)

    страница = клиент.get("/admin/checklists?lang=en").get_data(as_text=True)

    assert "Checklists" in страница
    assert "in production" in страница
