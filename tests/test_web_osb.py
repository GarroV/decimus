# ruff: noqa: F811 — фикстуры стенда приходят импортом из test_web_prescriptions
"""Страница «ОСБ» и записи предписаний: кто что видит и кому отказывает заслон (D599–D608).

Ядро — заслоны: согласовать, вернуть, отправить и закрыть могут ОСБ и главный
админ; админ страницу видит, но без кнопок и записей; девелопер страницы не
видит вовсе и только запрашивает предписание. Двери блока `db` подменены, что
держит база, проверяет `tests/test_db_prescriptions_review.py`.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from flask.testing import FlaskClient
from test_web_prescriptions import (  # noqa: F401
    ORIGIN,
    ИД,
    ФОРМА,
    _куда,
    _стенд,
    девелопер,
    зовы,
    партнёр,
    уК,
)

ЗАПИСИ_ВЕДЕНИЯ = ("approve", "return", "send", "close")


@pytest.fixture
def админ(monkeypatch: pytest.MonkeyPatch, зовы: Any) -> Iterator[FlaskClient]:
    yield from _стенд(monkeypatch, "HQ", "admin")


@pytest.mark.parametrize("клиент", ["админ", "девелопер"])
@pytest.mark.parametrize("шаг", ЗАПИСИ_ВЕДЕНИЯ)
def test_вести_предписание_без_права_нельзя(
    клиент: str, шаг: str, зовы: dict[str, list[Any]], request: pytest.FixtureRequest
) -> None:
    c: FlaskClient = request.getfixturevalue(клиент)
    ответ = c.post(f"/actions/prescriptions/{ИД}/{шаг}", data=ФОРМА, headers=ORIGIN)
    assert ответ.status_code == 403
    assert зовы["approve"] == зовы["return"] == зовы["issue"] == зовы["close"] == []


def test_осб_видит_страницу_и_кнопки_ведения(уК: FlaskClient) -> None:
    ответ = уК.get("/osb?queue=drafts")
    страница = ответ.get_data(as_text=True)
    assert ответ.status_code == 200
    assert "/actions/prescriptions/new" in страница


def test_админ_видит_страницу_без_кнопок(админ: FlaskClient) -> None:
    ответ = админ.get("/osb?queue=drafts")
    страница = ответ.get_data(as_text=True)
    assert ответ.status_code == 200
    assert "/actions/prescriptions/new" not in страница
    assert f"/actions/prescriptions/{ИД}/approve" not in страница


def test_девелопер_страницы_осб_не_видит(девелопер: FlaskClient) -> None:
    assert девелопер.get("/osb").status_code == 404


def test_партнёру_страница_осб_закрыта(партнёр: FlaskClient) -> None:
    assert партнёр.get("/osb").status_code == 404


def test_вкладка_предписаний_действий_ведёт_в_осб(админ: FlaskClient) -> None:
    ответ = админ.get("/actions?tab=prescriptions")
    assert ответ.status_code == 303
    assert _куда(ответ)[0] == "/osb"


def test_девелопер_запрашивает_но_без_основания_не_создаёт(
    девелопер: FlaskClient, зовы: dict[str, list[Any]]
) -> None:
    ответ = девелопер.post(
        "/actions/prescriptions", data={**ФОРМА, "then": "request"}, headers=ORIGIN
    )
    assert ответ.status_code in (200, 400, 422)
    assert зовы["create"] == []


def test_очередь_согласовано_показывает_ровно_столько_сколько_в_счётчике(
    уК: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test_web_prescriptions import предписание

    from src.db import prescriptions as rx

    monkeypatch.setattr(
        rx,
        "list_prescriptions",
        lambda **_k: rx.PrescriptionList(rows=(предписание(status="approved"),), truncated=False),
    )
    страница = уК.get("/osb?queue=approved").get_data(as_text=True)
    assert "не отправлено · 1" in страница
    assert "в списке: 1" in страница
    assert "Ничего не" not in страница


def test_без_выбора_открывается_первая_непустая_очередь(
    уК: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test_web_prescriptions import предписание

    from src.db import prescriptions as rx

    monkeypatch.setattr(
        rx,
        "list_prescriptions",
        lambda **_k: rx.PrescriptionList(rows=(предписание(status="approved"),), truncated=False),
    )
    страница = уК.get("/osb").get_data(as_text=True)
    assert "в списке: 1" in страница
    assert "Ничего не" not in страница
