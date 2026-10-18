"""#607: два теста с одним именем в одном файле — первый молча перестаёт запускаться.

Линтер этого не ловит: у тестов стоят декораторы (`parametrize`, `asyncio`), а
переопределение украшенной функции pyflakes считает намеренным. Проверка здесь —
по синтаксическому дереву каждого файла тестов, без импорта.
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

TESTS = Path(__file__).resolve().parent


def _повторы(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    имена: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith(
            "test"
        ):
            имена.append(node.name)
        if isinstance(node, ast.ClassDef):
            имена += [
                f"{node.name}.{m.name}"
                for m in node.body
                if isinstance(m, ast.FunctionDef | ast.AsyncFunctionDef)
                and m.name.startswith("test")
            ]
    return [имя for имя, сколько in Counter(имена).items() if сколько > 1]


def test_в_файле_нет_двух_тестов_с_одним_именем() -> None:
    найдено = {
        p.name: повторы for p in sorted(TESTS.rglob("test_*.py")) if (повторы := _повторы(p))
    }
    assert not найдено, f"второй тест с тем же именем прячет первый: {найдено}"


def test_проверка_видит_повтор(tmp_path: Path) -> None:
    файл = tmp_path / "test_x.py"
    файл.write_text(
        "import pytest\n\n"
        "def test_a():\n    pass\n\n"
        "@pytest.mark.parametrize('x', [1])\n"
        "def test_a(x):\n    pass\n",
        encoding="utf-8",
    )
    assert _повторы(файл) == ["test_a"]
