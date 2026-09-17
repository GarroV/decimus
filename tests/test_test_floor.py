"""Сторож числа выполненных проверок.

Гейт трижды был зелёным, когда проверки не выполнялись: 339 тестов блока базы
молча пропускались без переменной с доступами, а код возврата одинаков при
двухстах выполненных и при нуле. Сторож сравнивает фактический прогон с планкой
в репозитории; сам он тоже проверка, поэтому проверяется на испорченном входе —
иначе это сторож, который не может залаять (D129, #267).
"""

import importlib.util
from pathlib import Path

import pytest

_GUARD_PATH = Path(__file__).resolve().parents[1] / "scripts" / "check_test_floor.py"
_spec = importlib.util.spec_from_file_location("check_test_floor", _GUARD_PATH)
assert _spec is not None and _spec.loader is not None
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)


def _report(tests: int, skipped: int = 0, failures: int = 0, errors: int = 0) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?><testsuites name="pytest tests">'
        f'<testsuite name="pytest" errors="{errors}" failures="{failures}" '
        f'skipped="{skipped}" tests="{tests}" time="1.0"></testsuite></testsuites>'
    )


def test_прогон_на_планке_и_выше_проходит() -> None:
    assert guard.check_report(_report(tests=2878), floor=2878) == []
    assert guard.check_report(_report(tests=3000), floor=2878) == []


def test_усохший_прогон_краснеет() -> None:
    # Arrange
    report = _report(tests=2539)
    # Act
    problems = guard.check_report(report, floor=2878)
    # Assert
    assert problems, "прогон на 339 проверок меньше планки обязан покраснеть"
    assert "2539" in problems[0] and "2878" in problems[0]


def test_пропуск_считается_падением_а_не_пропуском() -> None:
    problems = guard.check_report(_report(tests=2878, skipped=12), floor=2878)
    assert problems, "пропуск по причине «нет окружения» — это падение"
    assert "пропущ" in problems[0].lower()


def test_пропуск_вычитается_из_выполненных() -> None:
    """2878 собранных при 300 пропущенных — это 2578 выполненных, а не 2878."""
    problems = guard.check_report(_report(tests=2878, skipped=300), floor=2878)
    assert len(problems) == 2, problems


def test_пустой_или_битый_отчёт_краснеет() -> None:
    assert guard.check_report("", floor=1)
    assert guard.check_report("<testsuites></testsuites>", floor=1)


def test_планка_читается_из_конфигурации_раннера() -> None:
    floor = guard.read_floor(Path(__file__).resolve().parents[1] / "pyproject.toml")
    assert isinstance(floor, int) and floor > 0


def test_отсутствующий_отчёт_не_считается_успехом(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        guard.main([str(tmp_path / "нет-такого.xml"), "--floor", "1"])
    assert exc.value.code != 0
