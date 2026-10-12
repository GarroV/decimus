"""Блоки РС и РКО на «Главной» (D378) — ядро: средние подборки и сигналы.

Средняя группы — среднее средних пиццерий (D353), а не простое среднее всех
оценок: у пиццерии с тремя волнами в месяце и пиццерии с одной вес одинаковый.
Месяц без оценок — разрыв, а не ноль и не дорисовка.
"""

from __future__ import annotations

from datetime import date

from src.ratings.summary import Fact
from src.web import home_ratings as hr

ОКТ, СЕН, АВГ = date(2026, 10, 1), date(2026, 9, 1), date(2026, 8, 1)


def факт(
    unit: str, country: str, begin: date, score: float, kind: str = "rs", period: int = 1
) -> Fact:
    return Fact(unit, unit, country, kind, period, begin, score)


def test_окно_месяцев_идёт_через_год_старые_первыми() -> None:
    assert hr.month_window(date(2026, 2, 14), n=4) == (
        date(2025, 11, 1),
        date(2025, 12, 1),
        date(2026, 1, 1),
        date(2026, 2, 1),
    )


def test_средняя_месяца_по_пиццериям_а_не_по_оценкам() -> None:
    # Arrange — у RS-1 три волны по 90, у RS-2 одна на 60.
    факты = [
        факт("RS-1", "RS", date(2026, 9, 2), 90, period=1),
        факт("RS-1", "RS", date(2026, 9, 12), 90, period=2),
        факт("RS-1", "RS", date(2026, 9, 22), 90, period=3),
        факт("RS-2", "RS", date(2026, 9, 2), 60, period=1),
    ]

    # Act
    ряд = hr.monthly(факты, "rs", ["RS"], [СЕН])

    # Assert — (90 + 60) / 2, а не (90·3 + 60) / 4 = 82.5
    assert ряд == (75.0,)


def test_месяц_без_оценок_разрыв_а_движение_к_прошлому_с_данными() -> None:
    факты = [
        факт("RS-1", "RS", date(2026, 8, 5), 80),
        факт("RS-1", "RS", date(2026, 10, 5), 86.5),
    ]

    блок = hr.gauge(факты, "rs", countries=["RS"], imf=["RS"], months=[АВГ, СЕН, ОКТ], threshold=85)

    assert блок.series == (80.0, None, 86.5)
    assert (блок.month, блок.value, блок.delta) == (ОКТ, 86.5, 6.5)


def test_подборка_отдельно_от_imf_и_сигнал_ниже_порога() -> None:
    факты = [
        факт("RS-1", "RS", date(2026, 10, 5), 70),
        факт("RS-2", "RS", date(2026, 10, 5), 90),
        факт("HR-1", "HR", date(2026, 10, 5), 98),
        факт("RS-1", "RS", date(2026, 10, 5), 99, kind="rko"),
    ]

    блок = hr.gauge(факты, "rs", countries=["RS"], imf=["RS", "HR"], months=[ОКТ], threshold=85)

    assert блок.value == 80.0
    assert блок.imf == round((70 + 90 + 98) / 3, 10)
    assert (блок.rated, блок.below) == (2, 1)
    assert блок.delta is None


def test_подборка_без_оценок_пустой_блок_а_не_ноль() -> None:
    факты = [факт("HR-1", "HR", date(2026, 10, 5), 98)]

    блок = hr.gauge(факты, "rs", countries=["RS"], imf=["RS", "HR"], months=[ОКТ], threshold=85)

    assert (блок.value, блок.month, блок.rated) == (None, None, 0)
    assert блок.imf_series == (98.0,)


def test_график_рвёт_линию_на_пустом_месяце() -> None:
    блок = hr.Gauge(
        kind="rs",
        months=(АВГ, СЕН, ОКТ, date(2026, 11, 1)),
        series=(80.0, None, 86.0, 88.0),
        imf_series=(None, None, None, None),
        month=date(2026, 11, 1),
        value=88.0,
        delta=2.0,
        imf=None,
        rated=1,
        below=0,
        threshold=85,
    )

    график = hr.chart(блок)

    assert график is not None
    # Одиночный август ломаной не даёт (только точкой), октябрь—ноябрь — одна ломаная.
    assert len(график.line) == 1 and график.line[0].count("L") == 1
    assert len(график.dots) == 3
    assert график.imf == ()
