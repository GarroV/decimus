"""Сторож полноты прогона.

Гейт трижды был зелёным, когда проверки не выполнялись: 339 тестов блока базы
молча пропускались без переменной с доступами, а код возврата одинаков при
двухстах выполненных и при нуле. Сторож смотрит, состоялся ли прогон; сам он
тоже проверка, поэтому проверяется на испорченном входе — иначе это сторож,
который не может залаять (D129, #267).

Планок числа проверок здесь больше нет: сняты в D205 вместе с `test_floor` и
`core_test_floor`. Число тестов не говорит, что проверено, зато запрещает
удалять тест-налог.
"""

import importlib.util
from pathlib import Path

import pytest

_GUARD_PATH = Path(__file__).resolve().parents[1] / "scripts" / "check_run_complete.py"
_spec = importlib.util.spec_from_file_location("check_run_complete", _GUARD_PATH)
assert _spec is not None and _spec.loader is not None
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)


def _report(tests: int, skipped: int = 0, failures: int = 0, errors: int = 0) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?><testsuites name="pytest tests">'
        f'<testsuite name="pytest" errors="{errors}" failures="{failures}" '
        f'skipped="{skipped}" tests="{tests}" time="1.0"></testsuite></testsuites>'
    )


def test_полный_прогон_проходит() -> None:
    assert guard.check_report(_report(tests=12)) == []


def test_прогон_из_одной_проверки_проходит() -> None:
    """Число проверок сторожа больше не занимает: усох набор или нет — не его дело."""
    assert guard.check_report(_report(tests=1)) == []


def test_пропуск_считается_падением_а_не_пропуском() -> None:
    problems = guard.check_report(_report(tests=12, skipped=3))
    assert problems, "пропущенные проверки обязаны краснить прогон"
    assert "пропущено проверок: 3" in problems[0]


def test_прогон_без_единой_выполненной_проверки_краснеет() -> None:
    """Зелёный прогон, в котором ничего не выполнялось, — ровно та форма
    молчания, ради которой сторож заводился."""
    problems = guard.check_report(_report(tests=0))
    assert any("не выполнено ни одной проверки" in problem for problem in problems)


def test_всё_пропущено_краснеет_дважды() -> None:
    problems = guard.check_report(_report(tests=9, skipped=9))
    assert len(problems) == 2, problems


def test_пустой_или_битый_отчёт_краснеет() -> None:
    assert guard.check_report("не xml вовсе")
    assert guard.check_report('<?xml version="1.0"?><testsuites></testsuites>')


def test_отсутствующий_отчёт_не_считается_успехом(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        guard.main([str(tmp_path / "нет-такого.xml")])
