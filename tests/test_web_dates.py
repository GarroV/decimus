"""Дата месяцем словом (#963) и записи карточки по критичности (#965)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from src.web.dates import human_day
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
