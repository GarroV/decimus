# ruff: noqa: F811 — фикстура стенда приходит импортом из test_web_app
"""Реестр «список слева, карточка справа»: период, очередь приёмки, правая колонка.

Ядро здесь одно — права: у колонки справа не может оказаться кнопки, которой
нет у отдельной карточки (обе берут их из `_card_context`). Период — граница,
по которой база отбирает проверки: ошибка в нём молча прячет месяц истории.
Остальное (вёрстка, стрелки) проверяется глазами по снимкам.
"""

from __future__ import annotations

from datetime import date, timedelta
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


def test_без_периода_в_адресе_принятые_за_текущий_месяц(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D466: «Принятые» открываются последними — текущим месяцем, а не всем подряд."""
    вызовы = _ловушка(monkeypatch)

    стенд.get("/inspections")

    месяц = rp.month_of(date.today())
    assert (вызовы[0]["date_from"], вызовы[0]["date_to"]) == (месяц.start, месяц.end)


def test_у_главной_без_периода_в_адресе_текущий_месяц() -> None:
    """Умолчание задаёт экран: «Главная» осталась на месяце (D378)."""
    assert rp.read({}, today=СЕГОДНЯ) == rp.month_of(СЕГОДНЯ)
    assert rp.read({}, today=СЕГОДНЯ, default_all=True) == rp.Period(None, None)
    assert rp.read({"from": "2026-03-05"}, today=СЕГОДНЯ, default_all=True).start == date(
        2026, 3, 5
    )


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


def test_период_реестра_общий_календарь_с_быстрыми_выборами(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D405: календарь тот же, что на «Главной»; без скрипта — форма с датами."""
    _ловушка(monkeypatch)

    страница = стенд.get("/inspections").get_data(as_text=True)

    assert "data-pcal" in страница
    for ключ in ("registry.period.all", "registry.period.this_month", "registry.period.last_month"):
        assert t(ключ, "ru") in страница, ключ
    assert 'name="from"' in страница and 'name="to"' in страница


# --- состояния списка -------------------------------------------------------


def test_пустой_месяц_назван_пустым_периодом_а_не_пустым_реестром(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ловушка(monkeypatch)

    месяц = rp.month_of(СЕГОДНЯ)
    страница = стенд.get(f"/inspections?from={месяц.start}&to={месяц.end}").get_data(as_text=True)

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


def test_на_приёмке_давно_ждущие_первыми_и_с_числом_дней(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D466: очередь идёт от самой давней, у каждой строки — сколько она ждёт."""
    свежая = шапка(
        id="aaaaaaaa-0000-0000-0000-000000000001",
        unit_name="Свежая-1",
        on_review=True,
        inspection_date=СЕГОДНЯ - timedelta(days=1),
    )
    давняя = шапка(
        id="bbbbbbbb-0000-0000-0000-000000000002",
        unit_name="Давняя-9",
        on_review=True,
        inspection_date=СЕГОДНЯ - timedelta(days=12),
    )
    _ловушка(monkeypatch, review=(свежая, давняя))

    страница = стенд.get("/inspections").get_data(as_text=True)

    assert страница.index("Давняя-9") < страница.index("Свежая-1")
    assert "ждёт 12 дн." in страница and "ждёт 1 дн." in страница


def test_на_приёмке_пусто_одна_тихая_строка(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ловушка(monkeypatch, rows=(шапка(),))

    страница = стенд.get("/inspections").get_data(as_text=True)

    assert t("registry.review.empty", "ru") in страница


def test_приёмка_мимо_периода_и_отбора_принятые_под_отбором(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Очередь видна при любом отборе; период и отбор — только у «Принятых»."""
    ждущая = шапка(unit_name="Ждущая-5", on_review=True, grade="D")
    принятая = шапка(unit_name="Принятая-3", grade="A")
    _ловушка(monkeypatch, rows=(принятая,), review=(ждущая,))

    страница = стенд.get("/inspections?grade=D&from=2020-01-01&to=2020-01-31").get_data(
        as_text=True
    )

    assert "Ждущая-5" in страница
    assert "Принятая-3" not in страница


# --- правая колонка ---------------------------------------------------------


def test_выбранная_адресом_проверка_открыта_справа(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    строка = шапка(unit_name="Тбилиси-2")
    _ловушка(monkeypatch, rows=(строка,))
    monkeypatch.setattr(data, "load_card", lambda *_a, **_k: карточка(строка))

    страница = стенд.get(f"/inspections?inspection={строка.id}").get_data(as_text=True)

    assert "data-drawer" in страница
    assert 'id="inspection-title">Тбилиси-2<' in страница
    # Панель — полный просмотр (D465): ссылки на отдельную страницу карточки нет.
    assert f'href="/inspections/{строка.id}?lang=ru"' not in страница
    assert "Открыть полностью" not in страница


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

    for действие in ("/retract", "/letter"):
        assert (действие in страница) is свои_действия, действие
    # Принятую проверку не правят (D465): «Исправить» в панели у неё нет ни у кого.
    assert t("card.act.move", "ru") not in страница


@pytest.mark.parametrize("стенд", ["guest"], indirect=True)
def test_гость_не_видит_отклонения_справа(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    строка = шапка()
    _ловушка(monkeypatch, rows=(строка,))
    monkeypatch.setattr(data, "load_card", lambda *_a, **_k: карточка(строка))

    страница = стенд.get(f"/inspections?inspection={строка.id}").get_data(as_text=True)

    assert "/retract" not in страница and t("card.act.move", "ru") not in страница


def test_без_выбора_панели_нет_и_карточка_не_читается(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Панель выезжает только по выбору: без него нет ни панели, ни запроса карточки."""
    _ловушка(monkeypatch, rows=(шапка(),))
    прочитано: list[str] = []
    monkeypatch.setattr(data, "load_card", lambda i, **_: прочитано.append(i))

    страница = стенд.get("/inspections").get_data(as_text=True)

    assert "data-drawer" not in страница and прочитано == []
