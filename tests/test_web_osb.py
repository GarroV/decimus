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


def _строки(monkeypatch: pytest.MonkeyPatch) -> None:
    """Три открытых: в Грузии согласовано и действует, в Польше — на согласовании."""
    from dataclasses import replace

    from test_web_prescriptions import предписание

    from src.db import prescriptions as rx

    строки = (
        replace(предписание(status="approved"), id="a" * 32, subject="Согласованное ГЕ"),
        replace(предписание(status="issued"), id="b" * 32, subject="Действующее ГЕ"),
        replace(
            предписание(status="review"), id="c" * 32, country="PL", subject="На согласовании ПЛ"
        ),
    )
    monkeypatch.setattr(
        rx,
        "list_prescriptions",
        lambda **_k: rx.PrescriptionList(rows=строки, truncated=False),
    )


def test_осб_слева_столбец_стран_со_счётчиками(
    уК: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _строки(monkeypatch)
    страница = уК.get("/osb?lang=ru").get_data(as_text=True)
    столбец = страница.split('class="pk-rail', 1)[1].split("</aside>", 1)[0]
    assert "Все страны" in столбец
    assert "Грузия" in столбец and "Польша" in столбец
    assert "согласовано 1" in столбец and "действуют 1" in столбец
    assert "на согласовании 1" in столбец


def test_осб_справа_блоки_по_состоянию_и_закрытые_свёрнуты(
    уК: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _строки(monkeypatch)
    страница = уК.get("/osb?lang=ru").get_data(as_text=True)
    справа = страница.split('class="pk-work"', 1)[1]
    порядок = [
        справа.index(x) for x in ("На согласовании", "Согласовано, не отправлено", "Действуют")
    ]
    assert порядок == sorted(порядок)
    assert "Согласованное ГЕ" in справа and "Действующее ГЕ" in справа
    assert "Черновики" not in справа, "пустой блок не рисуется"
    assert 'class="pk-archive"' in справа and "closed=1" in справа


def test_осб_страна_из_столбца_оставляет_только_свои_строки(
    уК: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _строки(monkeypatch)
    страница = уК.get("/osb?country=PL&lang=ru").get_data(as_text=True)
    справа = страница.split('class="pk-work"', 1)[1]
    assert "На согласовании ПЛ" in справа
    assert "Действующее ГЕ" not in справа and "Согласованное ГЕ" not in справа
    # Кнопка «Новое предписание» несёт выбранную страну.
    assert "/actions/prescriptions/new?country=PL" in справа


def test_осб_столбец_стран_есть_и_при_одной_стране(
    уК: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test_web_prescriptions import предписание

    from src.db import prescriptions as rx

    monkeypatch.setattr(
        rx,
        "list_prescriptions",
        lambda **_k: rx.PrescriptionList(rows=(предписание(status="approved"),), truncated=False),
    )
    страница = уК.get("/osb?lang=ru").get_data(as_text=True)
    assert 'class="pk-rail' in страница and "Все страны" in страница


def test_осб_без_ряда_чипов_и_вкладок_очередей(
    уК: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _строки(monkeypatch)
    страница = уК.get("/osb?lang=ru").get_data(as_text=True)
    assert "spill" not in страница and "ov-chip" not in страница
    assert "sbar" not in страница and "stabs" not in страница


def test_осб_на_телефоне_страны_выпадающим_списком(
    уК: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _строки(monkeypatch)
    страница = уК.get("/osb?country=GE&lang=ru").get_data(as_text=True)
    форма = страница.split('class="pk-rail-select"', 1)[1].split("</form>", 1)[0]
    assert "<select" in форма and 'name="country"' in форма
    assert 'value="GE" selected' in форма
    assert "data-autosubmit-button" in форма, "без скрипта выбор уходит кнопкой"


def test_форма_предписания_страна_выпадающим_списком(уК: FlaskClient) -> None:
    страница = уК.get("/actions/prescriptions/new?lang=ru").get_data(as_text=True)
    assert 'class="rx-country"' in страница and 'name="country"' in страница
    assert "ov-chip" not in страница
