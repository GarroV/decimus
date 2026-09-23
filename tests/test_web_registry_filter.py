"""Отбор реестра: сужает выборку и честно называет причину пустоты.

Отличать «проверок нет» от «их отсёк отбор» обязан сам экран. Одинаковая
надпись на два разных случая — молчаливый сбой в чистом виде: человек снимает
фильтры и не понимает, почему список не появился, или наоборот решает, что
проверок нет вовсе, глядя на суженную выборку.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from flask.testing import FlaskClient
from test_web_app import ТЕНАНТ, шапка
from web_harness import войти, подменить_двери, собрать

from src.web import inspections as data
from src.web.texts import t


@pytest.fixture
def стенд(monkeypatch: pytest.MonkeyPatch) -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant=ТЕНАНТ)
    with собрать(tenant=ТЕНАНТ).test_client() as client:
        assert войти(client).status_code == 302
        yield client


РЯД = (
    шапка(unit_name="Белград-1", pct=71.5, grade="D"),
    шапка(unit_name="Тбилиси-2", pct=95.5, grade="A"),
)


def test_отбор_по_букве_оставляет_только_её_проверки(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    monkeypatch.setattr(data, "load_registry", lambda **_: data.Registry(РЯД, True))

    # Act
    страница = стенд.get("/inspections?grade=D").get_data(as_text=True)

    # Assert
    assert "Белград-1" in страница
    assert "Тбилиси-2" not in страница


def test_пустота_от_отбора_называется_иначе_чем_пустой_реестр(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — проверки в реестре есть, но под отбор не подходит ни одна.
    monkeypatch.setattr(data, "load_registry", lambda **_: data.Registry(РЯД, True))

    # Act
    от_отбора = стенд.get("/inspections?grade=B").get_data(as_text=True)
    monkeypatch.setattr(data, "load_registry", lambda **_: data.Registry((), True))
    пустой = стенд.get("/inspections").get_data(as_text=True)

    # Assert — две разные причины пустого экрана названы разными словами.
    # Сравниваются сами заголовки пустого состояния, а не наличие слова на
    # странице: слово «отбор» стоит и в панели выборки, и проверка на него
    # проходила бы даже при одинаковых надписях (поймано порчей).
    assert t("registry.filtered_out.title", "ru") in от_отбора
    assert t("registry.empty.title", "ru") not in от_отбора
    assert t("registry.empty.title", "ru") in пустой
    assert t("registry.filtered_out.title", "ru") not in пустой


def test_непонятная_буква_в_адресе_страницу_не_роняет(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Адрес правят руками и пересылают письмом — отказ здесь не к месту."""
    # Arrange
    monkeypatch.setattr(data, "load_registry", lambda **_: data.Registry(РЯД, True))

    # Act
    ответ = стенд.get("/inspections?grade=%D0%AF&kind=выдумка")

    # Assert
    assert ответ.status_code == 200


def test_снятая_проверка_в_списке_помечена_а_не_спрятана(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Спрятанная снятая проверка делает реестр короче молча.

    Её числа в отчёт не идут, но сама она была: исчезнувшая строка означает,
    что проверки не было вовсе, а это неправда.
    """
    # Arrange
    снятая = шапка(unit_name="Белград-9", retracted="2026-09-21T10:00:00+00:00")
    monkeypatch.setattr(data, "load_registry", lambda **_: data.Registry((снятая,), True))

    # Act
    страница = стенд.get("/inspections").get_data(as_text=True)

    # Assert
    assert "Белград-9" in страница
    assert "is-frozen" in страница
