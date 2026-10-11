"""Таблицы стилей веба целы: скобки сходятся, подключённые файлы существуют.

Незакрытая скобка убивает все правила ниже неё молча — экран выглядит «как
будто стиль не применился» (#655), а ни один тест страницы этого не видит.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "src" / "web" / "static"
TEMPLATES = Path(__file__).resolve().parents[1] / "src" / "web" / "templates"
CSS_FILES = sorted(STATIC.glob("*.css"))
_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_STRING = re.compile(r"\"[^\"\n]*\"|'[^'\n]*'")
_LINK = re.compile(r"filename=['\"]([\w.-]+\.css)['\"]")


def _balance(text: str) -> int:
    """Сумма `{` минус `}` вне комментариев и строк; 0 — всё закрыто."""
    bare = _STRING.sub('""', _COMMENT.sub("", text))
    return bare.count("{") - bare.count("}")


def test_css_файлы_найдены() -> None:
    assert CSS_FILES, "нет ни одной таблицы стилей — путь теста устарел"


@pytest.mark.parametrize("файл", CSS_FILES, ids=lambda p: p.name)
def test_скобки_в_таблице_стилей_сходятся(файл: Path) -> None:
    assert _balance(file_text(файл)) == 0, f"{файл.name}: скобки не сходятся"


def test_проверка_скобок_видит_незакрытое() -> None:
    # Порча: без неё проверка могла бы быть зелёной на любом входе.
    assert _balance(".a { color: red; .b { color: blue; }") == 1
    assert _balance("/* } */ .a { content: '}'; }") == 0


def test_подключённые_в_шаблонах_таблицы_существуют() -> None:
    names = {
        m for html in TEMPLATES.rglob("*.html") for m in _LINK.findall(html.read_text("utf-8"))
    }
    assert names, "в шаблонах не нашлось ни одной таблицы — шаблон проверки устарел"
    missing = sorted(n for n in names if not (STATIC / n).exists())
    assert not missing, f"шаблоны подключают несуществующие таблицы: {missing}"


def file_text(path: Path) -> str:
    return path.read_text("utf-8")


_HEAD_SCRIPT = re.compile(r"<script\b[^>]*>", re.S)


def _скрипты_без_метки(html: str) -> list[str]:
    return [s for s in _HEAD_SCRIPT.findall(html) if "data-shell" not in s]


def test_скрипты_оболочки_помечены_для_перехода() -> None:
    """#664: `nav.js` отличает скрипты оболочки по `data-shell`; без метки
    каждый переход между разделами стал бы полной перезагрузкой."""
    base = (TEMPLATES / "base.html").read_text("utf-8")
    шапка = base.split("</head>", 1)[0]
    assert _HEAD_SCRIPT.findall(шапка), "в шапке base.html нет скриптов — тест устарел"
    assert _скрипты_без_метки(шапка) == []
    assert "script[src]:not([data-shell])" in file_text(STATIC / "nav.js")


def test_проверка_метки_видит_скрипт_без_неё() -> None:
    # Порча: скрипт оболочки без метки обязан найтись.
    assert _скрипты_без_метки('<script src="x.js" defer></script>') == ['<script src="x.js" defer>']
