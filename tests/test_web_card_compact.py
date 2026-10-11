# ruff: noqa: F811 — фикстура стенда приходит импортом из test_web_app
"""Карточка проверки компактна (D400): зоны с потерей, классы записей один раз, действия в шапке.

Права не меняются — это проверяет `test_web_app` и `test_web_registry_split`;
здесь — что кнопка есть именно в шапке и ровно одна, а у роли без права её нет.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from flask.testing import FlaskClient
from test_web_app import карточка, стенд, шапка  # noqa: F401

from src.web import inspections as data
from src.web import view
from src.web.texts import t

ПОВЕРХНОСТИ = ("/inspections/{id}", "/inspections?inspection={id}")


def _зона(code: str, name: str, loss: float) -> dict[str, Any]:
    return {
        "code": code,
        "name_ru": name,
        "name_en": name,
        "share": 20.0,
        "counts": {},
        "loss": loss,
        "left": 20.0 - loss,
        "zeroed": False,
    }


def _открыть(стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch, адрес: str, **поля: Any) -> str:
    строка = поля.pop("row", None) or шапка()
    monkeypatch.setattr(data, "load_card", lambda *_a, **_k: карточка(строка, **поля))
    monkeypatch.setattr(data, "load_moves", lambda *_a, **_k: ())
    monkeypatch.setattr(data, "load_units", lambda **_k: (("u-1", строка.unit_name),))
    monkeypatch.setattr(data, "load_registry", lambda **_: data.Registry((строка,), True, ()))
    return стенд.get(адрес.format(id=строка.id)).get_data(as_text=True)


def _зоны_на_экране(страница: str) -> list[str]:
    return re.findall(r'class="zlist__name">([^<]+?)\s*(?:<|$)', страница)


# --- потери по зонам -------------------------------------------------------


def test_зоны_без_потерь_отбираются_и_идут_от_большей_потери_к_меньшей() -> None:
    линии = view.zone_lines(
        {
            "A": _зона("A", "Кухня", 1.0),
            "B": _зона("B", "Бар", 0.0),
            "C": _зона("C", "Зал", 3.5),
        },
        "ru",
    )

    assert [x.name for x in view.loss_zones(линии)] == ["Зал", "Кухня"]


@pytest.mark.parametrize("адрес", ПОВЕРХНОСТИ)
def test_на_экране_только_зоны_с_потерей(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch, адрес: str
) -> None:
    by_zone = {
        "A": _зона("A", "Кухня", 1.0),
        "B": _зона("B", "Бар", 0.0),
        "C": _зона("C", "Зал", 3.5),
    }

    страница = _открыть(стенд, monkeypatch, адрес, by_zone=by_zone)

    assert _зоны_на_экране(страница) == ["Зал", "Кухня"]
    assert "Бар" not in страница
    assert t("card.zones.none", "ru") not in страница


@pytest.mark.parametrize("адрес", ПОВЕРХНОСТИ)
def test_без_потерь_одна_короткая_строка_вместо_списка(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch, адрес: str
) -> None:
    страница = _открыть(стенд, monkeypatch, адрес, by_zone={"B": _зона("B", "Бар", 0.0)})

    assert t("card.zones.none", "ru") in страница
    assert 'class="zlist"' not in страница


# --- класс записей: одно место ---------------------------------------------


@pytest.mark.parametrize("адрес", ПОВЕРХНОСТИ)
def test_класс_записей_показан_один_раз_и_нулевой_скрыт(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch, адрес: str
) -> None:
    counts = {"D1": 9, "D2": 1, "D3": 0}

    страница = _открыть(стенд, monkeypatch, адрес, counts=counts)

    метки = re.findall(r'class="tag__note">(\d+)</span>', страница)
    assert sorted(метки) == ["1", "9"]  # D1 9 и D2 1 — по разу; D3 0 нет
    assert not re.search(r">D3<span", страница)


# --- действия в шапке ------------------------------------------------------


@pytest.mark.parametrize("стенд", ["admin"], indirect=True)
@pytest.mark.parametrize("адрес", ПОВЕРХНОСТИ)
def test_у_админа_свои_действия_кнопками_в_шапке_и_только_там(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch, адрес: str
) -> None:
    страница = _открыть(стенд, monkeypatch, адрес)

    шапка_действий = страница.index('class="hact"')
    for действие in ("/retract", "/letter"):
        assert страница.count(действие) == 1, действие
        assert страница.index(действие) > шапка_действий, действие


@pytest.mark.parametrize("стенд", ["admin"], indirect=True)
@pytest.mark.parametrize("адрес", ПОВЕРХНОСТИ)
def test_у_админа_чужой_проверки_кнопок_действий_нет(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch, адрес: str
) -> None:
    страница = _открыть(стенд, monkeypatch, адрес, row=шапка(tenant_code="GE"))

    assert "/retract" not in страница and "/letter" not in страница
    assert t("card.act.move", "ru") not in страница


@pytest.mark.parametrize("адрес", ПОВЕРХНОСТИ)
def test_у_аудитора_отклонения_и_переноса_нет(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch, адрес: str
) -> None:
    страница = _открыть(стенд, monkeypatch, адрес)

    assert "/retract" not in страница
    assert t("card.act.move", "ru") not in страница
    assert t("accept.title", "ru") not in страница


@pytest.mark.parametrize("стенд", ["admin"], indirect=True)
def test_страница_админа_перенос_и_отклонение_формами_в_шапке(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    страница = _открыть(стенд, monkeypatch, "/inspections/{id}")

    действия = страница.split('class="hact"', 1)[1]
    assert 'id="move"' in действия and 'id="retract"' in действия
    # Старых разделов внизу страницы нет: действие живёт один раз.
    assert 'id="move"' not in страница.split('class="hact"', 1)[0]
    assert страница.count('id="move"') == 1 and страница.count('id="retract"') == 1
