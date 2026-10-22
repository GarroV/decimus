"""Никаких рядов чипов и тегов в шапках экранов (D611).

Владелец 22.10.2026: «Все сворачиваем либо в выпадающие списки, либо в какие-то
столбцы, либо в контекстное меню. Все, никаких шапок с тегами». Сторож смотрит
на шаблоны экранов: классы чипов-фильтров (`ov-chip`, `speriod__chip`, `rt-seg`,
`seg`, `seg__item`, `seg__current`) в них не живут. Отбор рисует `pick()` из
`_pick.html` — это `<select>`.
"""

from __future__ import annotations

import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

TEMPLATES = Path(__file__).resolve().parents[1] / "src" / "web" / "templates"
ЧИП = re.compile(
    r"""class\s*=\s*["'][^"']*\b(?:ov-chip|speriod__chip|rt-seg|seg|seg__item|seg__current)\b"""
)
# Форма «Новое предписание» переделывается отдельной задачей (ветка osb-columns, D611):
# строка уходит отсюда, когда та ветка в main.
ПОКА_НЕ_ПЕРЕДЕЛАНО = frozenset({"actions/prescription_form.html"})


def найти_ряды_чипов(root: Path) -> list[str]:
    """Шаблоны под `root`, где есть класс чипа-фильтра: «путь:строка»."""
    найдено = []
    for path in sorted(root.rglob("*.html")):
        имя = path.relative_to(root).as_posix()
        if имя in ПОКА_НЕ_ПЕРЕДЕЛАНО:
            continue
        for номер, строка in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if ЧИП.search(строка):
                найдено.append(f"{имя}:{номер}")
    return найдено


def test_шаблоны_экранов_без_рядов_чипов() -> None:
    assert найти_ряды_чипов(TEMPLATES) == [], (
        "Ряд чипов в шапке — запрещён (D611). Отбор — `pick()` из `_pick.html` (выпадающий "
        "список), период — календарь со стрелками."
    )


def test_сторож_ловит_чип_в_испорченной_копии(tmp_path: Path) -> None:
    # Arrange — копия шаблона с чипом, как его рисовали до D611.
    (tmp_path / "screen.html").write_text(
        '<div><a class="speriod__chip is-on" href="/x">Месяц</a></div>\n', encoding="utf-8"
    )

    # Act
    найдено = найти_ряды_чипов(tmp_path)

    # Assert — подмена сработала (файл не пуст) и сторож назвал строку.
    assert (tmp_path / "screen.html").stat().st_size > 0
    assert найдено == ["screen.html:1"]


def test_отбор_выводится_выпадающим_списком() -> None:
    # Arrange
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=True)
    macro = env.get_template("_pick.html").module.pick
    chip = {
        "label": "Страна",
        "current": "RS",
        "current_title": "Сербия",
        "options": [
            {"title": "все", "href": "/o", "selected": False, "count": None},
            {"title": "Сербия", "href": "/o?country=RS", "selected": True, "count": 12},
        ],
    }

    # Act
    html = str(macro(chip))

    # Assert
    assert "<select" in html and "data-pick-nav" in html
    assert '<option value="/o?country=RS" selected>Сербия · 12</option>' in html
    assert "ov-chip" not in html
