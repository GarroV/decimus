# ruff: noqa: F811 — фикстура стенда приходит импортом из test_web_app
"""Карточка проверки на приёмке (D750, D749): принять сразу, «Отклонить» в ряду решений, классы кодами.

Права считает `_card_context`; здесь проверяется, что и панель реестра, и страница
принимают одной формой без подтверждения, «Отклонить» стоит третьим в ряду решений, класс показан кодом D1/D2/D3, статус «На приёмке» — одним носителем,
а повтор виден на самой записи.
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


@pytest.mark.parametrize("стенд", ["admin"], indirect=True)
@pytest.mark.parametrize("адрес", [ПАНЕЛЬ, СТРАНИЦА], ids=["панель", "страница"])
def test_принять_принимает_сразу_одной_формой(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch, адрес: str
) -> None:
    страница = _открыть(стенд, monkeypatch, адрес)

    форма = re.search(
        rf'<form method="post" action="/inspections/{ID}/accept\?lang=ru"([^>]*)>(.*?)</form>',
        страница,
        re.S,
    )
    assert форма, "нет формы «Принять»"
    assert "<button" in форма.group(2) and "<span>Принять</span>" in форма.group(2)
    assert ("data-panel-form" in форма.group(1)) is (адрес == ПАНЕЛЬ)
    assert страница.count(f'action="/inspections/{ID}/accept') == 1
    # Ни раскрывающегося подтверждения, ни сводки цены решения.
    assert 'id="accept"' not in страница and "hact__sum" not in страница


@pytest.mark.parametrize("стенд", ["admin"], indirect=True)
@pytest.mark.parametrize("адрес", [ПАНЕЛЬ, СТРАНИЦА], ids=["панель", "страница"])
def test_отклонить_кнопка_с_подписью_в_ряду_решений(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch, адрес: str
) -> None:
    страница = _открыть(стенд, monkeypatch, адрес)

    решения = страница.split("hact__group--decide", 1)[1].split("hact__group--aux", 1)[0]
    окно = re.search(
        r'<details class="hact__item" name="hact" id="retract">\s*'
        r'<summary class="([^"]*)">(.*?)</summary>'
        r'.*?<form method="post" action="/inspections/[^"]+/retract\?lang=ru"',
        решения,
        re.S,
    )
    assert окно, "«Отклонить» нет в ряду решений"
    классы, внутри = окно.groups()
    assert "hbtn--danger" in классы and "hbtn--icon" not in классы
    assert "<span>Отклонить</span>" in внутри
    assert "required" in решения[окно.start() :]  # причина обязательна
    assert "Удалить проверку" not in страница


@pytest.mark.parametrize("стенд", ["admin"], indirect=True)
@pytest.mark.parametrize("адрес", [ПАНЕЛЬ, СТРАНИЦА], ids=["панель", "страница"])
def test_pdf_значок_с_подписью_pdf(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch, адрес: str
) -> None:
    страница = _открыть(стенд, monkeypatch, адрес)

    ссылка = re.search(r'<a class="hbtn ([^"]*)" href="[^"]*/report[^"]*"[^>]*>(.*?)</a>', страница, re.S)
    assert ссылка, "нет ссылки на PDF"
    assert "hbtn--pdf" in ссылка.group(1) and "hbtn--icon" not in ссылка.group(1)
    assert "<svg" in ссылка.group(2) and "<span>PDF</span>" in ссылка.group(2)


@pytest.mark.parametrize("стенд", ["admin"], indirect=True)
def test_решения_и_второстепенное_в_двух_группах(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    страница = _открыть(стенд, monkeypatch, СТРАНИЦА)

    решения = страница.index("hact__group--decide")
    остальное = страница.index("hact__group--aux")
    assert решения < остальное
    группа = страница[решения:остальное]
    for id_ in ('id="move"', "/accept?lang=", 'id="retract"'):
        assert id_ in группа, id_
    assert "/report" not in группа and "view=letter" not in группа
    assert 'id="retract"' not in страница[остальное:]


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
def test_класс_показан_кодом_а_не_словом(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch, адрес: str
) -> None:
    """Плашки записей и счётчик — D1/D2; слов «значительное/критическое» вместо кодов нет."""
    страница = _открыть(стенд, monkeypatch, адрес)

    сама = страница.split('class="sdetail spanel"', 1)[-1] if адрес == ПАНЕЛЬ else страница
    сама = re.sub(r"<(script|style)\b.*?</\1>", "", сама, flags=re.S)
    метки = re.findall(r'class="tag [^"]*"[^>]*>\s*(D[0-3])\b', сама)
    assert "D1" in метки and "D2" in метки
    видимое = re.sub(r"<[^>]+>", " ", сама)
    assert not re.search(r"значительное|критическое", видимое)
    # Заголовок записи — без пометки допустимых классов «(D1, D2)».
    assert not re.search(r"find-row__title[^>]*>[^<]*\(D[0-3]", сама)


@pytest.mark.parametrize("стенд", ["admin"], indirect=True)
def test_на_странице_у_второстепенных_действий_есть_имя_для_узкого_экрана(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """На узком экране подписи прячутся, поэтому имя обязано жить в `aria-label`."""
    страница = _открыть(стенд, monkeypatch, СТРАНИЦА)

    ауксы = страница.split("hact__group--aux", 1)[1]
    assert 'aria-label="Скачать PDF"' in ауксы
    assert 'aria-label="Письмо партнёру"' in ауксы
