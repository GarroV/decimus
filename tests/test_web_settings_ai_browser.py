"""Плитка «Нейросети» (D695) в настоящем Chromium: вёрстка на 1440 и 390 px, выбор из списка.

Без сервера и сети: страницы отдаёт Flask-клиент, статику — диск, остальное блокируется.
Что проверяется глазами браузера, а не разметкой: страница не шире окна (на телефоне —
главный дефект «растянутого» экрана), список выбора переходит к другой инструкции, адрес и
команды видны целиком. WALK_CHROME_BIN — Chrome for Testing вне Playwright. Снимки для
показа владельцу кладутся в каталог из `AI_TILE_SHOTS`, если он задан.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from oauth_harness import ПамятьOAuth, _Подключение, подменить_oauth
from web_harness import войти, подменить_двери, собрать

from src.web import users_mcp

playwright = pytest.importorskip("playwright.sync_api")
STATIC = Path(__file__).resolve().parents[1] / "src/web/static"
ХОСТ = "http://decimus.test"
MCP = "https://mcp.example/mcp"
РАЗМЕРЫ = ((1440, 900), (390, 844))


@pytest.fixture
def стенд(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    from datetime import UTC, datetime

    память: ПамятьOAuth = подменить_oauth(monkeypatch)
    monkeypatch.setattr(users_mcp, "own_status", lambda _id: users_mcp.TokenStatus(known=True))
    from web_harness import Учётка

    for ключ, имя, возврат in (
        ("a", "Claude", "https://claude.ai/api/mcp/auth_callback"),
        ("b", "ChatGPT", "https://chatgpt.com/connector/oauth/abc"),
        ("c", "codex", "http://localhost:1455/oauth/callback"),
    ):
        клиент = память.register_client(имя, [возврат], address="203.0.113.5")
        память.grants[ключ] = _Подключение(Учётка().id, клиент, datetime.now(UTC))
    подменить_двери(monkeypatch, tenant="HQ", role="admin")
    приложение = собрать(tenant="HQ", admin_public_url="https://admin.example", mcp_public_url=MCP)
    # Без `with`: контекст клиента не сохраняется между запросами, и ответы можно
    # отдавать из обработчиков Playwright (другая сопрограмма).
    client = приложение.test_client()
    assert войти(client).status_code == 302
    return client


@pytest.fixture
def page(стенд) -> Iterator:
    with playwright.sync_playwright() as pw:
        executable = os.environ.get("WALK_CHROME_BIN") or pw.chromium.executable_path
        if not Path(executable).exists():
            pytest.skip("Chromium unavailable; set WALK_CHROME_BIN")
        browser = pw.chromium.launch(executable_path=executable, headless=True)
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
                ответ = стенд.get(адрес.path + (f"?{адрес.query}" if адрес.query else ""))
                route.fulfill(
                    status=ответ.status_code,
                    body=ответ.get_data(),
                    content_type="text/html; charset=utf-8",
                )

        страница.route("**/*", отдать)
        yield страница
        browser.close()
        assert not ошибки, ошибки


def _снимок(страница, имя: str) -> None:  # type: ignore[no-untyped-def]
    каталог = os.environ.get("AI_TILE_SHOTS")
    if каталог:
        страница.screenshot(path=str(Path(каталог) / f"{имя}.png"), full_page=True)


@pytest.mark.parametrize(("ширина", "высота"), РАЗМЕРЫ)
def test_плитка_нейросети_не_шире_окна_и_выбор_работает(page, ширина: int, высота: int) -> None:
    page.set_viewport_size({"width": ширина, "height": высота})
    page.goto(f"{ХОСТ}/settings?tile=claude&ai=chatgpt")

    def без_горизонтальной_прокрутки() -> bool:
        return bool(
            page.evaluate(
                "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
            )
        )

    assert page.locator("select[data-pick-nav]").count() == 1
    assert page.locator("#claude-mcp-url").is_visible()
    assert page.locator("#chatgpt-token").is_visible()
    assert page.get_by_text("Настольный ChatGPT на Mac").is_visible()
    assert page.get_by_text("Обычные чаты и ChatGPT в браузере").is_visible()
    assert без_горизонтальной_прокрутки()
    _снимок(page, f"ai-chatgpt-{ширина}")

    page.select_option("select[data-pick-nav]", label="GLM (Z.ai)")
    page.wait_for_url("**ai=glm**")
    assert page.get_by_text("ZCode от Z.ai").is_visible()
    assert page.locator("#chatgpt-token").count() == 0
    assert без_горизонтальной_прокрутки()
    _снимок(page, f"ai-glm-{ширина}")

    page.select_option("select[data-pick-nav]", label="Claude")
    page.wait_for_url("**ai=claude**")
    assert page.locator("#ai-claude-cc").is_visible()
    assert page.locator("#ai-connected b").first.is_visible()
    assert page.get_by_text("называет себя «ChatGPT»").is_visible()
    assert без_горизонтальной_прокрутки()
    _снимок(page, f"ai-claude-{ширина}")
