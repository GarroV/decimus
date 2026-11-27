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
from web_harness import СВОЙ, ТОКЕН, Учётка, войти, подменить_двери, собрать

from src.db import web_own_profile
from src.web import auth

playwright = pytest.importorskip("playwright.sync_api")
STATIC = Path(__file__).resolve().parents[1] / "src/web/static"
ХОСТ = "http://decimus.test"


@pytest.fixture
def page_factory(monkeypatch: pytest.MonkeyPatch) -> Iterator:
    подготовить(monkeypatch)
    подменить_двери(monkeypatch, tenant="HQ", role="admin")
    клиент = собрать(tenant="HQ", ui_lang="ru").test_client()
    профиль = {"lang": "ru"}
    возвраты = []

    def сохранить(token: str, lang: str) -> bool:
        assert token == ТОКЕН
        профиль["lang"] = lang
        return True

    monkeypatch.setattr(web_own_profile, "set_web_lang", сохранить)
    monkeypatch.setattr(
        auth,
        "resolve_session",
        lambda token: (
            Учётка(tenant="HQ", role="admin", web_lang=профиль["lang"]) if token == ТОКЕН else None
        ),
    )
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
                ответ = клиент.open(
                    путь,
                    method=route.request.method,
                    data=route.request.post_data,
                    headers={"Origin": СВОЙ},
                    content_type=route.request.headers.get("content-type"),
                )
                if route.request.method == "POST":
                    # Chromium's mocked redirect chain bypasses request routing.
                    # Verify Flask's actual redirect, then open its target explicitly.
                    assert ответ.status_code == 302
                    возвраты.append(ответ.headers["Location"])
                    route.fulfill(status=200, body="", content_type="text/html")
                    return
                route.fulfill(
                    status=ответ.status_code,
                    body=ответ.get_data(),
                    headers={"Location": ответ.headers["Location"]}
                    if "Location" in ответ.headers
                    else {},
                    content_type="text/html; charset=utf-8",
                )

        страница.route("**/*", отдать)
        yield страница, клиент, возвраты
        browser.close()


def test_до_входа_выбор_кода_уходит_get_с_прежними_параметрами(page_factory) -> None:  # type: ignore[no-untyped-def]
    страница, _, _ = page_factory
    страница.goto(f"{ХОСТ}/login?next=%2Foverview&login_hint=person&scope=a&scope=b&lang=ru")
    список = страница.locator("select[data-lang-submit]")

    коды = список.locator("option").all_inner_texts()
    assert коды[:2] == ["RU", "EN"], коды
    with страница.expect_request(lambda r: "lang=en" in r.url) as запрос:
        список.select_option("en")
    параметры = parse_qs(urlsplit(запрос.value.url).query)
    assert параметры == {
        "next": ["/overview"],
        "login_hint": ["person"],
        "scope": ["a", "b"],
        "lang": ["en"],
    }


def test_вошедший_сохраняет_язык_post_ом_в_профиль(page_factory) -> None:  # type: ignore[no-untyped-def]
    страница, клиент, возвраты = page_factory
    assert войти(клиент).status_code == 302
    страница.goto(f"{ХОСТ}/settings?tile=language&lang=ru")
    список = страница.locator(".shell__main select[data-lang-submit]")

    with страница.expect_request(lambda r: r.method == "POST") as запрос:
        список.select_option("en")
    assert urlsplit(запрос.value.url).path.endswith("/settings/lang")
    assert "lang=en" in (запрос.value.post_data or "")
    страница.wait_for_url("**/settings/lang")
    assert возвраты == ["/settings?tile=language"]
    страница.goto(ХОСТ + возвраты[-1])
    assert страница.locator("html").get_attribute("lang") == "en"
    assert страница.locator(".shell__main select[data-lang-submit]").input_value() == "en"


def test_переход_обновляет_адрес_возврата_и_сохраняет_отбор(page_factory) -> None:  # type: ignore[no-untyped-def]
    страница, клиент, возвраты = page_factory
    страница.set_viewport_size({"width": 1280, "height": 900})
    assert войти(клиент).status_code == 302
    страница.goto(f"{ХОСТ}/settings?lang=ru")
    страница.evaluate("window.languageNavigationMarker = true")
    страница.evaluate("window.decimusNavigate('/ratings/rs?country=RS&country=GE&lang=ru')")
    страница.wait_for_url("**/ratings/rs?country=RS&country=GE&lang=ru")
    assert страница.evaluate("window.languageNavigationMarker") is True
    форма = страница.locator(".sidenav__prefs form.langsel")
    assert форма.locator('input[name="next"]').input_value() == "/ratings/rs?country=RS&country=GE"
    форма.locator("select").select_option("en")
    страница.wait_for_url("**/settings/lang")
    assert возвраты == ["/ratings/rs?country=RS&country=GE"]
    страница.goto(ХОСТ + возвраты[-1])
    assert страница.locator("html").get_attribute("lang") == "en"
