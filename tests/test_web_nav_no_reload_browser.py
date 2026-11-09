"""Переход между разделами левой панели не перезагружает страницу (владелец 09.11.2026:
«страница прыгает при переключении»). Раньше любой экран со скриптом в `<head>` (реестр,
«Качество», «Настройки», «Обучение»…) открывался полной перезагрузкой; теперь скрипты помечены
`data-swap-safe`, подключаются заново на `decimus:navigation`, а переход остаётся подменой.

Настоящий Chromium. Экраны, которым нужна база (проверки, календарь, ОСБ, страны, действия,
обзор), без базы отдают 503, поэтому для них ответ собирается из настоящей страницы: тот же
`<head>` и оболочка, но `<main>` — минимальная разметка экрана, а скрипты — те, что стоят в
шаблонах. Что шаблон помечает скрипт, проверяет `test_скрипты_в_head_помечены_swap_safe`.

Метка на окне пропадает, если страница перезагружена целиком, — по ней видно перезагрузку.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
from conftest import chromium_executable
from ratings_page import подготовить
from web_harness import войти, подменить_двери, собрать

playwright = pytest.importorskip("playwright.sync_api")
ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src/web/static"
TEMPLATES = ROOT / "src/web/templates"
ХОСТ = "http://decimus.test"
ОСНОВА = "/settings"

#: Страницы, которые отдаёт настоящее приложение без базы.
НАСТОЯЩИЕ = ("/settings", "/administration", "/training", "/quality")


def _скрипты(*имена: str) -> str:
    return "".join(f'<script src="/static/{n}" data-swap-safe defer></script>' for n in имена)


#: Экраны с базой: скрипты `<head>` по шаблону и разметка, на которой они что-то делают.
ЗАГЛУШКИ: dict[str, tuple[str, str]] = {
    "/inspections": (
        _скрипты("split.js", "proofread.js", "letter.js"),
        '<div class="split"><section class="split__list">'
        '<a class="srow" href="/inspections?id=1">Проверка 1</a></section></div>'
        '<form><div data-letter-editor data-field="lt" hidden></div>'
        "<div data-letter-tools hidden><div data-link-box hidden></div>"
        "<input data-link-input><span data-link-note></span></div>"
        '<textarea id="lt"></textarea><div data-letter-plain>Простой текст</div></form>',
    ),
    "/calendar": (
        _скрипты("split.js"),
        '<div class="split"><section class="split__list">'
        '<a class="srow" href="/calendar?id=1">Запись 1</a></section></div>',
    ),
    "/osb": (
        _скрипты("split.js", "actions.js"),
        '<div class="split"><section class="split__list">'
        '<a class="srow" href="/osb?id=1">Запись 1</a></section></div>'
        '<a href="#row" data-row-open>Правка</a>'
        '<div id="row" data-row-panel><button data-row-close>x</button></div>',
    ),
    "/country": (
        _скрипты("split.js", "country.js"),
        '<div class="pk-shell"><aside class="pk-rail">'
        '<a class="pk-item" href="/country?c=1">Страна 1</a></aside>'
        '<section class="pk-work">Рабочая область</section></div>',
    ),
    "/actions": (
        _скрипты("split.js", "actions.js"),
        '<div class="pk-shell"><aside class="pk-rail"></aside><section class="pk-work">'
        '<a href="#row" data-row-open>Правка</a>'
        '<div id="row" data-row-panel><button data-row-close>x</button></div></section></div>',
    ),
    "/overview": (
        _скрипты("home.js"),
        '<div data-rb-scroll><div data-rb-view style="overflow:auto;width:50px">'
        '<div style="width:500px">x</div></div><button data-rb-step="1" hidden>&gt;</button></div>',
    ),
}
#: Содержимое панелей, которые открывают строки заглушек.
ПАНЕЛИ = {
    "/inspections?id=1": "Проверка 1",
    "/calendar?id=1": "Запись 1",
    "/osb?id=1": "Запись 1",
}


def _заглушка(основа: str, путь: str, панель: str | None = None) -> str:
    """Настоящая оболочка и `<head>`, но с `<main>` и скриптами экрана из `ЗАГЛУШКИ`."""
    скрипты, разметка = ЗАГЛУШКИ[путь]
    # Адрес скрипта — как у настоящих страниц, с версией: иначе `nav.js` счёл бы его новым.
    for адрес in re.findall(r'src="(/static/[\w.-]+\?v=\w+)"', основа):
        скрипты = скрипты.replace(адрес.split("?")[0] + '"', адрес + '"')
    html = re.sub(
        r'<script src="[^"]*/(?:split|settings|country)\.js[^"]*"[^>]*></script>', "", основа
    )
    html = html.replace("</head>", скрипты + "</head>", 1)
    шапка_панели = (
        f'<aside data-drawer style="position:static;pointer-events:none"><h2>{панель}</h2></aside>'
        if панель
        else ""
    )
    return re.sub(
        r'(<main class="page[^"]*shell__main">).*?(</main>)',
        lambda m: m.group(1) + разметка + m.group(2) + шапка_панели,
        html,
        count=1,
        flags=re.S,
    )


@pytest.fixture
def page(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    подготовить(monkeypatch)
    подменить_двери(monkeypatch, tenant="HQ", role="admin")
    клиент = собрать(tenant="HQ", ui_lang="ru").test_client()
    assert войти(клиент).status_code == 302
    основа = клиент.get(f"{ОСНОВА}?lang=ru").get_data(as_text=True)
    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=chromium_executable(pw.chromium.executable_path), headless=True
        )
        страница = browser.new_page()
        страница.set_viewport_size({"width": 1440, "height": 900})
        ошибки: list[str] = []
        страница.on("pageerror", lambda error: ошибки.append(str(error)))

        def отдать(route) -> None:  # type: ignore[no-untyped-def]
            адрес = urlsplit(route.request.url)
            запрос = адрес.path + (f"?{адрес.query}" if адрес.query else "")
            без_языка = запрос.replace("lang=ru", "").rstrip("?&")
            if not route.request.url.startswith(ХОСТ):
                route.abort()
            elif адрес.path.startswith("/static/"):
                route.fulfill(path=str(STATIC / адрес.path.removeprefix("/static/")))
            elif без_языка in ПАНЕЛИ:
                route.fulfill(
                    body=_заглушка(основа, адрес.path, ПАНЕЛИ[без_языка]),
                    content_type="text/html; charset=utf-8",
                )
            elif адрес.path in ЗАГЛУШКИ:
                route.fulfill(
                    body=_заглушка(основа, адрес.path), content_type="text/html; charset=utf-8"
                )
            else:
                ответ = клиент.get(запрос)
                route.fulfill(
                    status=ответ.status_code,
                    body=ответ.get_data(),
                    content_type="text/html; charset=utf-8",
                )

        страница.route("**/*", отдать)
        yield страница
        browser.close()
        assert not ошибки, ошибки


def _тот_же_документ(страница: Any) -> bool:
    return bool(страница.evaluate("window.__same_document === 1"))


def _перейти(страница: Any, путь: str) -> None:
    """Щелчок по пункту левой панели; страница не должна перезагрузиться."""
    страница.locator(f".sidenav a[href^='{путь}?']").first.click()
    страница.wait_for_function("p => document.documentElement.dataset.navPath === p", arg=путь)
    assert _тот_же_документ(страница), f"{путь}: страница перезагружена целиком"
    assert urlsplit(страница.url).path == путь


def test_все_разделы_левой_панели_открываются_подменой(page: Any) -> None:
    page.goto(f"{ХОСТ}{ОСНОВА}?lang=ru")
    page.evaluate("window.__same_document = 1")

    for путь in (
        "/inspections",
        "/calendar",
        "/osb",
        "/country",
        "/training",
        "/quality",
        "/actions",
        "/overview",
        "/administration",
        "/settings",
        "/inspections",
    ):
        _перейти(page, путь)

    # Скрипты экранов, которые были поданы подменой, работают так же, как после загрузки.
    assert page.evaluate(
        "typeof window.LetterEditor === 'object' && typeof window.Proofread === 'object'"
    )


def test_скрипты_экранов_работают_после_прихода_подменой(page: Any) -> None:
    # Буфер обмена есть только в защищённом контексте: подставляется, как на настоящем адресе.
    page.add_init_script(
        "Object.defineProperty(navigator,'clipboard',{value:{writeText:()=>Promise.resolve()}})"
    )
    page.goto(f"{ХОСТ}{ОСНОВА}?lang=ru")
    page.evaluate("window.__same_document = 1")

    # Реестр: строка открывает панель фоном, без перезагрузки (`split.js`).
    _перейти(page, "/calendar")
    page.click(".split__list a.srow")
    page.wait_for_selector("[data-drawer]")
    assert _тот_же_документ(page)
    assert page.url.endswith("/calendar?id=1")

    # Реестр проверок: редактор письма включился на подменённой разметке (`letter.js`).
    _перейти(page, "/inspections")
    page.wait_for_function("document.querySelector('[data-letter-editor]').dataset.ready === '1'")
    assert page.evaluate("document.querySelector('[data-letter-plain]').hidden")

    # «Действия» и ОСБ: панель правки строки открывается без якоря (`actions.js`).
    _перейти(page, "/osb")
    page.click("[data-row-open]")
    assert page.evaluate("document.querySelector('[data-row-panel]').classList.contains('is-open')")
    assert page.evaluate("!location.hash")

    # «Страны»: скрипт отметил запись истории и работает при шагах «назад» (`country.js`).
    _перейти(page, "/country")
    assert page.evaluate("history.state && history.state.pick === true")

    # «Обзор»: стрелки слайдера показаны (`home.js`).
    _перейти(page, "/overview")
    assert page.evaluate("document.querySelector('[data-rb-scroll]').dataset.rbReady === ''")

    # «Настройки»: блок «Инструкции» получил обработчик (`settings.js`).
    _перейти(page, "/settings")
    assert page.evaluate(
        "[...document.querySelectorAll('details[data-copy-on-open]')]"
        ".every(d => d.hasAttribute('data-copy-ready'))"
    )

    # «Администрирование» открывается подменой, как и остальные (`split.js` в `<head>`).
    _перейти(page, "/administration")


def test_назад_и_вперёд_между_разделами_без_перезагрузки(page: Any) -> None:
    page.goto(f"{ХОСТ}{ОСНОВА}?lang=ru")
    page.evaluate("window.__same_document = 1")
    for путь in ("/inspections", "/country", "/training"):
        _перейти(page, путь)

    for ожидаемый in ("/country", "/inspections", "/settings"):
        page.go_back()
        page.wait_for_function("p => document.documentElement.dataset.navPath === p", arg=ожидаемый)
        assert _тот_же_документ(page), ожидаемый
        assert urlsplit(page.url).path == ожидаемый
    page.go_forward()
    page.wait_for_function(
        "p => document.documentElement.dataset.navPath === p", arg="/inspections"
    )
    assert _тот_же_документ(page)


def test_шаг_назад_из_панели_реестра_к_другому_разделу_не_перезагружает(page: Any) -> None:
    page.goto(f"{ХОСТ}{ОСНОВА}?lang=ru")
    page.evaluate("window.__same_document = 1")
    _перейти(page, "/calendar")
    page.click(".split__list a.srow")
    page.wait_for_selector("[data-drawer]")
    page.go_back()
    page.wait_for_function("() => !document.querySelector('[data-drawer]')")
    assert _тот_же_документ(page)
    page.go_back()
    page.wait_for_function("p => document.documentElement.dataset.navPath === p", arg="/settings")
    assert _тот_же_документ(page)
    page.go_forward()
    page.wait_for_function("p => document.documentElement.dataset.navPath === p", arg="/calendar")
    page.go_forward()
    page.wait_for_selector("[data-drawer]")
    assert _тот_же_документ(page)


#: Скрипты, которые не из экранов за левой панелью и остаются обычными: вход, мини-приложение,
#: лендинг, документы рассылок, passkey и подключение Dodo IS (отдельные страницы настроек).
ОСТАЮТСЯ_ПЕРЕЗАГРУЗКОЙ = (
    "login_second_step.html",
    "walk.html",
    "landing.html",
    "mailings/document.html",
    "settings/security.html",
    "dodois/connect.html",
    "base.html",
    "methodology/index.html",
    "inspections/letter.html",
)


def test_скрипты_в_head_помечены_swap_safe() -> None:
    """Каждый `<script src>` шаблона экрана — `data-swap-safe` или в списке исключений."""
    непомеченные = []
    for файл in TEMPLATES.rglob("*.html"):
        имя = str(файл.relative_to(TEMPLATES))
        if имя in ОСТАЮТСЯ_ПЕРЕЗАГРУЗКОЙ:
            continue
        for тег in re.findall(r"<script\b[^>]*\bsrc=[^>]*>", файл.read_text(encoding="utf-8")):
            if "data-swap-safe" not in тег and "data-shell" not in тег:
                непомеченные.append((имя, тег))
    assert not непомеченные, непомеченные
