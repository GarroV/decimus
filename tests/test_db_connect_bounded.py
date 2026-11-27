"""Прямые соединения с базой в `src/` открываются только со сроками (`src/db/timeouts.py`).

Голый `psycopg.connect` ждёт соединение, запрос и блокировку без предела: один
зависший запрос держит работника до рестарта. Сторож читает исходники, а не
поведение, — поэтому видит и путь, который тесты с базой не проходят.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest
from psycopg.conninfo import conninfo_to_dict

from src.db import timeouts

КОРЕНЬ = Path(__file__).resolve().parent.parent
SRC = КОРЕНЬ / "src"

#: Где голый вызов законен, и почему.
ИСКЛЮЧЕНИЯ = {
    # Сама дверь.
    "src/db/timeouts.py",
    # Накат миграций: долгая правка схемы, срок ей не задаётся.
    "src/db/migrate.py",
    # Ярус ниже базы (импортировать `src.db` ему нельзя), сроки — прямо в вызове.
    "src/settings_read.py",
}


def _голые_вызовы(путь: Path) -> list[int]:
    дерево = ast.parse(путь.read_text(encoding="utf-8"), filename=str(путь))
    строки: list[int] = []
    for узел in ast.walk(дерево):
        if isinstance(узел, ast.ImportFrom) and узел.module == "psycopg":
            if any(имя.name == "connect" for имя in узел.names):
                строки.append(узел.lineno)
        if not isinstance(узел, ast.Call):
            continue
        функция = узел.func
        if (
            isinstance(функция, ast.Attribute)
            and функция.attr == "connect"
            and isinstance(функция.value, ast.Name)
            and функция.value.id == "psycopg"
        ):
            строки.append(узел.lineno)
    return строки


def test_в_src_нет_голого_psycopg_connect() -> None:
    найдено = []
    for путь in sorted(SRC.rglob("*.py")):
        имя = путь.relative_to(КОРЕНЬ).as_posix()
        if имя in ИСКЛЮЧЕНИЯ:
            continue
        найдено += [f"{имя}:{строка}" for строка in _голые_вызовы(путь)]
    assert not найдено, (
        "Соединение без сроков ожидания: замените psycopg.connect(...) на "
        "timed_connect(...) из src/db/timeouts.py — " + ", ".join(найдено)
    )


def test_исключения_существуют() -> None:
    # Переименованный файл не должен оставлять за собой молчаливую дыру в списке.
    for имя in ИСКЛЮЧЕНИЯ:
        assert (КОРЕНЬ / имя).is_file(), имя


def test_timed_connect_передаёт_сроки_и_параметры(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("DB_STATEMENT_TIMEOUT_S", "DB_LOCK_TIMEOUT_S", "DB_BATCH_STATEMENT_TIMEOUT_S"):
        monkeypatch.delenv(var, raising=False)
    вызовы: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        timeouts.psycopg, "connect", lambda dsn, **kw: вызовы.append((dsn, kw)) or "conn"
    )

    assert timeouts.timed_connect("postgresql://a@db/x", autocommit=True) == "conn"
    timeouts.timed_connect("postgresql://a@db/x", batch=True, connect_timeout=3)

    обычный, пакетный = вызовы
    assert conninfo_to_dict(обычный[0])["options"] == (
        "-c statement_timeout=30000 -c lock_timeout=10000"
    )
    assert conninfo_to_dict(обычный[0])["connect_timeout"] == "10"
    assert обычный[1] == {"autocommit": True}
    assert "statement_timeout=300000" in conninfo_to_dict(пакетный[0])["options"]
    assert пакетный[1] == {"connect_timeout": 3}
