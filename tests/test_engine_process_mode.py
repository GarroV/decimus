"""D714 (прототип): итоги по процессам — «единый D3 за процесс».

Владелец: обход по-прежнему по зонам, но итоги сводятся к процессам, «чтобы не
было такого, что у нас просрочка в 3 разных местах уничтожает всю проверку».

Режим включается только изданием методики (`d3.mode = "once_per_process"`,
`collapse = "item"` в `scoring.json`); действующие издания считаются как
прежде — это стережёт `test_engine_regress.py` и проверка ниже на синтетике.

Правила режима, каждое — отдельным тестом:

* D3 стоит `d3.process_loss` п.п. ОДИН раз на процесс, сколько бы раз и в
  скольких зонах его ни записали;
* один и тот же пункт в нескольких зонах — одно нарушение по старшему классу;
* D1/D2 процесса, где есть D3, не вычитаются (процесс уже обнулён);
* разные пункты одного процесса без D3 вычитаются каждый;
* буква считается по свёрнутым нарушениям, а не по записям.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import (
    AUDIT,
    DATA,
    EXAMPLES,
    TEST_DATA,
    Run,
    requires_data,
    requires_examples,
    run_engine,
)

PROCESS_LOSS = 10.0


def _process_edition(src: Path, dst: Path) -> Path:
    """Копия методики `src`, у которой включён режим процессов. Пункты и доли те же."""
    shutil.copytree(src, dst)
    path = dst / "scoring.json"
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg["d3"] = {"mode": "once_per_process", "process_loss": PROCESS_LOSS}
    cfg["collapse"] = "item"
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
    return dst


@pytest.fixture
def process_data(tmp_path: Path) -> Path:
    return _process_edition(TEST_DATA, tmp_path / "process-edition")


@pytest.fixture
def both(tmp_path: Path, process_data: Path) -> Callable[..., tuple[dict, dict]]:
    """Одна и та же проверка, посчитанная прежним изданием и изданием процессов."""
    work = tmp_path / "chat"
    work.mkdir()
    state = work / "inspection.json"

    def run(*args: str, data: Path = TEST_DATA) -> Run:
        return run_engine(AUDIT, *args, cwd=work, state=state, data_dir=data)

    r = run("init", "--unit", "Тестовая", "--auditor", "Тест", "--date", "2026-08-21")
    assert r.code == 0, r.text

    def add_and_score(*records: tuple[str, ...]) -> tuple[dict, dict]:
        for rec in records:
            qid, level, zone, *rest = rec
            args = ["add", "--qid", qid, "--level", level, "--zone", zone, "--evidence", "x"]
            if "repeat" in rest:
                args.append("--repeat")
            r = run(*args)
            assert r.code == 0, r.text
        old = run("score", "--json")
        new = run("score", "--json", data=process_data)
        assert old.code == 0, old.text
        assert new.code == 0, new.text
        return json.loads(old.out), json.loads(new.out)

    return add_and_score


def test_просрочка_в_трёх_зонах_стоит_один_d3(both: Callable[..., tuple[dict, dict]]) -> None:
    old, new = both(
        ("PRD10", "D3", "fridge"), ("PRD10", "D3", "hot_kitchen"), ("PRD10", "D3", "cold_kitchen")
    )
    assert old["pct"] == 70.0, "прежняя модель: три зоны по 10 % сгорели"
    assert new["pct"] == 100.0 - PROCESS_LOSS
    assert new["counts"]["D3"] == 1, "один D3 за процесс, а не три"
    proc = new["by_process"]["ZAGOTOVKI"]
    assert proc["zeroed"] is True
    assert proc["loss"] == PROCESS_LOSS
    [item] = proc["items"]
    assert item["qid"] == "PRD10"
    assert sorted(item["zones"]) == ["cold_kitchen", "fridge", "hot_kitchen"]


def test_два_разных_d3_одного_процесса_стоят_один_раз(
    both: Callable[..., tuple[dict, dict]],
) -> None:
    _, new = both(("PRD10", "D3", "fridge"), ("PRD08", "D3", "dry_storage"))
    assert new["pct"] == 100.0 - PROCESS_LOSS
    assert new["counts"]["D3"] == 1
    assert len(new["by_process"]["ZAGOTOVKI"]["items"]) == 2


def test_d3_в_двух_процессах_стоит_дважды(both: Callable[..., tuple[dict, dict]]) -> None:
    _, new = both(("PRD10", "D3", "fridge"), ("FSB17", "D3", "hot_kitchen"))
    assert new["pct"] == 100.0 - 2 * PROCESS_LOSS
    assert new["counts"]["D3"] == 2
    assert new["by_process"]["ZAGOTOVKI"]["zeroed"] is True
    assert new["by_process"]["REZHIMY_HRANENIYA"]["zeroed"] is True


def test_d2_в_двух_зонах_считается_один_раз(both: Callable[..., tuple[dict, dict]]) -> None:
    old, new = both(("PRD01", "D2", "fridge"), ("PRD01", "D2", "cold_kitchen"))
    assert old["pct"] == 96.0
    assert new["pct"] == 98.0
    assert new["counts"]["D2"] == 1, "буква считает свёрнутое нарушение, а не записи"
    assert new["record_counts"]["D2"] == 2, "записи не пропали"
    assert old["grade"] == "C" and new["grade"] == "B"


def test_один_пункт_в_разных_зонах_берёт_старший_класс(
    both: Callable[..., tuple[dict, dict]],
) -> None:
    _, new = both(("PRD01", "D1", "fridge"), ("PRD01", "D2", "cold_kitchen"))
    assert new["pct"] == 98.0
    [item] = new["by_process"]["ZAGOTOVKI"]["items"]
    assert item["level"] == "D2"
    assert new["counts"] == {**new["counts"], "D1": 0, "D2": 1}


def test_d1_d2_процесса_с_d3_не_вычитаются(both: Callable[..., tuple[dict, dict]]) -> None:
    _, new = both(
        ("PRD10", "D3", "fridge"),
        ("PRD01", "D2", "cold_kitchen"),
        ("PRD06", "D1", "hot_kitchen"),
        ("CLN01", "D1", "hot_kitchen"),
    )
    # ZAGOTOVKI обнулён (−10), его D2 и D1 не вычитаются; CLN01 — другой процесс, −0.5,
    # хотя стоит в той же зоне, что D3: зона в режиме процессов ничего не обнуляет.
    assert new["pct"] == 100.0 - PROCESS_LOSS - 0.5
    assert new["counts"]["D1"] == 1 and new["counts"]["D2"] == 0
    assert new["breakdown"]["skipped"] == {"D1": 1, "D2": 1}
    assert new["breakdown"]["exact"] is True


def test_разные_пункты_процесса_вычитаются_каждый(
    both: Callable[..., tuple[dict, dict]],
) -> None:
    _, new = both(("CLN01", "D1", "hot_kitchen"), ("CLN02", "D1", "dishwashing"))
    assert new["pct"] == 99.0
    assert new["by_process"]["PORYADOK"]["loss"] == 1.0


def test_повтор_дорожает_и_в_режиме_процессов(both: Callable[..., tuple[dict, dict]]) -> None:
    _, new = both(("CLN01", "D1", "hot_kitchen", "repeat"), ("CLN01", "D1", "dough"))
    assert new["pct"] == 99.0, "повтор ×2 у старшей записи пункта"


def test_сумма_процессов_сходится_с_вычетом(both: Callable[..., tuple[dict, dict]]) -> None:
    _, new = both(
        ("PRD10", "D3", "fridge"),
        ("PRD10", "D3", "dough"),
        ("CLN01", "D1", "hot_kitchen"),
        ("CLN01", "D1", "dough"),
        ("TEH01", "D2", "dough"),
    )
    total = sum(p["loss"] for p in new["by_process"].values())
    assert round(total, 4) == round(new["deductions"], 4)
    assert round(100.0 - total, 2) == new["pct"]
    assert all(z["loss"] == 0.0 and not z["zeroed"] for z in new["zones"].values()), (
        "у зоны в режиме процессов своей потери нет — она только адрес"
    )


def test_прежнее_издание_не_знает_полей_режима(both: Callable[..., tuple[dict, dict]]) -> None:
    old, _ = both(("PRD10", "D3", "fridge"), ("CLN01", "D1", "dough"))
    assert "record_counts" not in old
    assert all("items" not in p for p in old["by_process"].values())


@requires_data
@requires_examples
@pytest.mark.parametrize(
    ("name", "pct", "grade"), [("belgrade-1", 97.5, "A"), ("belgrade-2", 97.5, "A")]
)
def test_белград_в_режиме_процессов(tmp_path: Path, name: str, pct: float, grade: str) -> None:
    """Белград-2: CLN06 записан в двух зонах — одно нарушение, 97.0 → 97.5."""
    data = _process_edition(DATA, tmp_path / "live-process")
    d = EXAMPLES / name
    r = run_engine(AUDIT, "score", "--json", cwd=d, state=d / "inspection.json", data_dir=data)
    assert r.code == 0, r.text
    res = json.loads(r.out)
    assert (res["pct"], res["grade"]) == (pct, grade)
