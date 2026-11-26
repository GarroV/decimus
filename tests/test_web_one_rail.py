"""Левый столбец выбора в любом разделе — `pick_item` (D655).

Строка колонки рисуется одним макросом `_pick_ui.html` и одним набором правил
`decimus-pick.css`. После D782 реестр проверок занимает всю ширину: страны выбираются
в общем блоке фильтров, выбранная проверка открывается в общей выезжающей панели.
Файлы читаются как текст: страницы и база не нужны.
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
        "`_pick_ui.html` (`.pk-item`), своих строк колонки не заводят (D655)."
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
    """Методика, вкладки администрирования и список стран «Стран» — через макрос."""
    for имя in (
        "methodology/index.html",
        "administration/_nav.html",
        "administration/countries.html",
    ):
        text = (WEB / "templates" / имя).read_text(encoding="utf-8")
        assert "pick_item" in text, f"{имя}: колонка выбора рисуется не через `pick_item`"


def test_проверки_используют_общие_фильтры_и_выезжающую_панель() -> None:
    """D782: реестр без отдельной колонки стран сохраняет общий список и панель."""
    text = (WEB / "templates" / "inspections" / "list.html").read_text(encoding="utf-8")
    тело = text.split("{% block body %}")[1].split("{% endblock %}")[0]
    assert 'extends "_split_page.html"' in text
    assert 'class="rg-filters"' in тело and "pick(chip)" in тело
    assert "period_picker(" in тело and 'name="q"' in тело
    assert "super()" in тело
    assert 'class="mx-shell' not in тело and "<aside" not in тело
    assert "{% block split_list %}" in text and "{% block split_detail %}" in text
