"""Дата месяцем словом (#963) и записи карточки по критичности (#965)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from src.web.dates import human_day
from src.web.registry_period import Period
from src.web.registry_view import period_title
from src.web.view import by_severity


def test_дата_любого_вида_выходит_месяцем_словом() -> None:
    assert human_day("10.12.2026", "ru") == "10 дек 2026"
    assert human_day("2026-09-06", "en") == "6 Sep 2026"
    assert human_day("24.09.2026 14:30", "ru") == "24 сен 2026, 14:30"
    assert human_day(date(2026, 5, 1), "ru") == "1 мая 2026"
    assert human_day(datetime(2026, 5, 1, 8, 5), "en") == "1 May 2026, 08:05"


def test_не_дата_остаётся_словами_аудитора() -> None:
    for слова in ("Нет", "вчера в 15:00", "31.02.2026", "2026-09-06 утром"):
        assert human_day(слова, "ru") == слова
    assert human_day(None, "ru") == ""


@dataclass(frozen=True)
class _F:
    n: int
    level: str


def test_критичные_записи_сверху_порядок_внутри_класса_сохраняется() -> None:
    записи = [_F(1, "D1"), _F(2, "R"), _F(3, "D3"), _F(4, "D2"), _F(5, "D1"), _F(6, "NC")]

    порядок = [(f.level, f.n) for f in by_severity(записи)]

    assert порядок == [("D3", 3), ("D2", 4), ("D1", 1), ("D1", 5), ("NC", 6), ("R", 2)]


def test_период_словами_и_без_повтора_общего_у_краёв() -> None:
    """#978: ISO-диапазон в шапке «Проверок» и на кнопке периода не читался."""
    # Внутри даты пробелы неразрывные: в узкой кнопке перенос только у тире.
    assert period_title(Period(date(2026, 10, 1), date(2026, 10, 15)), "ru") == (
        "1 — 15\u00a0окт\u00a02026"
    )

    def text(start: date, end: date | None, lang: str = "ru") -> str:
        return period_title(Period(start, end), lang).replace("\u00a0", " ")

    assert text(date(2026, 9, 1), date(2026, 10, 31)) == "1 сен — 31 окт 2026"
    assert text(date(2025, 12, 20), date(2026, 1, 5), "en") == "20 Dec 2025 — 5 Jan 2026"
    assert text(date(2026, 9, 1), None) == "1 сен 2026 — …"
    assert period_title(Period(date(2026, 9, 1), date(2026, 9, 30)), "ru") == "Сентябрь 2026"


def test_целый_год_листается_годом_а_не_длиной_в_днях() -> None:
    # Arrange: 2027 — 365 дней, 2028 високосный: сдвиг «на длину» промахнулся бы на день.
    from src.web import registry_period

    год = registry_period.year_of(date(2027, 6, 15))

    # Act
    следующий = registry_period.shift(год, 1)
    предыдущий = registry_period.shift(год, -1)

    # Assert
    assert год.year == 2027 and год.month is None
    assert следующий == Period(date(2028, 1, 1), date(2028, 12, 31))
    assert предыдущий == Period(date(2026, 1, 1), date(2026, 12, 31))
    assert period_title(год, "ru") == "2027"


def test_быстрый_выбор_знает_год_и_произвольный_период() -> None:
    from src.web import registry_period
    from src.web.registry_view import period_quick

    def select(**params: str) -> str:
        return "?" + "&".join(f"{k}={v}" for k, v in params.items() if v)

    сегодня = date(2026, 11, 10)

    def выбранный(period: Period) -> str:
        return next(q["title"] for q in period_quick(period, сегодня, "ru", select) if q["on"])

    assert выбранный(registry_period.year_of(сегодня)) == "Этот год"
    assert выбранный(registry_period.year_of(date(2025, 1, 1))) == "Прошлый год"
    assert выбранный(Period(date(2026, 3, 5), date(2026, 9, 1))) == "Произвольный период"
    assert выбранный(Period(None, None)) == "Всё время"
    быстрые = period_quick(Period(None, None), сегодня, "ru", select)
    ссылки = {q["title"]: q["href"] for q in быстрые}
    assert ссылки["Этот год"] == "?from=2026-01-01&to=2026-12-31"
    assert ссылки["Произвольный период"] == ""
