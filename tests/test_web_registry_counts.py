"""«Проверки»: счётчики стран, строка «На приёмке», лимит «Принятых», «Отбор» на телефоне.

Ядро здесь — числа, которые читают как факт: счётчик страны слева обязан называть то, что
откроется по клику (принятые проверки периода с тем же отбором), а «100 из N» — настоящее
число, а не длину первой страницы. Расхождение выглядит правдоподобно и не падает.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import date, timedelta

import pytest
from flask.testing import FlaskClient
from test_web_app import ТЕНАНТ, шапка
from web_harness import войти, подменить_двери, собрать

from src.web import app as web_app
from src.web import inspections as data
from src.web.registry_view import REVIEW_CLASSES
from src.web.texts import t


@pytest.fixture
def стенд(monkeypatch: pytest.MonkeyPatch) -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant=ТЕНАНТ)
    with собрать(tenant=ТЕНАНТ).test_client() as client:
        assert войти(client).status_code == 302
        yield client


ГЕО = {
    "Tbilisi-1": ("GE", "tbilisi"),
    "Tbilisi-2": ("GE", "tbilisi"),
    "Batumi-1": ("GE", "batumi"),
    "Antalya-1": ("TR", "antalya"),
    "Polotsk-1": ("BY", ""),
}


def _принятая(unit: str, номер: int, **поля: object) -> object:
    return шапка(
        id=f"00000000-0000-0000-0000-{номер:012d}",
        unit_name=unit,
        inspection_date=date(2026, 9, 1) + timedelta(days=номер % 28),
        **поля,
    )


ПРИНЯТЫЕ = (
    _принятая("Tbilisi-1", 1, grade="A", kind="planned"),
    _принятая("Tbilisi-2", 2, grade="B", kind="repeat"),
    _принятая("Batumi-1", 3, grade="A", kind="planned"),
    _принятая("Antalya-1", 4, grade="A", kind="repeat"),
    _принятая("Antalya-1", 5, grade="C", kind="planned"),
)
# Две ждущие приёмки: одна в стране, где есть принятые, другая — только на приёмке.
ЖДУТ = (
    _принятая("Tbilisi-1", 6, grade="B"),
    _принятая("Polotsk-1", 7, grade="C"),
)


def _реестр(monkeypatch: pytest.MonkeyPatch, **поля: object) -> None:
    monkeypatch.setattr(
        data, "load_registry", lambda **_: data.Registry(ПРИНЯТЫЕ, True, review=ЖДУТ, **поля)
    )
    monkeypatch.setattr(data, "load_geography", lambda **_: ГЕО)


def _счётчики_стран(страница: str) -> dict[str, int]:
    """Код страны → число из «проверок: N» в колонке стран; 0 для «проверок за период нет»."""
    рейл = страница.split('class="rg-countries pk-rail', 1)[1].split("</aside>", 1)[0]
    итог: dict[str, int] = {}
    for код, мета in re.findall(
        r'pk-item__code">(\w+)</span>.*?pk-item__meta">([^<]*)</span>', рейл, flags=re.S
    ):
        число = re.search(r"\d+", мета)
        итог[код] = int(число.group()) if число else 0
    return итог


def _принятых_в_заголовке(страница: str) -> str:
    блок = страница.split(t("registry.accepted.title", "ru"), 1)[1]
    return re.search(r'class="sbadge">([^<]*)<', блок).group(1)  # type: ignore[union-attr]


ОТБОРЫ = ("", "grade=A", "kind=repeat", "q=tbilisi", "grade=B&kind=repeat")


@pytest.mark.parametrize("запрос", ОТБОРЫ)
def test_сумма_счётчиков_стран_равна_принятым(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch, запрос: str
) -> None:
    # Arrange — ждущие приёмки есть в обеих группах стран: старый счёт добавлял их к принятым.
    _реестр(monkeypatch)

    # Act
    страница = стенд.get(f"/inspections?period=all&lang=ru&{запрос}").get_data(as_text=True)
    по_странам = _счётчики_стран(страница)

    # Assert — «Σ» это «Все страны», остальные коды — страны.
    сумма = sum(n for код, n in по_странам.items() if код != "Σ")
    assert str(сумма) == _принятых_в_заголовке(страница)
    assert по_странам["Σ"] == сумма


def test_счётчик_страны_не_считает_ждущих_приёмки(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    _реестр(monkeypatch)

    # Act
    по_странам = _счётчики_стран(
        стенд.get("/inspections?period=all&lang=ru").get_data(as_text=True)
    )

    # Assert — Грузия: три принятые и одна ждущая; Беларусь: только ждущая, но в списке есть.
    assert по_странам["GE"] == 3
    assert по_странам["TR"] == 2
    assert по_странам["BY"] == 0


def test_счёт_из_базы_важнее_длины_первой_страницы(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — страница из пяти строк, а в базе по Грузии 40 и по Турции 60: так выглядит
    # период, который не поместился в предел.
    _реестр(monkeypatch, place_counts=(("GE", "tbilisi", 40), ("TR", "antalya", 60)))

    # Act
    страница = стенд.get("/inspections?period=all&lang=ru").get_data(as_text=True)
    по_странам = _счётчики_стран(страница)

    # Assert
    assert по_странам == {"Σ": 100, "GE": 40, "TR": 60, "BY": 0}


# --- лимит «Принятых» ---------------------------------------------------------


def _сотня() -> tuple[object, ...]:
    return tuple(_принятая("Tbilisi-1", 1000 + n) for n in range(web_app.REGISTRY_LIMIT))


def _с_числом(monkeypatch: pytest.MonkeyPatch, всего: int) -> None:
    monkeypatch.setattr(
        data,
        "load_registry",
        lambda **_: data.Registry(_сотня(), True, place_counts=(("GE", "tbilisi", всего),)),
    )
    monkeypatch.setattr(data, "load_geography", lambda **_: ГЕО)


def test_лимит_называет_настоящее_число_и_подсказывает(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — на странице 100 строк, в базе 101
    _с_числом(monkeypatch, 101)

    # Act
    страница = стенд.get("/inspections?period=all&lang=ru").get_data(as_text=True)

    # Assert
    assert _принятых_в_заголовке(страница) == "100 из 101"
    assert "Показаны последние 100 — сузьте период или отбор" in страница


def test_лимит_молчит_когда_всё_поместилось(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — ровно сто: подсказки быть не должно
    _с_числом(monkeypatch, 100)

    # Act
    страница = стенд.get("/inspections?period=all&lang=ru").get_data(as_text=True)

    # Assert
    assert _принятых_в_заголовке(страница) == "100"
    assert "Показаны последние" not in страница


def test_лимит_подписан_и_по_английски(стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    _с_числом(monkeypatch, 140)

    # Act
    страница = стенд.get("/inspections?period=all&lang=en").get_data(as_text=True)

    # Assert
    assert "100 of 140" in страница
    assert "Showing the latest 100 — narrow the period or filters" in страница


# --- строка «На приёмке» ------------------------------------------------------


def test_строка_приёмки_называет_классы_записей_по_убыванию_тяжести(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    ждёт = ЖДУТ[0]
    чистая = ЖДУТ[1]
    monkeypatch.setattr(
        data,
        "load_registry",
        lambda **_: data.Registry(
            (),
            True,
            review=(ждёт, чистая),
            review_classes={ждёт.id: {"D1": 4, "D3": 1, "D2": 2, "D0": 9}},  # type: ignore[attr-defined]
        ),
    )
    monkeypatch.setattr(data, "load_geography", lambda **_: ГЕО)

    # Act
    страница = стенд.get("/inspections?lang=ru").get_data(as_text=True)

    # Assert — D0 нарушением не считается; у проверки без записей — «без нарушений»
    assert "D3: 1 · D2: 2 · D1: 4" in страница
    assert "D0" not in страница
    assert t("registry.review.no_findings", "ru") in страница


def test_строка_приёмки_молчит_когда_записи_не_прочитались(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — `review_classes=None`: «не прочиталось» не равно «без нарушений»
    monkeypatch.setattr(data, "load_registry", lambda **_: data.Registry((), True, review=ЖДУТ))
    monkeypatch.setattr(data, "load_geography", lambda **_: ГЕО)

    # Act
    страница = стенд.get("/inspections?lang=ru").get_data(as_text=True)

    # Assert
    assert t("registry.review.no_findings", "ru") not in страница
    assert not any(f"{код}:" in страница for код in REVIEW_CLASSES)


def test_пояснения_короткие_и_двуязычные(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    _реестр(monkeypatch)

    # Act
    ру = стенд.get("/inspections?period=all&lang=ru").get_data(as_text=True)
    ан = стенд.get("/inspections?period=all&lang=en").get_data(as_text=True)

    # Assert
    assert (
        "Ждут вычитки. Город и страна отбирают и здесь; период, оценка и вид — только принятые."
        in ру
    )
    assert "Новые сверху." in ру
    assert "Awaiting review. City and country filter here too" in ан
    assert "Newest first." in ан


# --- «Отбор» на телефоне ------------------------------------------------------


def test_отбор_свёрнут_в_details_с_числом_изменённых_полей(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    _реестр(monkeypatch)

    # Act — период, страна и буква не по умолчанию: три поля
    изменён = стенд.get(
        "/inspections?lang=ru&from=2026-01-01&to=2026-12-31&country=TR&grade=A"
    ).get_data(as_text=True)
    умолчание = стенд.get("/inspections?lang=ru&period=all").get_data(as_text=True)

    # Assert
    assert '<details class="rg-fold">' in изменён
    assert "Отбор · 3" in изменён
    assert "Отбор · " not in умолчание
