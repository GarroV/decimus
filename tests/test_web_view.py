"""Подготовка посчитанного к показу: выбор языка, порядок, тон метки.

Дорогая ошибка здесь одна — **действие над числом**. Процент, доля, потеря и
остаток посчитаны движком и записаны в базу; любое сложение, округление или
приведение по дороге к экрану означало бы второй расчёт оценки, пусть и
незаметный. Поэтому тесты сравнивают напечатанное с записанным дословно, а не
«примерно».
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.web.errors import WebTextError
from src.web.view import count_lines, grade_tone, level_tone, zone_lines

ЗОНЫ = {
    "KITCHEN": {
        "code": "KITCHEN",
        "name_ru": "Кухня",
        "name_en": "Kitchen",
        "share": Decimal("20.00"),
        "counts": {"D1": 2},
        "loss": Decimal("1.00"),
        "left": Decimal("19.00"),
        "zeroed": False,
    },
    "HALL": {
        "code": "HALL",
        "name_ru": "Зал",
        "name_en": "Hall",
        "share": Decimal("15.00"),
        "counts": {"D3": 1},
        "loss": Decimal("15.00"),
        "left": Decimal("0.00"),
        "zeroed": True,
    },
}


def test_зоны_печатаются_ровно_так_как_записаны() -> None:
    # Arrange — значения лежат в базе десятичными, с двумя знаками.
    # Act
    строки = zone_lines(ЗОНЫ, "ru")

    # Assert — ни округления, ни пересчёта: строка совпадает со записанным.
    кухня = next(line for line in строки if line.code == "KITCHEN")
    assert (кухня.share, кухня.loss, кухня.left) == ("20.00", "1.00", "19.00")


def test_зоны_идут_в_порядке_кода_а_не_как_легли_в_словарь() -> None:
    # Act
    строки = zone_lines(ЗОНЫ, "ru")

    # Assert — порядок словаря из jsonb не определён, порядок экрана обязан быть.
    assert [line.code for line in строки] == ["HALL", "KITCHEN"]


@pytest.mark.parametrize(("язык", "ожидание"), [("ru", "Кухня"), ("en", "Kitchen")])
def test_имя_зоны_берётся_по_языку_интерфейса(язык: str, ожидание: str) -> None:
    # Act
    строки = zone_lines(ЗОНЫ, язык)

    # Assert
    assert next(line for line in строки if line.code == "KITCHEN").name == ожидание


def test_незаведённый_язык_это_отказ_а_не_откат_на_русский() -> None:
    # Act / Assert — молчаливый откат показал бы половину экрана не на том языке.
    with pytest.raises(WebTextError, match="de"):
        zone_lines(ЗОНЫ, "de")


def test_обнулённая_зона_помечена_обнулённой() -> None:
    # Act
    строки = zone_lines(ЗОНЫ, "ru")

    # Assert — обнуление по D3 считает движок, экран его только показывает.
    assert next(line for line in строки if line.code == "HALL").zeroed is True


def test_отсутствующее_значение_это_прочерк_а_не_ноль() -> None:
    # Arrange — у зоны нет остатка вовсе: «значения нет» и «ноль» разные вещи.
    зоны = {"X": {"code": "X", "name_ru": "Х", "name_en": "X", "share": 10, "loss": 0}}

    # Act
    (строка,) = zone_lines(зоны, "ru")

    # Assert
    assert (строка.loss, строка.left) == ("0", "—")


def test_счётчики_классов_идут_по_классу_и_получают_свой_тон() -> None:
    # Act
    строки = count_lines({"D3": 1, "D1": 5, "D2": 2})

    # Assert
    assert [(line.level, line.count) for line in строки] == [("D1", "5"), ("D2", "2"), ("D3", "1")]
    assert [line.tone for line in строки] == ["tag--neutral", "tag--warn", "tag--err"]


@pytest.mark.parametrize(
    ("буква", "тон"),
    [("A", "tag--ok"), ("B", "tag--neutral"), ("C", "tag--warn"), ("D", "tag--err")],
)
def test_буква_оценки_получает_тон_дизайн_системы(буква: str, тон: str) -> None:
    assert grade_tone(буква) == тон


def test_неизвестная_буква_остаётся_на_экране_нейтральной() -> None:
    # Пороги букв живут в data/scoring.json и могут пополниться. Пропасть с
    # экрана оценка не имеет права: «есть, но я её не знаю» — это то, что и
    # надо увидеть.
    assert grade_tone("E") == "tag--neutral"


@pytest.mark.parametrize(
    ("класс", "тон"), [("D1", "tag--neutral"), ("D2", "tag--warn"), ("D3", "tag--err")]
)
def test_класс_нарушения_получает_тон_доменного_слоя(класс: str, тон: str) -> None:
    # D1 нейтрален намеренно: он снимает 0,5 %, и покраска сделала бы тревожным
    # весь отчёт, а D3 перестал бы читаться (dodo/decimus/domain.css).
    assert level_tone(класс) == тон
