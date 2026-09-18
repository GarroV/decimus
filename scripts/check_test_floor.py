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

#: Планка ЯДРА — отдельно от общей, потому что D129 развёл набор на два слоя с
#: разной ценой ошибки, а сторож этого не знал (#283).
#:
#: Общая планка мерит весь набор. Под D129 поверхностная переборка подлежит
#: удалению — и каждое такое удаление роняет общее число, то есть выглядит
#: ослаблением гейта и правится опусканием планки. Пока планка одна, вместе с
#: ней молча опускается и защита ядра: удалил полсотни тестов бота, опустил
#: число на полсотни — и не заметил, что в том же коммите перестал собираться
#: `tests/test_engine_*`.
#:
#: Поэтому планок ДВЕ. Общая говорит «набор усох», планка ядра — «усохло то,
#: где сбой молчит». Опустить первую, не тронув вторую, теперь можно; опустить
#: вторую — отдельное осознанное движение.
CORE_FLOOR_KEY = "core_test_floor"
CORE_PREFIXES_KEY = "core_test_prefixes"


def read_floor(pyproject: Path) -> int:
    """Планка живёт рядом с конфигурацией раннера, а не в голове у запускающего."""
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    floor = data.get("tool", {}).get("decimus", {}).get(FLOOR_KEY)
    if not isinstance(floor, int):
        raise SystemExit(
            f"{pyproject}: не задан [tool.decimus] {FLOOR_KEY} — планки нет, сторожить нечем"
        )
    return floor


def read_core(pyproject: Path) -> tuple[int, tuple[str, ...]]:
    """Планка ядра и то, по чему ядро опознаётся в отчёте прогона.

    Отсутствие настройки — не «ядра нет», а несторожимое ядро, и это отказ:
    ровно та форма молчания, ради которой сторож заводился (#207).
    """
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    раздел = data.get("tool", {}).get("decimus", {})
    floor = раздел.get(CORE_FLOOR_KEY)
    prefixes = раздел.get(CORE_PREFIXES_KEY)
    if not isinstance(floor, int):
        raise SystemExit(
            f"{pyproject}: не задан [tool.decimus] {CORE_FLOOR_KEY} — "
            "ядро не сторожится, а сбой в нём молчит"
        )
    if not isinstance(prefixes, list) or not all(isinstance(x, str) for x in prefixes):
        raise SystemExit(
            f"{pyproject}: не задан [tool.decimus] {CORE_PREFIXES_KEY} — "
            "непонятно, какие проверки считать проверками ядра"
        )
    if not prefixes:
        raise SystemExit(
            f"{pyproject}: {CORE_PREFIXES_KEY} пуст — под планку ядра не попадёт "
            "ни одна проверка, и она будет зелёной всегда"
        )
    return floor, tuple(prefixes)


def _выполнено_в_ядре(suite: ElementTree.Element, prefixes: tuple[str, ...]) -> int:
    """Сколько проверок ЯДРА действительно выполнено в этом прогоне.

    Пропущенная и упавшая с ошибкой сбора не считаются выполненными: смысл
    сторожа в том, что проверка либо отработала, либо её не было.
    """
    выполнено = 0
    for случай in suite.iter("testcase"):
        имя = случай.get("classname", "")
        if not any(имя.startswith(x) for x in prefixes):
            continue
        if случай.find("skipped") is not None or случай.find("error") is not None:
            continue
        выполнено += 1
    return выполнено


def check_report(
    xml_text: str, floor: int, core: tuple[int, tuple[str, ...]] | None = None
) -> list[str]:
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
            f"{floor - executed} — либо тесты исчезли, либо они не выполнялись. "
            f"Если переборка удалена намеренно (D129) — опустить [tool.decimus] "
            f"{FLOOR_KEY} тем же коммитом: это законное движение, а не обход гейта"
        )
    if core is not None:
        core_floor, prefixes = core
        в_ядре = _выполнено_в_ядре(suite, prefixes)
        if в_ядре < core_floor:
            problems.append(
                f"выполнено проверок ЯДРА: {в_ядре} при планке {core_floor}. "
                f"Усохло на {core_floor - в_ядре} — здесь сбой молчит, и "
                f"опускать [tool.decimus] {CORE_FLOOR_KEY} заодно с общей планкой нельзя"
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
    # Планка ядра берётся из конфигурации ВСЕГДА, даже когда общая задана
    # ключом: точечный прогон с `--floor` не повод перестать сторожить ядро.
    core = read_core(Path(args.pyproject))
    problems = check_report(report.read_text(encoding="utf-8"), floor, core)
    if problems:
        print(f"ПЛАНКА ПРОГОНА НЕ ВЗЯТА ({report}):", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        raise SystemExit(1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
