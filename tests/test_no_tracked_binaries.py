"""В публичном репозитории нет бинарников вне белого списка путей.

Картинка, PDF или документ Office, попавшие в историю, остаются в ней навсегда, а
в публичном репозитории их видит кто угодно (скриншот с данными, выгрузка). Новый
бинарник должен попасть сюда осознанно — строкой белого списка с причиной. БД не
нужна.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

BINARY_SUFFIXES = (".png", ".jpg", ".jpeg", ".pdf", ".docx", ".xlsx", ".zip")

#: Разрешённые префиксы путей. Каждая строка — с причиной.
ALLOWED_PREFIXES: tuple[str, ...] = (
    # Иконки веб-админки и мини-аппа (apple-touch-icon, icon-*.png).
    "src/web/static/",
)

HINT = (
    "бинарный файл вне белого списка: если он нужен, добавь его путь в "
    "ALLOWED_PREFIXES этого теста с причиной; иначе убери из git (в публичном "
    "репозитории он останется в истории)"
)


def tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"],  # noqa: S607 — git из PATH, как в соседних тестах
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [name for name in out.split("\0") if name]


def unexpected_binaries(names: list[str]) -> list[str]:
    return [
        name
        for name in names
        if name.lower().endswith(BINARY_SUFFIXES) and not name.startswith(ALLOWED_PREFIXES)
    ]


def test_no_tracked_binaries_outside_allowlist() -> None:
    found = unexpected_binaries(tracked_files())
    assert not found, "\n".join([*found, "", HINT])


@pytest.mark.parametrize("name", ["docs/shot.PNG", "notes/report.pdf", "data/a.xlsx", "x.zip"])
def test_checker_flags_new_binary(name: str) -> None:
    assert unexpected_binaries([name]) == [name]


def test_checker_accepts_allowlisted_and_text_files() -> None:
    names = [
        "src/web/static/icon-32.png",
        "docs/readme.md",
    ]
    assert unexpected_binaries(names) == []
