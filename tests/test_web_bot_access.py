"""Волна 3: блок и панель «Доступ в боте» на «Методике».

Сторожат то, чья ошибка молчит: маршрут переключателя под входом и под
заслоном чужого источника; заслоны двери доезжают до экрана текстом, а не
пятисоткой; при нуле открытых блок предупреждает, а не пустеет.
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


def test_без_входа_переключатель_не_работает(клиент: FlaskClient) -> None:
    ответ = клиент.post("/admin/bot/bizdev", data={"on": "0"})

    assert ответ.status_code == 302
    assert auth.LOGIN_PATH in (ответ.headers.get("Location") or "")


def test_панель_показывает_доступ_и_причину_у_черновика(клиент: FlaskClient) -> None:
    войти(клиент)
    клиент.post(
        "/admin/checklists",
        data={"code": "rnd", "name_ru": "Аудит РНД", "name_en": "RnD audit"},
        headers={"Origin": СВОЙ},
    )

    страница = клиент.get("/admin?panel=bot").get_data(as_text=True)

    assert "Доступ в боте" in страница
    assert 'action="/admin/bot/bizdev' in страница
    assert 'action="/admin/bot/rnd' not in страница, "черновик в бот не открывается — формы нет"
    assert "черновик" in страница


def test_выключить_последний_и_блок_предупреждает(клиент: FlaskClient) -> None:
    войти(клиент)

    ответ = клиент.post("/admin/bot/bizdev", data={"on": "0"}, headers={"Origin": СВОЙ})

    assert ответ.status_code == 302
    assert "panel=bot" in (ответ.headers.get("Location") or "")
    страница = клиент.get("/admin").get_data(as_text=True)
    assert "Бот сейчас не даст начать проверку" in страница


def test_черновик_открыть_в_боте_нельзя_и_экран_говорит_почему(клиент: FlaskClient) -> None:
    войти(клиент)
    клиент.post(
        "/admin/checklists",
        data={"code": "rnd", "name_ru": "Аудит РНД", "name_en": "RnD audit"},
        headers={"Origin": СВОЙ},
    )

    ответ = клиент.post("/admin/bot/rnd", data={"on": "1"}, headers={"Origin": СВОЙ})

    assert ответ.status_code == 200
    текст = ответ.get_data(as_text=True)
    assert "rnd" in текст and ("черновик" in текст or "нарушение" in текст)
    строки = {r.code: r for r in method.checklist_rail(method.load_store().store, tenant=ТЕНАНТ)}  # type: ignore[arg-type]
    assert строки["rnd"].in_bot is False


def test_чужой_источник_переключатель_не_принимает(клиент: FlaskClient) -> None:
    войти(клиент)

    ответ = клиент.post(
        "/admin/bot/bizdev", data={"on": "0"}, headers={"Origin": "https://evil.example"}
    )

    assert ответ.status_code in (400, 403)
    строки = {r.code: r for r in method.checklist_rail(method.load_store().store, tenant=ТЕНАНТ)}  # type: ignore[arg-type]
    assert строки["bizdev"].in_bot is True


def test_английский_интерфейс_отвечает_своими_словами(клиент: FlaskClient) -> None:
    войти(клиент)

    страница = клиент.get("/admin?panel=bot&lang=en").get_data(as_text=True)

    assert "Bot access" in страница
    assert "Доступ в боте" not in страница


def _опубликовать(store: Any, **правка: Any) -> None:
    from datetime import date

    from src.mcp.checklist import apply_change, publish

    итог = apply_change(store, tenant=ТЕНАНТ, today=date(2026, 9, 28), **правка)
    assert итог.accepted and итог.version is not None, итог
    publish(store, tenant=ТЕНАНТ, version=итог.version)


def test_открытый_с_пустым_изданием_не_считается_открытым_и_снимается(
    клиент: FlaskClient,
) -> None:
    """Флаг поднят, а издание потом опубликовали пустым: блок не врёт, флаг снимается."""
    from dataclasses import replace

    from src.mcp.checklists import set_bot_access, set_state

    войти(клиент)
    клиент.post("/admin/bot/bizdev", data={"on": "0"}, headers={"Origin": СВОЙ})
    клиент.post(
        "/admin/checklists",
        data={"code": "rnd", "name_ru": "Аудит РНД", "name_en": "RnD audit"},
        headers={"Origin": СВОЙ},
    )
    rnd = replace(method.load_store().store, code="rnd")  # type: ignore[type-var]
    _опубликовать(
        rnd,
        tool="add_checklist_item",
        command="add",
        options={
            "id": "RND01",
            "process": "Проба",
            "question-ru": "Проба пера",
            "levels": "D1",
            "zones": "all",
            "days": 5,
            "criteria": "D1: проба",
        },
    )
    set_state(rnd, tenant=ТЕНАНТ, state="active")
    set_bot_access(rnd, tenant=ТЕНАНТ, on=True)
    _опубликовать(
        rnd, tool="remove_checklist_item", command="remove", positional="RND01", options={}
    )

    строка = {r.code: r for r in method.checklist_rail(method.load_store().store, tenant=ТЕНАНТ)}[
        "rnd"
    ]  # type: ignore[arg-type]
    assert строка.wants_bot is True and строка.in_bot is False
    страница = клиент.get("/admin?panel=bot").get_data(as_text=True)
    assert "Бот сейчас не даст начать проверку" in страница, "блок посчитал пустой открытым"
    assert "бот его не даёт" in страница
    assert 'action="/admin/bot/rnd' in страница, "застрявший флаг обязан сниматься"

    клиент.post("/admin/bot/rnd", data={"on": "0"}, headers={"Origin": СВОЙ})

    строка = {r.code: r for r in method.checklist_rail(method.load_store().store, tenant=ТЕНАНТ)}[
        "rnd"
    ]  # type: ignore[arg-type]
    assert строка.wants_bot is False
