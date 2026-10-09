"""Свод пиццерий → справочник: разбор листа, слияние, коды (D374).

Сведения читают как факт (дата запуска, статус, партнёр), поэтому разбор —
ядро по D369: кривая колонка дала бы правдоподобную, но чужую дату.
"""

from datetime import date, datetime

from src.ratings.maps_link import DodoUnit
from src.ratings.svod import (
    CLOSED_COLUMNS,
    MAIN_COLUMNS,
    merge,
    normalize,
    parse_sheet,
    unit_codes,
    with_codes,
)

ШАПКА = ["Пиццерия", "Франчайзи", "Почта", "Статус", "Страна", "Город",
         "дата поступления выручки по доставке", "дата поступления выручки по ресторану",
         "Дизайнер", "Площадь кухни"]  # fmt: skip


def _лист(*строки: list[object], первая: int = 3) -> list[list[object]]:
    return [["итог"], ШАПКА, *[["источник"]] * (первая - 2), *строки]


def test_строка_свода_раскладывается_по_полям() -> None:
    строки = _лист(
        ["İzmir-1", "Партнёр", "p@example.com", "Ресторан открыт", "Турция", "Измир",
         datetime(2025, 4, 2), "03.08.2025", "Имя Дизайнера", 41],
        ["Tokmok-1", "П", None, "Проектирование", "Кыргызстан", "Токмок", None, None, None, None],
        ["Nowhere-1", "П", None, "Ресторан открыт", "Атлантида", None, None, None, None, None],
    )  # fmt: skip
    found, skipped = parse_sheet(строки, MAIN_COLUMNS, first_row=3, closed=False)

    assert skipped == 1
    измир, токмок = found
    assert (измир.country_code, измир.stage, измир.partner_email) == ("TR", "open", "p@example.com")
    assert (измир.delivery_on, измир.restaurant_on) == (date(2025, 4, 2), date(2025, 8, 3))
    assert измир.extra == {"Площадь кухни": 41}  # имя сотрудника не переносится
    assert (токмок.country_code, токмок.stage) == ("KG", "pipeline")


def test_закрытая_не_затирает_действующую_с_тем_же_именем() -> None:
    действующие, _ = parse_sheet(
        _лист(["Гомель-3", "П", None, "Ресторан открыт", "Беларусь", None, None, None, None, None]),
        MAIN_COLUMNS, first_row=3, closed=False,
    )  # fmt: skip
    закрытые, _ = parse_sheet(
        _лист(["Гомель-3", None, None, "Закрыта по решению франчайзи", "Беларусь", None, None, None,
               None, None], первая=2),
        CLOSED_COLUMNS, first_row=2, closed=True,
    )  # fmt: skip
    assert [p.stage for p in merge(действующие, закрытые)] == ["open"]
    assert [p.stage for p in merge([], закрытые)] == ["closed"]


def test_код_dodo_по_имени_только_однозначный() -> None:
    found, _ = parse_sheet(
        _лист(
            ["İzmir-1", "П", None, "Ресторан открыт", "Турция", None, None, None, None, None],
            ["Twin-1", "П", None, "Ресторан открыт", "Турция", None, None, None, None, None],
        ),
        MAIN_COLUMNS, first_row=3, closed=False,
    )  # fmt: skip
    api = [DodoUnit("a" * 32, "Izmir-1", 0, 0), DodoUnit("b" * 32, "Twin-1", 0, 0),
           DodoUnit("c" * 32, "Twin-1", 0, 0)]  # fmt: skip
    измир, двойник = with_codes(found, api)
    assert (измир.dodo_id, двойник.dodo_id) == ("a" * 32, None)

    точки = [("u1", "TR", ("Измир 1", "izmir-1"), None), ("u2", None, ("Izmir-1",), None),
             ("u3", "TR", ("Izmir-1",), "a" * 32)]  # fmt: skip
    assert unit_codes([измир], точки) == [("u1", "a" * 32)]


def test_нормализация_снимает_регистр_пробелы_и_диакритику() -> None:
    assert normalize("İzmir - 1") == normalize("izmir-1")
