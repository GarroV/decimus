# ruff: noqa: F811 — фикстура стенда приходит импортом из test_web_app
"""Ряд действий в шапке карточки проверки: кто какую кнопку видит.

Права считает `_card_context`; здесь проверяется, что шаблон показывает кнопку
только при праве и что внизу карточки не осталось прежних разделов-форм.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from flask.testing import FlaskClient
from test_web_app import карточка, стенд, шапка  # noqa: F401

from src.web import action_plans
from src.web import inspections as data

АДРЕС = "/inspections/11111111-1111-1111-1111-111111111111?lang=ru"


def _открыть(стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch, *, уК: bool) -> str:
    деталь = карточка(шапка())
    monkeypatch.setattr(data, "load_card", lambda *_a, **_k: деталь)
    monkeypatch.setattr(data, "load_moves", lambda *_a, **_k: ())
    monkeypatch.setattr(data, "load_units", lambda **_: (("u1", "Demo Pizzeria #1"),))
    monkeypatch.setattr(data, "load_report", lambda *_a, **_k: SimpleNamespace(id="r"))
    monkeypatch.setattr(action_plans, "is_hq", lambda: уК)
    monkeypatch.setattr(action_plans, "card_plan", lambda *_a, **_k: (None, True))
    ответ = стенд.get(АДРЕС)
    assert ответ.status_code == 200
    return ответ.get_data(as_text=True)


@pytest.mark.parametrize("стенд", ["admin"], indirect=True)
def test_админ_уК_видит_весь_ряд_и_форм_внизу_нет(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Act
    страница = _открыть(стенд, monkeypatch, уК=True)

    # Assert — кнопки в ряду, формы действий живут во всплывающих блоках.
    for подпись in ("Экшн-план", "Предписание", "Исправить", "Отклонить проверку"):
        assert f"<span>{подпись}</span>" in страница or f">{подпись}</a>" in страница, подпись
    assert "/actions/prescriptions/new?inspection=11111111" in страница
    assert 'action="/inspections/11111111-1111-1111-1111-111111111111/move' in страница
    assert 'action="/inspections/11111111-1111-1111-1111-111111111111/retract' in страница
    assert 'class="section" id="move"' not in страница, "форма переноса осталась в подвале"
    assert "Исправить дату или пиццерию" not in страница


@pytest.mark.parametrize("стенд", ["guest"], indirect=True)
def test_гостю_управляющих_кнопок_нет(стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch) -> None:
    # Act
    страница = _открыть(стенд, monkeypatch, уК=False)

    # Assert — читать и скачать можно, управлять нельзя.
    for запретное in ("/retract", "/move", "/actions/prescriptions/new", "/actions/request"):
        assert запретное not in страница, запретное
    assert "Скачать PDF" in страница
