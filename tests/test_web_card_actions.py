# ruff: noqa: F811 — фикстура стенда приходит импортом из test_web_app
"""Ряд действий в шапке карточки проверки: кто какую кнопку видит.

Права считает `_card_context`; здесь проверяется, что шаблон показывает кнопку
только при праве и что внизу карточки не осталось прежних разделов-форм.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from flask.testing import FlaskClient
from test_web_app import карточка, стенд, шапка  # noqa: F401

from src.web import action_plans
from src.web import inspections as data

АДРЕС = "/inspections/11111111-1111-1111-1111-111111111111?lang=ru"


def _открыть(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch, *, уК: bool, **поля_шапки: Any
) -> str:
    деталь = карточка(шапка(**поля_шапки))
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
    for подпись in ("План", "Сформировать предписание", "Исправить", "Отклонить проверку"):
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


@pytest.mark.parametrize("стенд", ["admin"], indirect=True)
def test_оценка_слева_у_названия_а_действия_подписаны(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Act
    страница = _открыть(стенд, monkeypatch, уК=True)

    # Assert — оценка раньше названия, в левом блоке шапки (D489).
    assert 'class="head-line__lead"' in страница
    assert страница.index('class="head-line__lead"') < страница.index('class="card__title"')
    assert страница.index('class="grade ') < страница.index('class="card__title"')
    # Короткие надписи, полное имя — в aria-label и в мгновенной подсказке.
    for короткая in ("Письмо", "План", "Сформировать предписание"):
        assert f"<span>{короткая}</span>" in страница, короткая
    assert 'aria-label="Письмо партнёру" data-tip="Письмо партнёру"' in страница
    assert 'title="Письмо партнёру"' not in страница


@pytest.mark.parametrize("стенд", ["admin"], indirect=True)
def test_принята_без_даты_объясняет_себя(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Act — проверка из времён до приёмки: accepted_at пуст.
    страница = _открыть(стенд, monkeypatch, уК=True)

    # Assert
    assert 'data-tip="Принята — в истории сети"' in страница


@pytest.mark.parametrize("стенд", ["admin"], indirect=True)
def test_принята_с_датой_называет_кто_принял(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Act
    страница = _открыть(
        стенд,
        monkeypatch,
        уК=True,
        accepted_at="2026-09-19T08:30:00+00:00",
        accepted_by="Demo Lead",
    )

    # Assert
    assert 'data-tip="Принята 19 сен 2026, 08:30 · Demo Lead"' in страница


@pytest.mark.parametrize("стенд", ["admin"], indirect=True)
def test_язык_отчёта_словом_а_не_кодом(стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """#1086: «Язык отчёта: английский», а не «en»."""
    страница = _открыть(стенд, monkeypatch, уК=True, report_lang="en")
    факт = страница.split("Язык отчёта", 1)[1].split("</div>", 2)[1]
    assert "английский" in факт and ">en<" not in факт
