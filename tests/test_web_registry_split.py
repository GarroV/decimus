# ruff: noqa: F811 — фикстура стенда приходит импортом из test_web_app
"""Реестр «список слева, карточка справа»: период, очередь приёмки, правая колонка.

Ядро здесь одно — права: у колонки справа не может оказаться кнопки, которой
нет у отдельной карточки (обе берут их из `_card_context`). Период — граница,
по которой база отбирает проверки: ошибка в нём молча прячет месяц истории.
Остальное (вёрстка, стрелки) проверяется глазами по снимкам.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from flask.testing import FlaskClient
from test_web_app import ТЕНАНТ, карточка, стенд, шапка  # noqa: F401

from src.web import inspections as data
from src.web import registry_period as rp
from src.web.texts import t

СЕГОДНЯ = date.today()


def _ловушка(
    monkeypatch: pytest.MonkeyPatch, *, rows: tuple[Any, ...] = (), review: tuple[Any, ...] = ()
) -> list[dict[str, Any]]:
    """Подменить чтение реестра и запомнить, с каким периодом его звали."""
    вызовы: list[dict[str, Any]] = []

    def _реестр(**kw: Any) -> data.Registry:
        вызовы.append(kw)
        return data.Registry(rows, True, review)

    monkeypatch.setattr(data, "load_registry", _реестр)
    return вызовы


# --- период: что уходит в базу ---------------------------------------------


def test_без_периода_в_адресе_база_отбирает_текущий_месяц(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    вызовы = _ловушка(monkeypatch)

    стенд.get("/inspections")

    месяц = rp.month_of(СЕГОДНЯ)
    assert (вызовы[0]["date_from"], вызовы[0]["date_to"]) == (месяц.start, месяц.end)


@pytest.mark.parametrize(
    ("адрес", "ждём"),
    [
        ("?from=2026-03-05&to=2026-03-20", (date(2026, 3, 5), date(2026, 3, 20))),
        ("?from=2026-03-20&to=2026-03-05", (date(2026, 3, 5), date(2026, 3, 20))),
        ("?period=all", (None, None)),
        ("?from=2026-03-05", (date(2026, 3, 5), None)),
        ("?from=выдумка&to=2026-03-20", (None, date(2026, 3, 20))),
    ],
)
def test_период_из_адреса_уходит_в_базу_границами(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch, адрес: str, ждём: tuple[Any, Any]
) -> None:
    вызовы = _ловушка(monkeypatch)

    ответ = стенд.get(f"/inspections{адрес}")

    assert ответ.status_code == 200
    assert (вызовы[0]["date_from"], вызовы[0]["date_to"]) == ждём


@pytest.mark.parametrize(
    ("период", "шаг", "ждём"),
    [
        (rp.month_of(date(2026, 1, 15)), -1, rp.month_of(date(2025, 12, 1))),
        (rp.month_of(date(2026, 12, 3)), 1, rp.month_of(date(2027, 1, 1))),
        (rp.month_of(date(2026, 3, 1)), -1, rp.month_of(date(2026, 2, 1))),
        (
            rp.Period(date(2026, 3, 5), date(2026, 3, 11)),
            1,
            rp.Period(date(2026, 3, 12), date(2026, 3, 18)),
        ),
        (rp.Period(None, None), 1, None),
        (rp.Period(date(2026, 3, 5), None), -1, None),
    ],
)
def test_стрелка_листает_на_длину_периода(
    период: rp.Period, шаг: int, ждём: rp.Period | None
) -> None:
    assert rp.shift(период, шаг) == ждём


# --- состояния списка -------------------------------------------------------


def test_пустой_месяц_назван_пустым_периодом_а_не_пустым_реестром(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ловушка(monkeypatch)

    страница = стенд.get("/inspections").get_data(as_text=True)

    assert t("registry.period.empty.title", "ru") in страница
    assert t("registry.empty.title", "ru") not in страница


def test_ждущие_приёмки_видны_когда_история_месяца_пуста(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    ждущая = шапка(unit_name="Белград-7", on_review=True)
    вызовы = _ловушка(monkeypatch, review=(ждущая,))
    monkeypatch.setattr(data, "load_card", lambda *_a, **_k: карточка(ждущая))

    страница = стенд.get("/inspections?grade=A").get_data(as_text=True)

    assert вызовы and "Белград-7" in страница
    assert t("registry.review.title", "ru") in страница


# --- правая колонка ---------------------------------------------------------


def test_выбранная_адресом_проверка_открыта_справа(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    строка = шапка(unit_name="Тбилиси-2")
    _ловушка(monkeypatch, rows=(строка,))
    monkeypatch.setattr(data, "load_card", lambda *_a, **_k: карточка(строка))

    страница = стенд.get(f"/inspections?inspection={строка.id}").get_data(as_text=True)

    assert "split--open" in страница
    assert 'id="inspection-title">Тбилиси-2<' in страница
    assert f'href="/inspections/{строка.id}?lang=ru"' in страница


def test_проверка_вне_охвата_справа_не_показана(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ловушка(monkeypatch, rows=(шапка(),))
    monkeypatch.setattr(data, "load_card", lambda *_a, **_k: None)

    страница = стенд.get("/inspections?inspection=чужая").get_data(as_text=True)

    assert t("registry.panel.missing.title", "ru") in страница
    assert 'id="inspection-title"' not in страница


@pytest.mark.parametrize("стенд", ["admin"], indirect=True)
@pytest.mark.parametrize(("пространство", "свои_действия"), [(ТЕНАНТ, True), ("GE", False)])
def test_действия_справа_те_же_что_у_карточки(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch, пространство: str, свои_действия: bool
) -> None:
    """Админ УК видит «Отклонить» и «Письмо» у своей проверки и не видит у партнёрской (D283)."""
    строка = шапка(tenant_code=пространство)
    _ловушка(monkeypatch, rows=(строка,))
    monkeypatch.setattr(data, "load_card", lambda *_a, **_k: карточка(строка))
    monkeypatch.setattr(data, "load_moves", lambda *_a, **_k: ())

    страница = стенд.get(f"/inspections?inspection={строка.id}").get_data(as_text=True)

    for действие in ("/retract", "/letter", "#move"):
        assert (действие in страница) is свои_действия, действие


def test_аудитор_не_видит_отклонения_справа(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    строка = шапка()
    _ловушка(monkeypatch, rows=(строка,))
    monkeypatch.setattr(data, "load_card", lambda *_a, **_k: карточка(строка))

    страница = стенд.get(f"/inspections?inspection={строка.id}").get_data(as_text=True)

    assert "/retract" not in страница and "#move" not in страница
