"""Каждая фоновая задача бота названа в `docs/38-runbook.md` (D738).

Новая выгрузка без раздела «сломалось → куда смотреть» — задача, которую через месяц никто не найдёт
и не починит без автора. Реестр задач — сам планировщик бота: каждый
`asyncio.create_task(модуль.функция(...))` в `src/bot/app.py`, плюс любой `src/bot/*_loader.py`,
даже если его забыли подключить. Проверяется упоминание имени модуля в документе. Базы не нужно.

Проверка способна упасть: тест ниже убирает из документа по одной задаче и требует отказа с именем
именно этой задачи; имена берутся из кода, а не из списка в тесте.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RUNBOOK = ROOT / "docs" / "38-runbook.md"
APP = ROOT / "src" / "bot" / "app.py"
BOT_DIR = ROOT / "src" / "bot"


def scheduled_modules() -> set[str]:
    """Модули, чьи функции планировщик запускает как `asyncio.create_task(модуль.функция())`."""
    modules: set[str] = set()
    for node in ast.walk(ast.parse(APP.read_text(encoding="utf-8"))):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr != "create_task" or not node.args:
            continue
        job = node.args[0]
        if (
            isinstance(job, ast.Call)
            and isinstance(job.func, ast.Attribute)
            and isinstance(job.func.value, ast.Name)
        ):
            modules.add(job.func.value.id)
    return modules


def job_modules() -> set[str]:
    """Задачи, которые обязаны быть в runbook: из планировщика и все `*_loader.py` рядом с ним."""
    loaders = {path.stem for path in BOT_DIR.glob("*_loader.py")}
    return scheduled_modules() | loaders


def unmentioned(modules: set[str], runbook_text: str) -> list[str]:
    """Модули, имя которых не встречается в документе."""
    return sorted(name for name in modules if name not in runbook_text)


def test_scheduler_registry_is_found() -> None:
    """Реестр не пуст: иначе проверка ниже ничего бы не проверяла."""
    jobs = job_modules()
    assert {"maps_loader", "dodois_loader", "health_loader"} <= jobs, (
        f"Реестр фоновых задач не прочитался из {APP.relative_to(ROOT)}: нашлось {sorted(jobs)}"
    )


def test_every_background_job_is_in_the_runbook() -> None:
    missing = unmentioned(job_modules(), RUNBOOK.read_text(encoding="utf-8"))
    assert not missing, (
        f"Фоновые задачи бота без упоминания в {RUNBOOK.relative_to(ROOT)}: "
        f"{', '.join(missing)}. "
        "Добавьте строку в таблицу «Фоновые задачи бота» и раздел «сломалось → куда смотреть → "
        "что делать» (симптом, где смотреть, частые причины, что сделать, когда звать владельца)."
    )


@pytest.mark.parametrize("job", sorted(job_modules()))
def test_check_fails_when_a_job_is_removed_from_the_runbook(job: str) -> None:
    """Проверка не зелёная по умолчанию: без упоминания задачи она называет именно эту задачу."""
    text = RUNBOOK.read_text(encoding="utf-8").replace(job, "")
    assert unmentioned(job_modules(), text) == [job]
