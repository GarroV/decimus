"""Содержимое левой панели стоит на месте, когда у списка пунктов появляется своя полоса прокрутки.

Настоящий Chromium, страницы отдаёт Flask-клиент, статику — диск, остальное блокируется. Окно
нарочно низкое: меню не влезает, и у списка пунктов появляется своя вертикальная полоса
прокрутки — она не должна сдвигать пункты по горизонтали (владелец 10.11.2026: «левая панель
до сих пор прыгает»). Замер — `getBoundingClientRect` панели и первого пункта.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from conftest import chromium_executable
from web_harness import войти, подменить_двери, собрать

playwright = pytest.importorskip("playwright.sync_api")
STATIC = Path(__file__).resolve().parents[1] / "src/web/static"
ХОСТ = "http://decimus.test"
СТРАНИЦЫ = ("/overview", "/inspections", "/ratings")
ВЫСОТЫ = (500, 900)


@pytest.fixture
def стенд(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    подменить_двери(monkeypatch, tenant="HQ", role="admin")
    client = собрать(tenant="HQ").test_client()
    assert войти(client).status_code == 302
    return client


@pytest.fixture
def page(стенд) -> Iterator:  # type: ignore[no-untyped-def]
    with playwright.sync_playwright() as pw:
        executable = chromium_executable(pw.chromium.executable_path)
        # Без --hide-scrollbars: у мыши на Mac и Windows полоса прокрутки занимает место.
        browser = pw.chromium.launch(
            executable_path=executable, headless=True, ignore_default_args=["--hide-scrollbars"]
        )
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
  const out = {};
  for (const sel of ['.shell__nav', '.sidenav__head', '.sidenav__brand', '.sidenav__fold',
      '.sidenav__search', '.sidenav__list', '.sidenav__list > :first-child',
      '.sidenav__foot', '.sidenav__user']) {
    const n = document.querySelector(sel);
    const r = n && n.getBoundingClientRect();
    out[sel] = r && [r.left, r.width];
  }
  const list = document.querySelector('.sidenav__list');
  out.scrolls = list.scrollHeight > list.clientHeight;
  return out;
}"""


def _замер(page, ветка: str) -> dict:  # type: ignore[no-untyped-def]
    page.evaluate(f"document.documentElement.setAttribute('data-nav-ratings-open','{ветка}')")
    page.wait_for_timeout(300)
    return page.evaluate(_ЗАМЕР)


@pytest.mark.parametrize("свёрнута", ["false"])
@pytest.mark.parametrize("высота", ВЫСОТЫ)
def test_панель_стоит_на_месте_при_раскрытии_рейтингов_и_смене_страницы(
    page, высота: int, свёрнута: str
) -> None:
    page.set_viewport_size({"width": 1440, "height": высота})
    page.add_init_script(f"localStorage.setItem('decimus-nav-collapsed','{свёрнута}')")
    замеры = {}
    for путь in СТРАНИЦЫ:
        page.goto(f"{ХОСТ}{путь}")
        for ветка in ("false", "true"):
            замеры[(путь, ветка)] = _замер(page, ветка)
    if высота == ВЫСОТЫ[0]:  # иначе проверка пустая: прокрутки у списка нет
        assert any(z["scrolls"] for z in замеры.values()), замеры
    эталон = замеры[(СТРАНИЦЫ[0], "false")]
    for ключ, замер in замеры.items():
        for что, значение in замер.items():
            if что != "scrolls":
                assert значение == эталон[что], (ключ, что, значение, эталон[что])


_ВЕРТИКАЛЬ = """() => {
  const items = [...document.querySelectorAll('.sidenav__list > *')]
    .filter(n => !n.classList.contains('sidenav__branch'))
    .map(n => Math.round(n.getBoundingClientRect().height));
  const t = document.querySelector('.sidenav__branch-toggle').getBoundingClientRect();
  const list = document.querySelector('.sidenav__list');
  return { items, toggleTop: Math.round(t.top), scrolls: list.scrollHeight > list.clientHeight };
}"""


@pytest.mark.parametrize("высота", (600, 800))
def test_пункты_не_сжимаются_и_рейтинги_не_уезжают_вверх(page, высота: int) -> None:
    """Раскрытая ветка не помещается — пункты держат высоту, «Рейтинги» остаются под курсором.

    Владелец 12.11.2026: «левая панель до сих пор прыгает когда разворачиваешь вкладку
    рейтингов». Без `flex-shrink: 0` у пунктов (forma 63bd06b) колонка сплющивала их с 34 до
    18 px, и пункт «Рейтинги» уезжал вверх на ~96 px.
    """
    page.set_viewport_size({"width": 1440, "height": высота})
    page.add_init_script("localStorage.setItem('decimus-nav-collapsed','false')")
    page.goto(f"{ХОСТ}/overview")
    page.evaluate("document.documentElement.setAttribute('data-nav-ratings-open','false')")
    page.wait_for_timeout(300)
    закрыта = page.evaluate(_ВЕРТИКАЛЬ)
    page.evaluate("document.documentElement.setAttribute('data-nav-ratings-open','true')")
    page.wait_for_timeout(400)
    открыта = page.evaluate(_ВЕРТИКАЛЬ)
    assert открыта["scrolls"], (
        "проверка пустая: раскрытый список поместился, сжатию неоткуда взяться"
    )
    assert открыта["toggleTop"] == закрыта["toggleTop"], (закрыта, открыта)
    assert открыта["items"] == закрыта["items"], (закрыта, открыта)
