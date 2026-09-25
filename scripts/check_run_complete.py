#!/usr/bin/env python3
"""Сторож полноты прогона: краснеет, когда проверки не выполнялись.

Код возврата pytest одинаков при двухстах выполненных проверках и при нуле,
поэтому зелёный гейт сам по себе не отличает «проверено» от «не проверялось».
На этом проекте так было трижды: 339 тестов блока базы молча пропускались без
переменной с доступами, а прогон оставался зелёным (D129, #267).

Сторож отвечает на один вопрос: прогон **состоялся**? Пропущенная проверка
ничего не проверила, отсутствующий отчёт — не успех, а признак того, что до
записи результата дело не дошло.

**Чего здесь больше нет.** До D205 сторож сверял ещё и ЧИСЛО выполненных
проверок с планками `test_floor` (2885) и `core_test_floor` (534) в
`pyproject.toml`. Планки сняты: число тестов не говорит, что проверено, зато
запрещает удалять тест — любое сокращение переборки краснило гейт, и из-за
этого T309 («удалить тесты-налог») стояла замороженной. Решение владельца
17.09.2026, дословно: «мы не должны строить тесты ради тестов». То, ради чего
сторож заводился, — молчаливый зелёный прогон — осталось здесь целиком; ушла
только метрика, которая цементировала налог.

Запуск: python scripts/check_run_complete.py reports/junit.xml
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from xml.etree import ElementTree


def check_report(xml_text: str) -> list[str]:
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
    if executed <= 0:
        problems.append(
            "не выполнено ни одной проверки. Это не зелёный прогон, а прогон, "
            "которого не было: сбор тестов не состоялся или всё отсеялось выборкой"
        )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", help="путь к JUnit XML прогона")
    args = parser.parse_args(argv)

    report = Path(args.report)
    if not report.is_file():
        raise SystemExit(
            f"{report}: отчёта прогона нет. Отсутствующий отчёт — не успех, "
            "а признак того, что прогон не дошёл до записи результата"
        )

    problems = check_report(report.read_text(encoding="utf-8"))
    if problems:
        print(f"ПРОГОН НЕ СОСТОЯЛСЯ ({report}):", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        raise SystemExit(1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
