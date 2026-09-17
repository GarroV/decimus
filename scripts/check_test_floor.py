#!/usr/bin/env python3
"""Сторож числа выполненных проверок: краснеет, когда прогон усох.

Код возврата pytest одинаков при двухстах выполненных проверках и при нуле,
поэтому зелёный гейт не отличает «проверено» от «не проверялось». На этом
проекте так трижды: 339 тестов блока базы молча пропускались без переменной с
доступами, а прогон оставался зелёным. Сторож сравнивает фактический прогон с
планкой, записанной в конфигурации раннера, и считает пропуск падением —
пропущенная проверка ничего не проверила (D129, #267).

Запуск: python scripts/check_test_floor.py reports/junit.xml [--floor N]
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path
from xml.etree import ElementTree

FLOOR_KEY = "test_floor"


def read_floor(pyproject: Path) -> int:
    """Планка живёт рядом с конфигурацией раннера, а не в голове у запускающего."""
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    floor = data.get("tool", {}).get("decimus", {}).get(FLOOR_KEY)
    if not isinstance(floor, int):
        raise SystemExit(
            f"{pyproject}: не задан [tool.decimus] {FLOOR_KEY} — планки нет, сторожить нечем"
        )
    return floor


def check_report(xml_text: str, floor: int) -> list[str]:
    """Возвращает список расхождений; пустой список означает «прогон полный»."""
    try:
        # Разбирается СОБСТВЕННЫЙ отчёт, записанный pytest в этом же прогоне,
        # а не присланный кем-то файл: тянуть defusedxml ради оснастки гейта —
        # лишняя зависимость.
        root = ElementTree.fromstring(xml_text)  # noqa: S314 -- свой отчёт, не внешний ввод
    except ElementTree.ParseError as err:
        return [f"отчёт прогона не читается: {err}"]

    suite = root if root.tag == "testsuite" else root.find("testsuite")
    if suite is None:
        return ["в отчёте прогона нет ни одного набора тестов — прогон не состоялся"]

    collected = int(suite.get("tests", 0))
    skipped = int(suite.get("skipped", 0))
    executed = collected - skipped

    problems: list[str] = []
    if skipped:
        problems.append(
            f"пропущено проверок: {skipped}. Пропуск по причине «нет окружения» "
            "считается падением: пропущенная проверка ничего не проверила"
        )
    if executed < floor:
        problems.append(
            f"выполнено проверок: {executed} при планке {floor}. Прогон усох на "
            f"{floor - executed} — либо тесты исчезли, либо они не выполнялись"
        )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", help="путь к JUnit XML прогона")
    parser.add_argument("--floor", type=int, default=None, help="планка числом")
    parser.add_argument(
        "--pyproject",
        default=str(Path(__file__).resolve().parents[1] / "pyproject.toml"),
        help="откуда брать планку, если она не задана ключом",
    )
    args = parser.parse_args(argv)

    report = Path(args.report)
    if not report.is_file():
        raise SystemExit(
            f"{report}: отчёта прогона нет. Отсутствующий отчёт — не успех, "
            "а признак того, что прогон не дошёл до записи результата"
        )

    floor = args.floor if args.floor is not None else read_floor(Path(args.pyproject))
    problems = check_report(report.read_text(encoding="utf-8"), floor)
    if problems:
        print(f"ПЛАНКА ПРОГОНА НЕ ВЗЯТА ({report}):", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        raise SystemExit(1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
