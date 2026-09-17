"""D120/D121: итог по процессам считается вкладом в потерю итога.

Владелец просил сводку не по секторам пиццерии, а по направлениям методики, и
выбрал нашу шкалу: не «выполнено 71 % работы с продуктом», как у Qualon, а
«столько процентов итога потеряно из-за этого процесса».

Проверяется здесь не «поле появилось», а свойство, без которого сводка врёт:
сумма вкладов всех процессов равна общей потере. Разойдись она — и таблица
покажет цифры, которые не сходятся с итоговым баллом на той же странице.

Отдельно взята ветка D3: в белградских примерах его нет ни одного, поэтому
обнуление зоны не проверяется ими вовсе.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Callable
from pathlib import Path

from conftest import ROOT, Run


def методика_пунктов() -> list[dict[str, str]]:
    """Пункты синтетической методики — источник ожидаемого состава процессов."""
    path = Path(ROOT) / "tests" / "methodology" / "checklist.csv"
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def свод(audit: Callable[..., Run]) -> dict:
    r = audit("score", "--json")
    assert r.code == 0, r.text
    return json.loads(r.out)


def test_сумма_вкладов_процессов_равна_общей_потере(started: Callable[..., Run]) -> None:
    started("add", "--qid", "CLN01", "--level", "D1", "--zone", "hot_kitchen")
    started("add", "--qid", "CLN01", "--level", "D1", "--zone", "cold_kitchen")
    started("add", "--qid", "PRD05", "--level", "D2", "--zone", "dough")

    s = свод(started)
    вклады = sum(p["loss"] for p in s["by_process"].values())

    assert round(вклады, 4) == round(s["deductions"], 4)
    assert round(s["pct"] + вклады, 2) == 100.0


def test_обнулённая_зона_ложится_на_процесс_виновника(started: Callable[..., Run]) -> None:
    # D3 обнуляет горячий цех целиком, а второй процесс теряет свою зону отдельно.
    started("add", "--qid", "PRD04", "--level", "D3", "--zone", "hot_kitchen")
    started("add", "--qid", "CLN01", "--level", "D1", "--zone", "cold_kitchen")

    s = свод(started)
    доля_цеха = s["zones"]["hot_kitchen"]["share"]

    assert s["by_process"]["ZAGOTOVKI"]["loss"] == доля_цеха
    assert s["by_process"]["PORYADOK"]["loss"] < доля_цеха
    assert round(sum(p["loss"] for p in s["by_process"].values()), 4) == round(s["deductions"], 4)


def test_нарушение_чужого_процесса_в_обнулённой_зоне_ничего_не_стоит(
    started: Callable[..., Run],
) -> None:
    """Зона уже в нуле — вычитать с неё второй раз нечего, и приписать этот
    ноль второму процессу нельзя: иначе сумма вкладов перерастёт общую потерю."""
    started("add", "--qid", "PRD04", "--level", "D3", "--zone", "hot_kitchen")
    started("add", "--qid", "CLN01", "--level", "D1", "--zone", "hot_kitchen")

    s = свод(started)

    assert s["by_process"]["PORYADOK"]["loss"] == 0.0
    assert s["by_process"]["PORYADOK"]["D1"] == 1, "запись не пропала — она просто ничего не стоит"
    assert round(sum(p["loss"] for p in s["by_process"].values()), 4) == round(s["deductions"], 4)


def test_группировка_идёт_по_коду_а_не_по_формулировке(started: Callable[..., Run]) -> None:
    """Ключ — код процесса: формулировки переводятся и правятся, коды нет."""
    started("add", "--qid", "CLN01", "--level", "D1", "--zone", "hot_kitchen")

    s = свод(started)

    assert "PORYADOK" in s["by_process"], "ключ — код процесса, не его формулировка"
    assert s["by_process"]["PORYADOK"]["name_ru"] == "Порядок"
    assert s["by_process"]["PORYADOK"]["name_en"]


def test_в_сводку_попадают_все_процессы_методики(started: Callable[..., Run]) -> None:
    """Сводка из двух строк вместо семи читается как «остальное не смотрели»."""
    started("add", "--qid", "CLN01", "--level", "D1", "--zone", "hot_kitchen")

    s = свод(started)

    процессы_методики = {
        (r.get("process_code") or r["process_ru"]).strip() for r in методика_пунктов()
    }
    assert set(s["by_process"]) == процессы_методики


def test_чистый_процесс_и_неоцениваемый_различимы(started: Callable[..., Run]) -> None:
    """Ноль потерь и «оценивать нечего» — разные вещи.

    Процесс, у которого в методике есть нарушения, но их не нашли, обязан
    показать 0 % — это «проверено, чисто». Процесс из одних информационных
    пунктов (D0) вычетов не даёт вовсе, и 0 % на его месте соврал бы о том,
    что его оценивали.
    """
    started("add", "--qid", "CLN01", "--level", "D1", "--zone", "hot_kitchen")

    s = свод(started)
    оцениваемые = {k for k, p in s["by_process"].items() if p["scored"]}
    информационные = {k for k, p in s["by_process"].items() if not p["scored"]}

    assert оцениваемые, "ни один процесс не помечен оцениваемым"
    assert информационные, "в методике есть процесс из одних D0 — он обязан быть отличим"
    assert all(s["by_process"][k]["loss"] == 0.0 for k in информационные)
