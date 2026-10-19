"""Сравнение девелоперов и стран на «Рейтингах» (D551, #972)."""

from __future__ import annotations

from datetime import date

from src.db.ratings_read import CountryRow
from src.ratings.compare import lines
from src.ratings.model import RKO, RS
from src.ratings.summary import Fact

СТРАНЫ = (
    CountryRow("GE", "Грузия", "Georgia", "Индира", True, "CAUCASUS"),
    CountryRow("AM", "Армения", "Armenia", "Индира", True, "CAUCASUS"),
    CountryRow("TR", "Турция", "Turkey", "Олег", True, "TURKEY"),
    CountryRow("SI", "Словения", "Slovenia", None, True, "CEE"),
)


def факт(unit: str, country: str, kind: str, score: float, period: int = 1) -> Fact:
    return Fact(unit, unit, country, kind, period, date(2026, 9, 1), score)


def test_девелопер_это_средняя_его_пиццерий_а_не_средняя_стран() -> None:
    # Грузия — две пиццерии (80 и 90), Армения — одна (100): средняя пиццерий
    # девелопера 90, а средняя средних стран была бы 92.5.
    сейчас = [
        факт("ge1", "GE", RS, 80.0),
        факт("ge2", "GE", RS, 90.0),
        факт("am1", "AM", RS, 100.0),
        факт("tr1", "TR", RS, 70.0),
        факт("ge1", "GE", RKO, 95.0),
    ]
    раньше = [факт("ge1", "GE", RS, 85.0), факт("am1", "AM", RS, 95.0)]

    итог = lines(СТРАНЫ, сейчас, раньше)

    индира = next(x for x in итог.developers if x.key == "Индира")
    assert (индира.countries, индира.units) == (("GE", "AM"), 3)
    assert индира.rs == 90.0 and индира.rs_delta == 0.0
    assert индира.rko == 95.0 and индира.rko_delta is None
    грузия = next(x for x in итог.countries if x.key == "GE")
    assert (грузия.rs, грузия.rs_delta, грузия.units) == (85.0, 0.0, 2)


def test_лучшие_сверху_а_без_данных_внизу_и_без_девелопера_строки_нет() -> None:
    сейчас = [факт("ge1", "GE", RS, 80.0), факт("tr1", "TR", RS, 95.0)]

    итог = lines(СТРАНЫ, сейчас, [])

    assert [x.key for x in итог.developers] == ["Олег", "Индира"]
    assert [x.key for x in итог.countries] == ["TR", "GE", "AM", "SI"]
    assert итог.countries[-1].rs is None and итог.countries[-1].units == 0
