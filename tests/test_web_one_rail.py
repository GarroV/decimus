"""Левый столбец выбора в любом разделе — `pick_item` (D654).

Владелец 26.10.2026: «Сделай единый визуал для всех вкладок… заходишь в проверки — левое
меню одного вида. Заходишь в страны — другого вида. В администрирование захожу — по-третьему.
Приведи всё к единому визуалу». Строка колонки рисуется одним макросом `_pick_ui.html` и одним
набором правил `decimus-pick.css`; своя строка колонки в шаблоне или стиле — это тот самый
третий вид. Файлы читаются как текст: страницы и база не нужны.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "src" / "web"
ШАБЛОНЫ = sorted((WEB / "templates").rglob("*.html"))
СТИЛИ = sorted((WEB / "static").glob("*.css"))

#: Классы, которыми рисовали строку колонки до единого вида: у каждого раздела свой.
СВОИ_СТРОКИ = ("mx-rail__row", "sadmin__tab", "slist--countries", "slist--dodois")
ЧУЖАЯ_СТРОКА = re.compile(r'class="[^"]*\b[\w-]*rail__row\b')


@pytest.mark.parametrize("путь", ШАБЛОНЫ, ids=lambda p: p.relative_to(WEB).as_posix())
def test_шаблон_не_рисует_свою_строку_колонки(путь: Path) -> None:
    text = путь.read_text(encoding="utf-8")
    найдено = [имя for имя in СВОИ_СТРОКИ if имя in text]
    assert not найдено, (
        f"{путь.name}: {', '.join(найдено)}. Строка левой колонки — `pick_item` из "
        "`_pick_ui.html` (`.pk-item`), своих строк колонки не заводят (D654)."
    )
    assert not ЧУЖАЯ_СТРОКА.search(text), f"{путь.name}: строка колонки не через `.pk-item`"


@pytest.mark.parametrize("путь", СТИЛИ, ids=lambda p: p.name)
def test_стили_не_хранят_свою_строку_колонки(путь: Path) -> None:
    text = путь.read_text(encoding="utf-8")
    найдено = [имя for имя in СВОИ_СТРОКИ if имя in text]
    assert not найдено, (
        f"{путь.name}: мёртвые правила {', '.join(найдено)} — строка колонки одна, `.pk-item`"
    )


def test_экраны_с_колонкой_берут_pick_item() -> None:
    """Проверки, Методика, вкладки администрирования и список стран «Стран» — через макрос."""
    for имя in (
        "inspections/list.html",
        "methodology/index.html",
        "administration/_nav.html",
        "administration/countries.html",
    ):
        text = (WEB / "templates" / имя).read_text(encoding="utf-8")
        assert "pick_item" in text, f"{имя}: колонка выбора рисуется не через `pick_item`"
