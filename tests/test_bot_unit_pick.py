"""D196: пиццерия проверки — из справочника, а не из написанного."""

from __future__ import annotations

import pytest

from src.bot import unit_pick
from src.bot.unit_pick import UnitMatch, match_in, match_unit
from src.db.errors import ConfigError

СПРАВОЧНИК = [
    ("Тбилиси-1", (), True),
    ("Тбилиси-2", (), True),
    ("Батуми-1", (), True),
    ("Белград-1", ("БГ1",), True),
]


@pytest.mark.parametrize("написано", ["Тбилиси-1", "тбилиси -1", "Тбилиси – 1", "  ТБИЛИСИ-1 ", "тбилиси 1"])
def test_небрежное_написание_находит_каноничную_точку(написано: str) -> None:
    # Act
    сверка = match_in(написано, СПРАВОЧНИК)

    # Assert — «Тбилиси -1» 24.09.2026 завёл вторую точку; теперь это та же.
    assert сверка == UnitMatch(name="Тбилиси-1", suggestions=(), checked=True)


def test_синоним_ведёт_к_точке() -> None:
    assert match_in("бг1", СПРАВОЧНИК).name == "Белград-1"


def test_незнакомое_не_становится_точкой_а_получает_подсказки() -> None:
    # Act
    сверка = match_in("Тбилиси-4", СПРАВОЧНИК)

    # Assert — точки нет, и сама она не подставляется: выбирает человек.
    assert сверка.name is None
    assert сверка.checked is True
    assert "Тбилиси-1" in сверка.suggestions
    assert "Батуми-1" not in сверка.suggestions


def test_совсем_чужое_без_подсказок() -> None:
    сверка = match_in("Лондон Центральный", СПРАВОЧНИК)
    assert (сверка.name, сверка.suggestions, сверка.checked) == (None, (), True)


def test_пустой_справочник_не_останавливает_аудитора() -> None:
    assert match_in("Что угодно", []).checked is False


def test_недоступный_справочник_не_останавливает_аудитора(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange — аудитор уже на точке; сорвать обход из-за базы нельзя.
    def лежит(**_: object) -> list[object]:
        raise ConfigError("DATABASE_URL не задан")

    monkeypatch.setattr(unit_pick.directory, "list_units", лежит)

    # Act / Assert
    assert match_unit("Тбилиси-1").checked is False


def test_кириллица_находит_точку_базы_записанную_латиницей() -> None:
    # Arrange — справочник сети латиницей, рядом дубли, заведённые ботом до D196.
    справочник = [
        ("Тбилиси -1", (), False),
        ("Tbilisi-1", (), True),
        ("Тбилиси-1", (), False),
        ("Batumi-1", (), True),
    ]

    # Act / Assert — побеждает точка базы, а не дубль.
    assert match_in("Тбилиси-1", справочник).name == "Tbilisi-1"
    assert match_in("тбилиси -1", справочник).name == "Tbilisi-1"
    assert match_in("Батуми-1", справочник).name == "Batumi-1"
