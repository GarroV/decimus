"""Левая панель не двигает страницу (владелец 09.11.2026): ширина панели и левый край
содержимого одни и те же на всех экранах, при раскрытом и закрытом «Рейтинги», в узкой панели
и с полосой прокрутки страницы.

Настоящий Chromium, без сервера и сети: страницы отдаёт Flask-клиент, статику — диск. Полосы
прокрутки включены (в безголовом режиме их по умолчанию прячут, и скачок ширины на них не
виден). WALK_CHROME_BIN — Chrome for Testing вне Playwright.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from conftest import chromium_executable
from ratings_page import подготовить
from web_harness import войти, подменить_двери, собрать

playwright = pytest.importorskip("playwright.sync_api")
STATIC = Path(__file__).resolve().parents[1] / "src/web/static"
ХОСТ = "http://decimus.test"
#: Экраны с разной раскладкой: «Рейтинги» (свой css и скрипт), обычные и справочные.
ЭКРАНЫ = (
    "/settings",
    "/administration",
    "/training",
    "/quality",
    "/ratings/rs",
    "/ratings/maps",
    "/ratings/inspections",
)
ЗАМЕР = """()=>{const r=s=>document.querySelector(s).getBoundingClientRect();
  return {nav: Math.round(r('.shell__nav').width), left: Math.round(r('.shell__main').left),
          main: Math.round(r('.shell__main').width)}}"""
ВЫСОКАЯ = ".shell__main{min-height:2600px !important}"


@pytest.fixture
def page(monkeypatch: pytest.MonkeyPatch) -> Iterator:
    подготовить(monkeypatch)
    подменить_двери(monkeypatch, tenant="HQ", role="admin")
    клиент = собрать(tenant="HQ", ui_lang="ru").test_client()
    assert войти(клиент).status_code == 302
    with playwright.sync_playwright() as pw:
        executable = chromium_executable(pw.chromium.executable_path)
        browser = pw.chromium.launch(
            executable_path=executable, headless=True, ignore_default_args=["--hide-scrollbars"]
        )
        страница = browser.new_page()
        ошибки: list[str] = []
        страница.on("pageerror", lambda error: ошибки.append(str(error)))

        def отдать(route) -> None:  # type: ignore[no-untyped-def]
            адрес = urlsplit(route.request.url)
            if not route.request.url.startswith(ХОСТ):
                route.abort()
            elif адрес.path.startswith("/static/"):
                route.fulfill(path=str(STATIC / адрес.path.removeprefix("/static/")))
            else:
                ответ = клиент.get(адрес.path + (f"?{адрес.query}" if адрес.query else ""))
                route.fulfill(
                    status=ответ.status_code,
                    body=ответ.get_data(),
                    content_type="text/html; charset=utf-8",
                )

        страница.route("**/*", отдать)
        yield страница
        browser.close()
        assert not ошибки, ошибки


def _выбор(страница, **ключи: str) -> None:  # type: ignore[no-untyped-def]
    """Что человек выбрал раньше: ширина панели и раскрытие «Рейтингов» (localStorage)."""
    имена = {"collapsed": "decimus-nav-collapsed", "ratings": "decimus-nav-ratings-open"}
    команды = "".join(f"localStorage.setItem('{имена[k]}','{v}');" for k, v in ключи.items())
    if команды:
        страница.add_init_script(f"try{{{команды}}}catch(e){{}}")


def _открыть(страница, путь: str) -> dict[str, int]:  # type: ignore[no-untyped-def]
    страница.goto(f"{ХОСТ}{путь}?lang=ru")
    return страница.evaluate(ЗАМЕР)


@pytest.mark.parametrize("ширина", [1440, 1280, 1101])
@pytest.mark.parametrize("раскрыты", ["true", "false"])
def test_панель_и_край_содержимого_одни_на_всех_экранах(page, ширина: int, раскрыты: str) -> None:
    page.set_viewport_size({"width": ширина, "height": 900})
    _выбор(page, collapsed="false", ratings=раскрыты)

    замеры = {путь: _открыть(page, путь) for путь in ЭКРАНЫ}

    assert {(m["nav"], m["left"]) for m in замеры.values()} == {(216, 216)}, замеры


@pytest.mark.parametrize("ширина", [1440, 1099])
def test_узкая_панель_остаётся_узкой_на_всех_экранах(page, ширина: int) -> None:
    page.set_viewport_size({"width": ширина, "height": 900})
    _выбор(page, collapsed="true")

    замеры = {путь: _открыть(page, путь) for путь in ЭКРАНЫ}

    assert {(m["nav"], m["left"]) for m in замеры.values()} == {(56, 56)}, замеры


def test_раскрытие_рейтингов_в_полной_панели_ничего_не_двигает(page) -> None:  # type: ignore[no-untyped-def]
    page.set_viewport_size({"width": 1440, "height": 900})
    _выбор(page, collapsed="false", ratings="false")
    до = _открыть(page, "/settings")

    page.click("[data-nav-ratings-toggle]")
    page.wait_for_timeout(400)

    assert page.locator("#ratings-navigation a").first.is_visible()
    assert page.evaluate(ЗАМЕР) == до
    page.click("[data-nav-ratings-toggle]")
    page.wait_for_timeout(400)
    assert page.evaluate(ЗАМЕР) == до


def test_рейтинги_в_узкой_панели_всплывают_и_панель_не_растёт(page) -> None:  # type: ignore[no-untyped-def]
    page.set_viewport_size({"width": 1440, "height": 900})
    _выбор(page, collapsed="true")
    до = _открыть(page, "/settings")
    assert (до["nav"], до["left"]) == (56, 56)
    пункты = page.locator("#ratings-navigation a")
    assert not пункты.first.is_visible()

    page.click("[data-nav-ratings-toggle]")

    assert пункты.first.is_visible()
    всплыл = page.locator("#ratings-navigation").bounding_box()
    assert всплыл and всплыл["x"] >= 56
    assert page.evaluate(ЗАМЕР) == до
    page.keyboard.press("Escape")
    assert not пункты.first.is_visible()
    page.click("[data-nav-ratings-toggle]")
    page.mouse.click(900, 600)
    assert not пункты.first.is_visible()
    assert page.evaluate("localStorage.getItem('decimus-nav-collapsed')") == "true"


@pytest.mark.parametrize("путь", ["/settings", "/ratings/rs"])
def test_ширина_содержимого_не_зависит_от_полосы_прокрутки_страницы(page, путь: str) -> None:
    page.set_viewport_size({"width": 1440, "height": 900})
    _выбор(page, collapsed="false", ratings="false")
    коротких = {путь_: _открыть(page, путь_)["main"] for путь_ in ("/settings", "/ratings/rs")}

    page.goto(f"{ХОСТ}{путь}?lang=ru")
    page.add_style_tag(content=ВЫСОКАЯ)
    высокая = page.evaluate(ЗАМЕР)["main"]

    assert set(коротких.values()) == {высокая}, (коротких, высокая)
