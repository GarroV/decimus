"""«Проверки» в настоящем браузере: на телефоне «На приёмке» выше «Отбора», «Отбор» свёрнут.

Chromium и WebKit (WebKit — по `PW_WEBKIT_EXECUTABLE`, без него пропуск вслух). Страницы
отдаёт Flask-клиент, статику — диск, остальное блокируется. Замер — `getBoundingClientRect`:
на 390 px блок приёмки стоит над блоком отбора, поля отбора скрыты до щелчка по «Отбор»; на
1440 px раскладка прежняя — колонка слева, строки-заголовка «Отбор» нет, поля раскрыты.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from conftest import chromium_executable
from test_web_app import ТЕНАНТ
from test_web_registry_counts import ГЕО, ЖДУТ, ПРИНЯТЫЕ
from web_harness import войти, подменить_двери, собрать

from src.web import inspections as data

playwright = pytest.importorskip("playwright.sync_api")
STATIC = Path(__file__).resolve().parents[1] / "src/web/static"
ХОСТ = "http://decimus.test"
АДРЕС = "/inspections?lang=ru&grade=A"


@pytest.fixture
def стенд(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    подменить_двери(monkeypatch, tenant=ТЕНАНТ)
    monkeypatch.setattr(
        data, "load_registry", lambda **_: data.Registry(ПРИНЯТЫЕ, True, review=ЖДУТ)
    )
    monkeypatch.setattr(data, "load_geography", lambda **_: ГЕО)
    client = собрать(tenant=ТЕНАНТ).test_client()
    assert войти(client).status_code == 302
    return client


@pytest.fixture(params=["chromium", "webkit"])
def page(request, стенд) -> Iterator:  # type: ignore[no-untyped-def]
    with playwright.sync_playwright() as pw:
        if request.param == "chromium":
            browser = pw.chromium.launch(
                executable_path=chromium_executable(pw.chromium.executable_path), headless=True
            )
        else:
            webkit = os.environ.get("PW_WEBKIT_EXECUTABLE")
            if not webkit:
                pytest.skip("нет PW_WEBKIT_EXECUTABLE — WebKit не прогнан")
            browser = pw.webkit.launch(executable_path=os.path.expanduser(webkit), headless=True)
        страница = browser.new_page()

        def отдать(route) -> None:  # type: ignore[no-untyped-def]
            адрес = urlsplit(route.request.url)
            if not route.request.url.startswith(ХОСТ):
                route.abort()
            elif адрес.path.startswith("/static/"):
                route.fulfill(path=str(STATIC / адрес.path.removeprefix("/static/")))
            else:
                ответ = стенд.get(адрес.path + (f"?{адрес.query}" if адрес.query else ""))
                route.fulfill(
                    status=ответ.status_code,
                    body=ответ.get_data(),
                    content_type="text/html; charset=utf-8",
                )

        страница.route("**/*", отдать)
        yield страница
        browser.close()


_ЗАМЕР = """() => {
  const box = (sel) => { const n = document.querySelector(sel); if (!n) return null;
    const r = n.getBoundingClientRect();
    return {top: r.top, left: r.left, right: r.right, h: r.height}; };
  const vis = (sel) => { const n = document.querySelector(sel); if (!n) return false;
    const r = n.getBoundingClientRect(); const s = getComputedStyle(n);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden'; };
  return {
    review: box('.slist--review'), accepted: box('.slist--registry:not(.slist--review)'),
    filters: box('.rg-filters'), open: document.querySelector('.rg-fold').open,
    sum: vis('.rg-fold__sum'), body: vis('.rg-fold__body'), search: vis('.rg-search'),
    sumText: document.querySelector('.rg-fold__sum').textContent.trim(),
  };
}"""


def test_телефон_приёмка_выше_отбора_и_отбор_свёрнут(page) -> None:  # type: ignore[no-untyped-def]
    # Arrange
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(ХОСТ + АДРЕС)

    # Act
    замер = page.evaluate(_ЗАМЕР)

    # Assert — порядок блоков и свёрнутость
    assert замер["review"]["top"] < замер["filters"]["top"] < замер["accepted"]["top"]
    assert замер["open"] is False
    assert замер["sum"] is True
    assert замер["filters"]["h"] < 80  # только строка «Отбор»: поля скрыты
    assert замер["sumText"] == "Отбор · 1"

    # Act — щелчок по «Отбор» раскрывает поля
    page.click(".rg-fold__sum")
    раскрыто = page.evaluate(_ЗАМЕР)

    # Assert
    assert раскрыто["open"] is True
    assert раскрыто["filters"]["h"] > 200
    assert раскрыто["search"] is True


def test_десктоп_колонка_слева_отбор_раскрыт_без_строки_заголовка(page) -> None:  # type: ignore[no-untyped-def]
    # Arrange
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(ХОСТ + АДРЕС)

    # Act
    замер = page.evaluate(_ЗАМЕР)

    # Assert — раскладка как была: колонка слева, списки справа друг под другом
    assert замер["filters"]["right"] <= замер["review"]["left"]
    assert замер["review"]["top"] < замер["accepted"]["top"]
    assert замер["sum"] is False
    assert замер["filters"]["h"] > 200  # поля раскрыты, хотя `<details>` не открыт
    assert замер["search"] is True


def test_у_строки_реестра_виден_фокус_с_клавиатуры(page) -> None:  # type: ignore[no-untyped-def]
    # Arrange
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(ХОСТ + АДРЕС)

    # Act — Tab до первой строки списка (фокус с клавиатуры, а не мышью)
    for _ in range(60):
        page.keyboard.press("Tab")
        if page.evaluate("document.activeElement.classList.contains('srow')"):
            break
    стиль = page.evaluate(
        "(() => { const s = getComputedStyle(document.activeElement);"
        " return [s.outlineStyle, s.outlineWidth, s.outlineOffset]; })()"
    )

    # Assert — то же кольцо, что у ссылок меню: 2px сплошное, внутрь строки
    assert page.evaluate("document.activeElement.classList.contains('srow')")
    assert стиль == ["solid", "2px", "-2px"]
