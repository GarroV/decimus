"""Снимки живых экранов для посадочной страницы (D545) — одной командой.

    make landing-shots                       # открытое демо, ru и en
    LANDING_SHOTS_BASE=http://127.0.0.1:8080 make landing-shots

Язык браузера (`locale`) ставится по языку снимка: мини-апп обхода выбирает по нему
русскую или английскую идущую проверку демо (`WEB_WALK_PREVIEW_CHAT_RU`), поэтому
русский снимок обхода получается целиком русским, а не с английскими записями.

Скрипт сам входит на стенд открытого демо (`/demo` → роль без пароля), открывает
настоящие экраны за «всё время» — иначе в демо-данных почти пусто, — прячет плашку
«Демо: выдуманные данные…» и пишет обрезанные ретина-снимки (deviceScaleFactor 2) в
`src/web/static/landing/<имя>-<язык>.webp` и их размеры — в `sizes.json`. Ничего не рисуется
и не подставляется:
только прячется плашка и лишние рамки экрана. Пересъёмка нужна при каждой правке
интерфейса, видимой на этих экранах (реестр — docs/12-web-admin.md, «Снимки на посадочной»).

Playwright — не зависимость проекта: если его нет в `.venv`, цель `make` ставит его
сама (`pip install playwright`), браузер берётся из кеша Playwright.
"""

from __future__ import annotations

import io
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path

from PIL import Image
from playwright.sync_api import Page, sync_playwright

BASE = os.environ.get("LANDING_SHOTS_BASE", "https://decimus-demo.vasiliy-garro.workers.dev")
OUT = Path(__file__).resolve().parent.parent / "src" / "web" / "static" / "landing"
LANGS = ("ru", "en")
LOCALES = {"ru": "ru-RU", "en": "en-US"}
# Куски английского интерфейса и пустого календаря: на русском снимке обхода их быть не
# должно, а на снимке календаря не должно быть «поездок: 0». Нашлись — съёмка падает,
# а не пишет негодный снимок: так стенд, не обновлённый после правки посева, виден сразу.
ENGLISH_ON_RU_WALK = ("Found last time", "Recorded now", "Not looked at yet", "Checked")
ENGLISH_ON_RU_SHEET = ("Save", "What you see", "Photo", "Back")
EMPTY_TRIPS = ("поездок: 0", "trips: 0")
SCALE = 2
WEBP_QUALITY = 86
# Окно уже обычного: снимок показывается шириной в полстраницы, и текст на нём должен читаться.
DESKTOP = {"width": 1120, "height": 900}
PHONE = {"width": 390, "height": 844}
# Плашка демо и всё, что на экране служебное и к смыслу снимка не относится.
HIDE_CSS = ".demo-bar{display:none !important}"


def hide_chrome(page: Page, extra: str = "") -> None:
    page.add_style_tag(content=HIDE_CSS + extra)


def enter(page: Page, role: str, lang: str) -> None:
    """Войти в демо ролью без пароля: язык кладётся в куку на странице выбора роли."""
    page.goto(f"{BASE}/demo?lang={lang}")
    page.click(f'form[action^="/demo/{role}"] button')
    page.wait_for_load_state("networkidle")


def settle(page: Page) -> None:
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(500)


def block_clip(page: Page, first: str, last: str, pad: float = 12.0) -> dict[str, float]:
    """Рамка вокруг блоков от верхнего из `first` до нижнего из `last` (селекторы — любые)."""
    box = page.evaluate(
        """([a, b]) => {
            const r = (sel) =>
                [...document.querySelectorAll(sel)].map((e) => e.getBoundingClientRect());
            const all = [...r(a), ...r(b)];
            const left = Math.min(...all.map((x) => x.left));
            const right = Math.max(...all.map((x) => x.right));
            const top = Math.min(...r(a).map((x) => x.top));
            const bottom = Math.max(...r(b).map((x) => x.bottom));
            return {x: left, y: top + scrollY, width: right - left, height: bottom - top};
        }""",
        [first, last],
    )
    return {
        "x": box["x"] - pad,
        "y": box["y"] - pad,
        "width": box["width"] + 2 * pad,
        "height": box["height"] + 2 * pad,
    }


def main_clip(page: Page, *, height: float | None = None, pad: float = 0.0) -> dict[str, float]:
    """Рабочая область `main` целиком (или первые `height` пикселей)."""
    box = page.evaluate(
        """() => {
            const m = document.querySelector('main').getBoundingClientRect();
            return {x: m.left, y: m.top + scrollY, width: m.width, height: m.height};
        }"""
    )
    h = min(box["height"], height) if height else box["height"]
    return {
        "x": box["x"] - pad,
        "y": box["y"] - pad,
        "width": box["width"] + 2 * pad,
        "height": h + 2 * pad,
    }


SIZES: dict[str, list[int]] = {}


def save(page: Page, name: str, lang: str, clip: dict[str, float] | None) -> Path:
    png = page.screenshot(clip=clip, full_page=clip is not None)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}-{lang}.webp"
    image = Image.open(io.BytesIO(png)).convert("RGB")
    image.save(path, "WEBP", quality=WEBP_QUALITY, method=6)
    # Размеры в CSS-пикселях — в `width`/`height` картинки, чтобы страница не прыгала.
    SIZES[f"{name}-{lang}"] = [image.width // SCALE, image.height // SCALE]
    return path


def shot_walk(page: Page, lang: str) -> Path:
    """Экран обхода мини-аппа: зона в работе, найденное в прошлый раз и записи."""
    page.goto(f"{BASE}/tg/walk?lang={lang}")
    settle(page)
    hide_chrome(page)
    if lang == "ru":
        text = page.inner_text("body")
        leaked = [w for w in ENGLISH_ON_RU_WALK if w in text]
        if leaked:
            raise RuntimeError(
                f"русский снимок обхода с английским текстом {leaked}: стенд без русской проверки?"
            )
    return save(page, "walk", lang, None)


def shot_match(page: Page, lang: str) -> Path:
    """Запись обхода: к словам проверяющего подобран пункт чек-листа, осталось подтвердить."""
    page.goto(f"{BASE}/tg/walk?lang={lang}")
    settle(page)
    hide_chrome(page)
    page.click(".walk-rec__open")
    page.wait_for_selector(".walk-sheet")
    page.wait_for_timeout(500)
    if lang == "ru":
        text = page.inner_text(".walk-sheet")
        leaked = [w for w in ENGLISH_ON_RU_SHEET if w in text]
        if leaked or "Сохранить" not in text:
            raise RuntimeError(f"русский снимок записи с английским текстом {leaked}")
    return save(page, "match", lang, None)


def shot_report(page: Page, lang: str) -> Path:
    """Карточка проверки: оценка, буква, потери по зонам и нарушения."""
    page.goto(f"{BASE}/overview?period=all&lang={lang}")
    settle(page)
    # Первая проверка из «Требует внимания» — завершённая, с потерями и нарушениями.
    page.goto(
        BASE + page.eval_on_selector("main a[href^='/inspections/']", "e => e.getAttribute('href')")
    )
    settle(page)
    hide_chrome(page)
    page.click("details.mx-more--explain summary")
    page.wait_for_timeout(300)
    # Без ссылки «назад» и пометки про PDF: от карточки оценки до последнего блока.
    return save(
        page, "report", lang, block_clip(page, ".icard > .card", ".icard > section.ov-card")
    )


def shot_plan(page: Page, lang: str) -> Path:
    """Календарь: проверки месяца с оценками и поездки проверяющих."""
    page.goto(f"{BASE}/calendar?from=2026-07-01&to=2026-07-31&lang={lang}")
    settle(page)
    hide_chrome(page)
    # `text_content`, не `inner_text`: счётчик поездок лежит под значком «?» и скрыт (D632),
    # а `inner_text` скрытого не видит — проверка молча перестала бы что-либо ловить.
    text = page.text_content("main") or ""
    if any(mark in text for mark in EMPTY_TRIPS):
        raise RuntimeError("в календаре нет поездок: стенд без поездок в посеве?")
    return save(page, "plan", lang, main_clip(page))


def shot_actions(page: Page, lang: str) -> Path:
    """Планы действий у партнёра."""
    page.goto(f"{BASE}/actions?tab=plans&lang={lang}")
    settle(page)
    hide_chrome(page)
    return save(page, "actions", lang, main_clip(page))


def shot_network(page: Page, lang: str) -> Path:
    """Главная УК за всё время: потери по направлениям и таблица пиццерий."""
    page.goto(f"{BASE}/overview?period=all&lang={lang}")
    settle(page)
    # Раскладка D557: верхний ряд — фильтры и блок рейтингов (в демо пуст), второй —
    # период, «Топ нарушений», «Где сеть теряет проценты». Прячем верхний ряд и
    # карточку периода: снимок — про нарушения и потери, ряд встаёт парой.
    hide_chrome(
        page,
        ".hm-top,.hm-grid--3 > section:first-child{display:none !important}"
        ".hm-grid--3{grid-template-columns:repeat(2,minmax(0,1fr)) !important}",
    )
    clip = block_clip(page, ".hm-grid--3 > section:nth-child(n+2)", "section.hm-units")
    return save(page, "network", lang, clip)


def shot_pizzerias(page: Page, lang: str) -> Path:
    """«Пиццерии»: страна слева, выбранная пиццерия справа."""
    page.goto(f"{BASE}/country/AM?period=all&lang={lang}")
    settle(page)
    unit = page.eval_on_selector("a[href*='unit=']", "e => e.getAttribute('href')")
    page.goto(BASE + unit)
    settle(page)
    hide_chrome(page)
    rail = page.evaluate("() => document.querySelector('main').getBoundingClientRect().height")
    return save(page, "pizzerias", lang, main_clip(page, height=min(float(rail), 440.0), pad=0.0))


# (роль, область окна, съёмщик)
SHOTS: list[tuple[str, dict[str, int], Callable[[Page, str], Path]]] = [
    ("admin", PHONE, shot_walk),
    ("admin", PHONE, shot_match),
    ("admin", DESKTOP, shot_report),
    ("admin", DESKTOP, shot_plan),
    ("partner", DESKTOP, shot_actions),
    ("admin", DESKTOP, shot_network),
    ("admin", DESKTOP, shot_pizzerias),
]


def main() -> int:
    written: list[Path] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for lang in LANGS:
            for role, viewport, shooter in SHOTS:
                context = browser.new_context(
                    viewport=viewport, device_scale_factor=SCALE, locale=LOCALES[lang]
                )
                page = context.new_page()
                try:
                    enter(page, role, lang)
                    written.append(shooter(page, lang))
                finally:
                    context.close()
        browser.close()
    (OUT / "sizes.json").write_text(
        json.dumps(SIZES, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    for path in written:
        print(
            f"{path.relative_to(OUT.parent.parent.parent.parent)}  {path.stat().st_size // 1024} КБ"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
