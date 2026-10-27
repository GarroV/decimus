"""Ядро плитки «Стабильно ниже порога» (D658): кто попал в общий список и по каким источникам.

Это расчёт, который читают как факт про пиццерию, — ошибка здесь молчит.
"""

from __future__ import annotations

from src.ratings import risk_sources as rs
from src.ratings.summary import RiskUnit

ПОРОГ = 85.0


def зона(unit: str, kind: str = "rs", scores: tuple[float, ...] = (80.0, 81.0, 82.0)) -> RiskUnit:
    return RiskUnit(unit, unit.upper(), "RS", kind, scores)


def точка(unit: str, aggregator: str, scores: tuple[float, ...], scale: int = 10) -> rs.PointScores:
    return rs.PointScores(aggregator, unit, unit.upper(), "RS", scale, scores)


def проверки(unit: str, pcts: tuple[float, ...]) -> rs.InspectionScores:
    return rs.InspectionScores(unit, unit.upper(), "RS", pcts)


def собрать(
    zone: tuple[RiskUnit, ...] = (),
    points: tuple[rs.PointScores, ...] = (),
    inspections: tuple[rs.InspectionScores, ...] = (),
) -> tuple[rs.RiskRow, ...]:
    return rs.combine(zone, points, inspections, inspection_threshold=ПОРОГ)


def коды(row: rs.RiskRow) -> list[str]:
    return [s.code for s in row.sources]


def test_wolt_четыре_снимка_ниже_девяти_флаг() -> None:
    rows = собрать(points=(точка("a", "wolt", (8.9, 8.8, 8.7, 8.5)),))
    assert [коды(r) for r in rows] == [["wolt"]]


def test_wolt_один_снимок_на_пороге_и_выше_флага_нет() -> None:
    # 9.0 — не ниже порога: «все четыре ниже» не выполнено
    assert собрать(points=(точка("a", "wolt", (8.9, 8.8, 9.0, 8.5)),)) == ()


def test_агрегатор_меньше_четырёх_снимков_не_судится() -> None:
    assert собрать(points=(точка("a", "wolt", (8.0, 8.0, 8.0)),)) == ()


def test_берутся_только_последние_четыре_снимка() -> None:
    # новые первыми: последние четыре ниже, старый — выше, флаг есть
    assert коды(собрать(points=(точка("a", "wolt", (8.0, 8.0, 8.0, 8.0, 9.8)),))[0]) == ["wolt"]
    # свежий выше порога — флага нет, как бы плохи ни были старые
    assert собрать(points=(точка("a", "wolt", (9.5, 8.0, 8.0, 8.0, 8.0)),)) == ()


def test_glovo_порог_девяносто_процентов() -> None:
    assert коды(собрать(points=(точка("a", "glovo", (89.0, 88.0, 87.0, 89.9), 100),))[0]) == [
        "glovo"
    ]
    assert собрать(points=(точка("a", "glovo", (89.0, 88.0, 90.0, 89.0), 100),)) == ()


def test_прочие_площадки_ниже_девяноста_процентов_шкалы() -> None:
    # шкала 5: порог 4.5
    assert коды(собрать(points=(точка("a", "bolt_food", (4.4, 4.3, 4.4, 4.2), 5),))[0]) == [
        "bolt_food"
    ]
    assert собрать(points=(точка("a", "bolt_food", (4.4, 4.5, 4.4, 4.2), 5),)) == ()


def test_порог_сравнивается_с_показанным_значением() -> None:
    # 8.96 показывается как 9.0 — не ниже порога, флага нет (P38)
    assert собрать(points=(точка("a", "wolt", (8.96, 8.96, 8.96, 8.96)),)) == ()


def test_наши_проверки_две_последние_ниже_порога() -> None:
    rows = собрать(inspections=(проверки("a", (80.0, 84.9)),))
    assert [коды(r) for r in rows] == [["inspections"]]


def test_наши_проверки_одна_на_пороге_флага_нет() -> None:
    assert собрать(inspections=(проверки("a", (80.0, 85.0)),)) == ()


def test_наши_проверки_одна_проверка_не_судится() -> None:
    assert собрать(inspections=(проверки("a", (60.0,)),)) == ()


def test_наши_проверки_берутся_две_последние_а_не_все() -> None:
    # новые первыми; третья, старая, ниже порога не в счёт, а свежая выше — флага нет
    assert собрать(inspections=(проверки("a", (90.0, 70.0, 70.0)),)) == ()


def test_рс_и_рко_берутся_из_зоны_риска_как_есть() -> None:
    rows = собрать(zone=(зона("a", "rs"), зона("a", "rko", (70.0, 71.0, 72.0))))
    assert [коды(r) for r in rows] == [["rs", "rko"]]
    assert rows[0].sources[1].scores == (70.0, 71.0, 72.0)


def test_пиццерия_по_нескольким_источникам_одна_строка() -> None:
    rows = собрать(
        zone=(зона("a"),),
        points=(точка("a", "wolt", (8.0,) * 4),),
        inspections=(проверки("a", (70.0, 71.0)),),
    )
    assert len(rows) == 1
    assert коды(rows[0]) == ["rs", "wolt", "inspections"]


def test_порядок_больше_источников_выше_затем_имя() -> None:
    rows = собрать(
        zone=(зона("b"), зона("c")),
        points=(точка("c", "wolt", (8.0,) * 4), точка("a", "wolt", (8.0,) * 4)),
        inspections=(проверки("c", (70.0, 70.0)),),
    )
    assert [r.unit for r in rows] == ["c", "a", "b"]  # c — три источника, a и b — по одному


def test_у_пиццерии_две_точки_одной_площадки_флаг_один() -> None:
    rows = собрать(
        points=(точка("a", "wolt", (8.0,) * 4), точка("a", "wolt", (8.5,) * 4)),
    )
    assert коды(rows[0]) == ["wolt"]


def test_никто_не_ниже_порога_список_пуст() -> None:
    rows = собрать(
        points=(точка("a", "wolt", (9.5,) * 4),),
        inspections=(проверки("a", (95.0, 96.0)),),
    )
    assert rows == ()
