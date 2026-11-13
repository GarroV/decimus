"""Язык интерфейса — выпадающий список кодов (D743, #1619): выбор сам отправляет форму.

Настоящий Chromium без сервера: страницы отдаёт Flask-клиент, статику — диск (как в
`test_web_nav_stable_browser.py`). Вошедший сохраняет язык POST-ом в профиль, до входа —
GET с прежними параметрами адреса.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from conftest import chromium_executable
from ratings_page import подготовить
from web_harness import войти, подменить_двери, собрать

playwright = pytest.importorskip("playwright.sync_api")
STATIC = Path(__file__).resolve().parents[1] / "src/web/static"
ХОСТ = "http://decimus.test"


@pytest.fixture
def page_factory(monkeypatch: pytest.MonkeyPatch) -> Iterator:
    подготовить(monkeypatch)
    подменить_двери(monkeypatch, tenant="HQ", role="admin")
    клиент = собрать(tenant="HQ", ui_lang="ru").test_client()
    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=chromium_executable(pw.chromium.executable_path), headless=True
        )
        страница = browser.new_page(viewport={"width": 390, "height": 800})

        def отдать(route) -> None:  # type: ignore[no-untyped-def]
            адрес = urlsplit(route.request.url)
            if not route.request.url.startswith(ХОСТ):
                route.abort()
            elif адрес.path.startswith("/static/"):
                route.fulfill(path=str(STATIC / адрес.path.removeprefix("/static/")))
            else:
                путь = адрес.path + (f"?{адрес.query}" if адрес.query else "")
                ответ = клиент.get(путь)
                route.fulfill(
                    status=ответ.status_code,
                    body=ответ.get_data(),
                    content_type="text/html; charset=utf-8",
                )

        страница.route("**/*", отдать)
        yield страница, клиент
        browser.close()


def test_до_входа_выбор_кода_уходит_get_с_прежними_параметрами(page_factory) -> None:  # type: ignore[no-untyped-def]
    страница, _ = page_factory
    страница.goto(f"{ХОСТ}/login?next=%2Foverview&lang=ru")
    список = страница.locator("select[data-lang-submit]")

    коды = список.locator("option").all_inner_texts()
    assert коды[:2] == ["RU", "EN"], коды
    with страница.expect_request(lambda r: "lang=en" in r.url) as запрос:
        список.select_option("en")
    параметры = parse_qs(urlsplit(запрос.value.url).query)
    assert параметры == {"next": ["/overview"], "lang": ["en"]}


def test_вошедший_сохраняет_язык_post_ом_в_профиль(page_factory) -> None:  # type: ignore[no-untyped-def]
    страница, клиент = page_factory
    assert войти(клиент).status_code == 302
    страница.goto(f"{ХОСТ}/settings?tile=language&lang=ru")
    список = страница.locator(".shell__main select[data-lang-submit]")

    with страница.expect_request(lambda r: r.method == "POST") as запрос:
        список.select_option("en")
    assert urlsplit(запрос.value.url).path.endswith("/settings/lang")
    assert "lang=en" in (запрос.value.post_data or "")
