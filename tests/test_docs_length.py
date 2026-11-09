"""Документ в docs/ не длиннее 800 строк (D738).

Документ на три с половиной тысячи строк читают с начала до усталости: новичок не находит нужного,
а правящий не видит, что рядом лежит противоречащий кусок. Предел держится проверкой, а не
договорённостью: перерос — разбейте по теме, а не поднимайте предел.

Не считаются: сгенерированные `00-map.md` и `inventory.md` (их длину задаёт код), а также
`docs/history/` (исторические записи), `docs/furca/` (журналы и контракты стройки) и
`docs/superpowers/` (планы и спеки). Базы не нужно. Проверка способна упасть: тест ниже
подсовывает ей документ на 801 строку и требует отказа.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

#: Предел строк на документ.
MAX_LINES = 800

#: Документы, длину которых определяет генератор (`make map`), а не автор.
GENERATED = frozenset({"00-map.md", "inventory.md"})
#: Каталоги, на которые предел не распространяется, — с причиной в докстринге модуля.
EXEMPT_DIRS = frozenset({"history", "furca", "superpowers"})


def counted_documents() -> list[Path]:
    """Документы, на которые распространяется предел."""
    found = []
    for path in sorted(DOCS.rglob("*.md")):
        relative = path.relative_to(DOCS)
        if relative.parts[0] in EXEMPT_DIRS or relative.as_posix() in GENERATED:
            continue
        found.append(path)
    return found


def too_long(text: str, limit: int = MAX_LINES) -> bool:
    return len(text.splitlines()) > limit


@pytest.mark.parametrize("path", counted_documents(), ids=lambda p: p.relative_to(DOCS).as_posix())
def test_document_is_not_longer_than_the_limit(path: Path) -> None:
    lines = len(path.read_text(encoding="utf-8").splitlines())
    assert lines <= MAX_LINES, (
        f"{path.relative_to(ROOT)}: {lines} строк при пределе {MAX_LINES}. Разбейте документ по "
        "теме на несколько (новый — с номером из свободных, в README и docs/00-map.md), не "
        "поднимайте предел (D738)."
    )


def test_the_check_fails_on_a_too_long_document() -> None:
    """Проверка, которая не падает на сломанном входе, проверкой не является."""
    assert too_long("строка\n" * (MAX_LINES + 1))
    assert not too_long("строка\n" * MAX_LINES)


def test_the_exempt_directories_exist() -> None:
    """Опечатка в имени каталога молча включила бы его в счёт или выключила бы проверку."""
    missing = [name for name in sorted(EXEMPT_DIRS) if not (DOCS / name).is_dir()]
    assert not missing, f"в EXEMPT_DIRS названы каталоги, которых нет: {missing}"
