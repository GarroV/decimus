# ruff: noqa: F811
"""Ряд действий карточки проверки не двигается при раскрытии окон: реальный DOM, Chromium.

Окно действия («Исправить», корзина «Удалить проверку») со скриптом `hact.js` встаёт в слот под всем
рядом и сдвигает содержимое ниже; кнопки ряда остаются на тех же местах — иначе
интерфейс прыгает под рукой. Страница — синтетический HTML из Flask без сервера, стили
подключены настоящие. Снимки состояний — в каталог из `CARD_STATES_DIR`, если задан.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from conftest import chromium_executable
from playwright.sync_api import sync_playwright
from test_web_acceptance import _приёмка, админ, стенд  # noqa: F401
from test_web_proofread_browser import _лист

STATIC = Path(__file__).resolve().parents[1] / "src/web/static"
ПОВЕРХНОСТИ = {
    "страница": "/inspections/x",
    "панель": "/inspections?inspection=x",
}
ЭКРАНЫ = {"1280": (1280, 900), "390": (390, 844)}
ДОПУСК = 0.6
КНОПКИ = ".hact .hbtn"


@pytest.fixture(params=["chromium", "webkit"])
def браузер(request):
    """Chromium всегда; WebKit — когда задан `PW_WEBKIT_EXECUTABLE` (путь к `pw_run.sh`)."""
    with sync_playwright() as p:
        if request.param == "webkit":
            путь = os.environ.get("PW_WEBKIT_EXECUTABLE")
            if not путь:
                pytest.skip("WebKit не проверен: не задан PW_WEBKIT_EXECUTABLE")
            b = p.webkit.launch(executable_path=путь, headless=True)
        else:
            b = p.chromium.launch(
                executable_path=chromium_executable(p.chromium.executable_path), headless=True
            )
        yield b
        b.close()


def _открыть(браузер, html: str, размер: tuple[int, int]):
    стили = re.findall(r'<link[^>]+href="/static/([^"?]+\.css)[^"]*"', html)
    html = re.sub(r"<script\b[^>]*src=[^>]*>\s*</script>", "", html)
    html = re.sub(r"<link[^>]+stylesheet[^>]*>", "", html)
    page = браузер.new_page(viewport={"width": размер[0], "height": размер[1]})
    page.route("**/*", lambda route: route.abort())
    page.set_content(html, wait_until="domcontentloaded")
    for css in стили:
        page.add_style_tag(path=str(STATIC / css))
    page.add_script_tag(path=str(STATIC / "hact.js"))
    return page


def _координаты(page) -> list[float]:
    """x, y, ширина, высота каждой кнопки ряда — плоским списком (для `approx`)."""
    рамки = page.evaluate(
        """(sel) => [...document.querySelectorAll(sel)].map(el => {
          const r = el.getBoundingClientRect();
          return [Math.round(r.x * 10) / 10, Math.round(r.y * 10) / 10,
                  Math.round(r.width * 10) / 10, Math.round(r.height * 10) / 10];
        })""",
        КНОПКИ,
    )
    return [v for рамка in рамки for v in рамка]


def _ниже_ряда(page) -> float:
    return page.evaluate(
        "() => document.querySelector('[data-violations]').getBoundingClientRect().y"
    )


def _снимок(page, имя: str) -> None:
    каталог = os.environ.get("CARD_STATES_DIR")
    if каталог:
        Path(каталог).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(каталог) / f"{имя}.png"))


@админ
@pytest.mark.parametrize("экран", list(ЭКРАНЫ))
@pytest.mark.parametrize("поверхность", list(ПОВЕРХНОСТИ))
def test_кнопки_ряда_на_месте_при_любом_раскрытии(
    стенд, monkeypatch, браузер, поверхность: str, экран: str
) -> None:
    _приёмка(monkeypatch)
    _лист(monkeypatch)
    html = стенд.get(ПОВЕРХНОСТИ[поверхность]).get_data(as_text=True)
    page = _открыть(браузер, html, ЭКРАНЫ[экран])
    метка = f"{браузер.browser_type.name}-{поверхность}-{экран}"

    # Панель выезжает анимацией: снимаем «закрыто», когда координаты перестали меняться.
    закрыто = _координаты(page)
    for _ in range(40):
        page.wait_for_timeout(100)
        следующие = _координаты(page)
        if следующие == закрыто:
            break
        закрыто = следующие
    содержимое_закрыто = _ниже_ряда(page)
    assert len(закрыто) >= 12, "ряд не отрисован"
    _снимок(page, f"{метка}-1-закрыто")

    for номер, id_ in enumerate(("move", "retract"), start=2):
        if not page.locator(f"#{id_}").count():
            continue  # в панели «Исправить» нет (D465)
        page.click(f"#{id_} > summary")
        # `toggle` приходит позже щелчка: ждём, пока в слоте останется ровно открытое окно.
        page.wait_for_function(
            "(id) => document.querySelectorAll('.hact__slot .hact__pop').length === 1"
            " && document.querySelector('#' + id).open",
            arg=id_,
        )
        _снимок(page, f"{метка}-{номер}-{id_}")
        assert _координаты(page) == pytest.approx(закрыто, abs=ДОПУСК), (
            f"{метка}: {id_} сдвинул ряд"
        )
        окно = page.locator(f"#{id_}").evaluate("el => el.open")
        assert окно
        pop = page.locator(".hact__slot .hact__pop")
        assert pop.count() == 1, "окно не переехало в слот под рядом"
        низ_ряда = max(закрыто[i + 1] + закрыто[i + 3] for i in range(0, len(закрыто), 4))
        рамка = pop.bounding_box()
        assert рамка and рамка["y"] >= низ_ряда - ДОПУСК, "окно не под рядом"
        assert _ниже_ряда(page) > содержимое_закрыто, "содержимое не сдвинулось ниже окна"

    page.click("#retract > summary")  # закрыть: окно вернулось, место освободилось
    page.wait_for_function("() => !document.querySelector('.hact__slot .hact__pop')")
    assert page.locator(".hact__slot .hact__pop").count() == 0
    assert _координаты(page) == pytest.approx(закрыто, abs=ДОПУСК)
    assert _ниже_ряда(page) == pytest.approx(содержимое_закрыто, abs=ДОПУСК)
    page.close()


@админ
@pytest.mark.parametrize("поверхность", list(ПОВЕРХНОСТИ))
def test_на_телефоне_кнопки_обычного_размера_пиктограммы_ниже(
    стенд, monkeypatch, браузер, поверхность: str
) -> None:
    """390px: кнопки прежнего размера (как на main) — не растянуты
    ни по высоте, ни по ширине (D750); подписи целиком; пиктограммы строкой ниже."""
    _приёмка(monkeypatch)
    _лист(monkeypatch)
    html = стенд.get(ПОВЕРХНОСТИ[поверхность]).get_data(as_text=True)
    page = _открыть(браузер, html, ЭКРАНЫ["390"])
    page.wait_for_timeout(1500)  # панель выезжает анимацией

    рамки = page.evaluate(
        """() => {
          const box = (el) => { const r = el.getBoundingClientRect();
            const cut = el.scrollWidth > el.clientWidth + 1;
            return {x: r.x, y: r.y, w: r.width, h: r.height, cut}; };
          const g = document.querySelector('.hact__group--decide');
          return {
            decide: [...g.querySelectorAll('.hbtn')].map(box),
            group: box(g),
            aux: [...document.querySelectorAll('.hact__group--aux .hbtn:not(.hbtn--pdf)')].map(box),
            pdf: [...document.querySelectorAll('.hbtn--pdf')].map(box),
          };
        }"""
    )
    решения = рамки["decide"]
    прежняя = 34 if поверхность == "страница" else 36
    for кнопка in решения:
        # Как на main: в шапке полной страницы кнопки 34px (.head-line), в панели — 36px (.hbtn).
        assert кнопка["h"] == pytest.approx(прежняя, abs=0.6), f"высота кнопки изменена: {кнопка}"
        assert not кнопка["cut"], кнопка
        assert кнопка["w"] < рамки["group"]["w"] - 40, f"кнопка растянута по ширине: {кнопка}"
    if поверхность == "страница":
        assert len(решения) == 3  # Принять, Исправить, Отклонить
    else:
        assert len(решения) == 2  # Принять, Отклонить (правки даты и пиццерии в панели нет)
    assert len({round(к["y"]) for к in решения}) == 1, "решения не одной строкой"
    assert len(рамки["aux"]) >= 1
    низ_решений = max(к["y"] + к["h"] for к in решения)
    for значок in рамки["aux"]:
        assert значок["w"] == pytest.approx(прежняя, abs=0.6) and значок["h"] == pytest.approx(
            прежняя, abs=0.6
        ), f"размер пиктограммы изменён: {значок}"
        assert значок["y"] >= низ_решений, "пиктограммы не строкой ниже"
    assert len({round(з["y"]) for з in рамки["aux"]}) == 1, "пиктограммы в одну строку"
    assert len(рамки["pdf"]) == 1 and not рамки["pdf"][0]["cut"], "подпись «PDF» обрезана или нет"
    page.close()
