# ruff: noqa: F811 — фикстура стенда приходит импортом из test_web_app
"""Карточка проверки на приёмке: цена решения, две группы действий, статус один раз.

Права считает `_card_context`; здесь проверяется, что и панель реестра, и страница
показывают «Принять» подтверждением с ценой решения, «Отклонить» — подписанной
кнопкой, статус «На приёмке» — одним носителем, а повтор виден на самой записи.
"""

from __future__ import annotations

import dataclasses
import re
from typing import Any

import pytest
from flask.testing import FlaskClient
from test_web_app import ТЕНАНТ, карточка, стенд, шапка  # noqa: F401

from src.web import action_plans
from src.web import inspections as data

ID = "11111111-1111-1111-1111-111111111111"
ПАНЕЛЬ = f"/inspections?inspection={ID}&lang=ru"
СТРАНИЦА = f"/inspections/{ID}?lang=ru"


def _открыть(
    стенд: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
    адрес: str,
    *,
    repeat: bool = False,
    **шапка_полей: Any,
) -> str:
    строка = шапка(tenant_code=ТЕНАНТ, on_review=True, pct=97.5, grade="A", **шапка_полей)
    деталь = карточка(строка, counts={"D1": 1, "D2": 1})
    находки = tuple(dataclasses.replace(f, repeat=repeat) for f in деталь.findings)
    деталь = dataclasses.replace(деталь, findings=находки)
    monkeypatch.setattr(data, "load_card", lambda *_a, **_k: деталь)
    monkeypatch.setattr(data, "load_moves", lambda *_a, **_k: ())
    monkeypatch.setattr(data, "load_registry", lambda **_: data.Registry((строка,), True, ()))
    monkeypatch.setattr(data, "load_units", lambda **_k: (("u1", строка.unit_name),))
    monkeypatch.setattr(action_plans, "card_plan", lambda *_a, **_k: (None, True))
    ответ = стенд.get(адрес)
    assert ответ.status_code == 200
    return ответ.get_data(as_text=True)


def _окно_принять(страница: str) -> str:
    найдено = re.search(
        r'<details class="hact__item" name="hact" id="accept">(.*?)</details>', страница, re.S
    )
    assert найдено, "«Принять» не раскрывающееся подтверждение"
    return найдено.group(1)


@pytest.mark.parametrize("стенд", ["admin"], indirect=True)
@pytest.mark.parametrize("адрес", [ПАНЕЛЬ, СТРАНИЦА], ids=["панель", "страница"])
def test_принять_показывает_что_подтверждается_и_последствие(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch, адрес: str
) -> None:
    страница = _открыть(стенд, monkeypatch, адрес)

    окно = _окно_принять(страница)
    сводка = re.search(r'class="hact__sum">(.*?)</p>', окно, re.S)
    assert сводка, "нет сводки цены решения"
    текст = re.sub(r"<[^>]+>|\s+", " ", сводка.group(1))
    assert "A" in текст and "97.5%" in текст and "записей: 1" in текст and "значительное" in текст
    assert "D2" not in текст
    assert "входит в историю сети" in окно  # последствие, оно же у `accept.hint`
    # Одна форма «Принять» на карточке, и она внутри подтверждения (D401).
    assert страница.count(f'action="/inspections/{ID}/accept') == 1
    assert ("data-panel-form" in окно) is (адрес == ПАНЕЛЬ)


@pytest.mark.parametrize("стенд", ["admin"], indirect=True)
def test_в_панели_отклонить_подписана_а_корзина_не_в_шапке(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    страница = _открыть(стенд, monkeypatch, ПАНЕЛЬ)

    кнопка = re.search(
        r'<summary class="([^"]*)"[^>]*>(?:(?!</summary>).)*Отклонить</span></summary>',
        страница,
        re.S,
    )
    assert кнопка, "«Отклонить» без подписи"
    assert "hbtn--danger" in кнопка.group(1) and "hbtn--icon" not in кнопка.group(1)
    шапка_панели = страница.split("</header>", 1)[0]
    assert "hbtn--icon hbtn--danger" not in шапка_панели


@pytest.mark.parametrize("стенд", ["admin"], indirect=True)
def test_решения_и_второстепенное_в_двух_группах(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    страница = _открыть(стенд, monkeypatch, СТРАНИЦА)

    решения = страница.index("hact__group--decide")
    остальное = страница.index("hact__group--aux")
    assert решения < остальное
    группа = страница[решения:остальное]
    for id_ in ('id="accept"', 'id="move"', 'id="retract"'):
        assert id_ in группа, id_
    assert "/report" not in группа and "view=letter" not in группа


@pytest.mark.parametrize("стенд", ["admin"], indirect=True)
@pytest.mark.parametrize("адрес", [ПАНЕЛЬ, СТРАНИЦА], ids=["панель", "страница"])
def test_статус_на_приёмке_сказан_один_раз(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch, адрес: str
) -> None:
    страница = _открыть(стенд, monkeypatch, адрес)

    # В панели список реестра рядом тоже зовёт очередь «На приёмке» — считаем саму карточку.
    сама_карточка = страница.split('class="sdetail spanel"', 1)[-1]
    assert сама_карточка.count("На приёмке") == 1, "метка, плашка и строка повторяют статус"
    assert "Ждёт приёмки" not in страница and "Вычитайте записи" not in страница


@pytest.mark.parametrize("стенд", ["admin"], indirect=True)
def test_списано_названо_один_раз_в_блоке_потерь_по_зонам(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    страница = _открыть(стенд, monkeypatch, СТРАНИЦА)

    assert страница.count("Списано") == 1 and not re.search(r"Вычтено \d", страница)


@pytest.mark.parametrize("стенд", ["admin"], indirect=True)
@pytest.mark.parametrize("повтор", [True, False])
def test_повтор_виден_на_самой_записи(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch, повтор: bool
) -> None:
    страница = _открыть(стенд, monkeypatch, ПАНЕЛЬ, repeat=повтор)

    assert ('class="find-row__repeat"' in страница) is повтор


@pytest.mark.parametrize("стенд", ["admin"], indirect=True)
@pytest.mark.parametrize("адрес", [ПАНЕЛЬ, СТРАНИЦА], ids=["панель", "страница"])
def test_кодов_класса_на_экране_нет(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch, адрес: str
) -> None:
    """Класс — словами: в видимом тексте карточки нет «D1», «D2», «D3»."""
    страница = _открыть(стенд, monkeypatch, адрес)

    сама = страница.split('class="sdetail spanel"', 1)[-1] if адрес == ПАНЕЛЬ else страница
    сама = re.sub(r"<(script|style)\b.*?</\1>", "", сама, flags=re.S)
    видимое = re.sub(r"<[^>]+>", " ", сама)
    assert not re.findall(r"\bD[0-3]\b", видимое)
    assert "отклонение" in видимое  # метка класса записи и чип — словом


@pytest.mark.parametrize("стенд", ["admin"], indirect=True)
def test_на_странице_у_второстепенных_действий_есть_имя_для_узкого_экрана(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """На узком экране подписи прячутся, поэтому имя обязано жить в `aria-label`."""
    страница = _открыть(стенд, monkeypatch, СТРАНИЦА)

    ауксы = страница.split("hact__group--aux", 1)[1]
    assert 'aria-label="Скачать PDF"' in ауксы
    assert 'aria-label="Письмо партнёру"' in ауксы


@pytest.mark.parametrize("стенд", ["admin"], indirect=True)
def test_раскрытия_карточки_одного_вида_с_шевроном(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    страница = _открыть(стенд, monkeypatch, СТРАНИЦА)

    assert 'class="mx-more mx-more--card"' in страница  # «Версия чек-листа»
    assert "mx-more mx-more--card mx-more--explain" in страница
