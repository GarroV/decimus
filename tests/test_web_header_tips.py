"""Шапка экрана без облака текста (D631, D632): служебное — под значком «?», столбиком.

Владелец 23.10.2026: «там где ты кидаешь целую кучу информации непонятной … общим
облаком. Давай это все будем скрывать за подсказкой». В шапке — заголовок и действия;
свежесть, счётчики и пояснения лежат под «?» (макрос `_info_tip.html`), по строке на
факт. Пояснения не удаляются, а переезжают; уходит только дубль того, что уже на экране
(период рядом с переключателем периода).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from flask import render_template_string
from flask.testing import FlaskClient
from jinja2 import Environment, FileSystemLoader
from test_web_app import ТЕНАНТ, шапка
from test_web_usage import _вошедший, _заглушка
from web_harness import войти, подменить_двери, собрать

from src.web import inspections as data

TEMPLATES = Path(__file__).resolve().parents[1] / "src" / "web" / "templates"
# Классы строк-облаков в шапке. Исключения — шапки подтверждения входа: логин там и есть
# содержание экрана (кто подтверждается), а не служебная строка.
ОБЛАКО = re.compile(r"""class\s*=\s*["'][^"']*\b(?:shead__sub|ov-head__sub|pk-head__facts)\b""")
ДОПУЩЕНО = {"settings/continue.html", "settings/confirm.html"}

_ТИП = "{% from \"_info_tip.html\" import info_tip %}{{ info_tip(label, title, rows, 'demo') }}"


def найти_облака(root: Path) -> list[str]:
    """Шаблоны под `root` со строкой-облаком в шапке: «путь:строка»."""
    найдено = []
    for path in sorted(root.rglob("*.html")):
        имя = path.relative_to(root).as_posix()
        if имя in ДОПУЩЕНО:
            continue
        for номер, строка in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if ОБЛАКО.search(строка):
                найдено.append(f"{имя}:{номер}")
    return найдено


def шапка_без_подсказки(страница: str, открытие: str) -> tuple[str, str]:
    """Шапка экрана целиком и она же без столбика под «?»: (вся, без столбика)."""
    начало = страница.index(открытие)
    конец = страница.index("</header>", начало)
    вся = страница[начало:конец]
    return вся, re.sub(r'<div class="info-tip__pop.*?</ul>\s*</div>', "", вся, flags=re.S)


def test_макрос_рисует_значок_и_столбик_строка_на_факт() -> None:
    # Arrange
    app = собрать(tenant="HQ")

    # Act
    with app.test_request_context("/?lang=ru"):
        html = render_template_string(
            _ТИП, label="Сводка", title="Итоги", rows=["проверок: 3", "поездок: 1"]
        )
        без_названия = render_template_string(_ТИП, label="Сводка", title="", rows=["одна"])

    # Assert
    assert 'aria-label="Сводка"' in html and 'role="button"' in html and 'tabindex="0"' in html
    assert html.count("<li>") == 2
    assert "<li>проверок: 3</li>" in html and "<li>поездок: 1</li>" in html
    assert "Итоги" in html and " · " not in html
    assert 'aria-describedby="info-demo"' in html and 'id="info-demo"' in html
    assert "popover__group" not in без_названия


def test_макрос_экранирует_строки() -> None:
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=True)
    html = env.get_template("_info_tip.html").module.info_tip("x", "", ["<b>a</b>"])

    assert "<b>a</b>" not in html and "&lt;b&gt;a&lt;/b&gt;" in html


def test_шаблоны_без_строк_облака_в_шапке() -> None:
    assert найти_облака(TEMPLATES) == [], (
        "Строка служебного текста под заголовком запрещена (D632): число, свежесть или "
        "пояснение уходит под «?» — макрос `info_tip` из `_info_tip.html`."
    )


def test_сторож_ловит_облако_в_испорченной_копии(tmp_path: Path) -> None:
    # Arrange — шапка с пояснением строкой, как её рисовали до D632.
    (tmp_path / "screen.html").write_text(
        '<header><p class="shead__sub">Пояснение · раз · два</p></header>\n', encoding="utf-8"
    )

    # Act
    найдено = найти_облака(tmp_path)

    # Assert — подмена сработала (файл не пуст) и сторож назвал строку.
    assert (tmp_path / "screen.html").stat().st_size > 0
    assert найдено == ["screen.html:1"]


def test_расход_пояснение_под_знаком_вопроса_а_не_под_заголовком(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _вошедший(monkeypatch, role="superadmin")
    _заглушка(monkeypatch)

    страница = client.get("/users?tab=usage").get_data(as_text=True)  # type: ignore[attr-defined]

    вся, без_столбика = шапка_без_подсказки(страница, '<header class="shead">')
    assert "Сколько токенов и денег уходит на нейросеть" in вся
    assert "Сколько токенов и денег уходит на нейросеть" not in без_столбика
    assert "info-tip__mark" in без_столбика


@pytest.fixture
def стенд(monkeypatch: pytest.MonkeyPatch) -> Iterator[FlaskClient]:
    monkeypatch.setattr(
        data,
        "load_dated",
        lambda **_: (шапка(unit_name="Белград-1", inspection_date=date(2026, 9, 10)),),
    )
    подменить_двери(monkeypatch, tenant=ТЕНАНТ)
    with собрать(tenant=ТЕНАНТ).test_client() as client:
        assert войти(client).status_code == 302
        yield client


def test_календарь_числа_под_знаком_вопроса_период_не_повторён(стенд: FlaskClient) -> None:
    страница = стенд.get("/calendar?from=2026-09-01&to=2026-09-30").get_data(as_text=True)

    вся, без_столбика = шапка_без_подсказки(страница, '<header class="shead">')
    assert "<li>проверок: 1</li>" in вся and "<li>поездок: " in вся
    assert "проверок:" not in без_столбика and "поездок:" not in без_столбика
    assert "сентябр" not in без_столбика.lower() and "2026" not in без_столбика


def test_настройки_пояснение_столбиком_по_фактам(стенд: FlaskClient) -> None:
    страница = стенд.get("/settings?lang=ru").get_data(as_text=True)

    вся, без_столбика = шапка_без_подсказки(страница, '<header class="shead">')
    assert вся.count("<li>") == 3
    assert "Ваш профиль: подключения и вход." in вся
    assert "Ваш профиль" not in без_столбика and "ssec__note" not in без_столбика
