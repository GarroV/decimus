"""Посадочная страница (D524, D545–D547): стопка листов с настоящими снимками.

Здесь то, что ломается молча: текст на одном языке из двух, снимок, которого нет на
диске или который переснят с другим размером, ссылка «Войти» без возврата, лист без
заголовка. Экран целиком — `make landing-shots` и глаза, а не тест.
"""

from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any

import pytest
from flask import Flask
from PIL import Image
from web_harness import СЕКРЕТ

from src.web import landing
from src.web.app import create_app
from src.web.config import Settings
from src.web.texts_demo import DEMO_TEXTS

STATIC = Path(landing.__file__).parent / "static"
SHOTS = STATIC / landing.SHOTS_DIR
ДЕМО = "https://demo.example/demo"
ЯЗЫКИ = ("ru", "en")
# Снимки страницы: имя без языка.
СНИМКИ = ("walk", "match", "plan", "report", "actions", "network", "pizzerias")


def _клиент(**настройки: Any) -> Any:
    app: Flask = create_app(
        Settings(
            host="127.0.0.1", port=8266, tenant="HQ", ui_lang="en", secret_key=СЕКРЕТ, **настройки
        )
    )
    app.config.update(TESTING=True)
    return app.test_client()


def _страница(lang: str, **настройки: Any) -> str:
    return _клиент(**настройки).get(f"/welcome?lang={lang}").get_data(as_text=True)


def test_каждый_текст_лендинга_есть_на_обоих_языках() -> None:
    ключи = {k: v for k, v in DEMO_TEXTS.items() if k.startswith("landing.")}
    assert ключи, "тексты лендинга не найдены"
    for ключ, перевод in ключи.items():
        for язык in ЯЗЫКИ:
            assert перевод.get(язык, "").strip(), f"{ключ}: нет текста на «{язык}»"


@pytest.mark.parametrize("язык", ЯЗЫКИ)
def test_страница_не_показывает_сырых_ключей(язык: str) -> None:
    """Ключ без перевода выводится как есть: `landing.…` в разметке — потерянный текст."""
    assert (
        re.search(r"landing\.[a-z]", re.sub(r"<[^>]+>", "", _страница(язык, demo_url=ДЕМО))) is None
    )


@pytest.mark.parametrize("язык", ЯЗЫКИ)
def test_все_листы_и_заголовки_на_месте(язык: str) -> None:
    страница = _страница(язык, demo_url=ДЕМО)
    assert страница.count('class="lp-sheet ') == 7, "ожидалось семь листов"
    assert страница.count("<h1") == 1, "заголовок первого уровня должен быть один"
    assert страница.count("<h2") == 6, "у каждого листа после первого — свой заголовок"
    for ключ in ("landing.hero.title", "landing.walk.title", "landing.cta.title"):
        assert DEMO_TEXTS[ключ][язык] in страница


@pytest.mark.parametrize("язык", ЯЗЫКИ)
def test_снимки_лежат_на_диске_с_верными_размерами(язык: str) -> None:
    """Файл есть, `width`/`height` в разметке — из `sizes.json`, а он — по самому файлу."""
    страница = _страница(язык, demo_url=ДЕМО)
    for имя in СНИМКИ:
        ключ = f"{имя}-{язык}"
        файл = SHOTS / f"{ключ}.webp"
        assert файл.is_file(), f"нет снимка {файл.name}: `make landing-shots`"
        assert f"/static/landing/{ключ}.webp" in страница
        with Image.open(файл) as снимок:
            ждём = [снимок.width // 2, снимок.height // 2]
        assert landing.SHOT_SIZES[ключ] == ждём, f"{ключ}: sizes.json разошёлся с файлом"
        assert f'width="{ждём[0]}" height="{ждём[1]}"' in страница


def test_у_каждого_снимка_есть_альтернативный_текст() -> None:
    for язык in ЯЗЫКИ:
        страница = _страница(язык, demo_url=ДЕМО)
        for имя in СНИМКИ:
            assert f'alt="{DEMO_TEXTS[f"landing.alt.{имя}"][язык]}"' in html.unescape(страница)


def test_только_первый_снимок_грузится_сразу() -> None:
    страница = _страница("en", demo_url=ДЕМО)
    картинки = re.findall(r"<img[^>]*lp-shot[^>]*>", страница)
    assert len(картинки) == len(СНИМКИ)
    assert 'loading="lazy"' not in картинки[0]
    assert all('loading="lazy"' in кадр for кадр in картинки[1:])


@pytest.mark.parametrize("язык", ЯЗЫКИ)
def test_кнопка_демо_и_вход_ведут_куда_надо(язык: str) -> None:
    страница = _страница(язык, demo_url=ДЕМО)
    assert страница.count(f'href="{ДЕМО}?lang={язык}"') == 3  # шапка, первый экран, финал
    assert f'href="/login?lang={язык}"' in страница


def test_вход_несёт_адрес_возврата() -> None:
    страница = (
        _клиент(demo_url=ДЕМО).get("/welcome?lang=en&next=/inspections").get_data(as_text=True)
    )
    assert "/login?next=/inspections&amp;lang=en" in страница


def test_без_адреса_демо_кнопок_демо_нет() -> None:
    страница = _страница("en")
    assert "Open the demo" not in страница and 'class="lp-cta' not in страница
    assert "Sign in" in страница


def test_страница_подключает_свои_стили_и_скрипт_файлами() -> None:
    страница = _страница("en", demo_url=ДЕМО)
    assert "/static/decimus-landing.css" in страница and "/static/landing.js" in страница
    assert (STATIC / "decimus-landing.css").is_file() and (STATIC / "landing.js").is_file()
    # Политика источников (#489): встроенного кода нет.
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>\s*\S", страница)


def test_стили_лендинга_не_лежат_в_общем_файле() -> None:
    """Они переехали в `decimus-landing.css` и подключаются только лендингом."""
    общий = (STATIC / "decimus-web.css").read_text(encoding="utf-8")
    assert ".lp-" not in общий


def test_оранжевый_бренда_только_у_главной_кнопки() -> None:
    css = (STATIC / "decimus-landing.css").read_text(encoding="utf-8")
    assert len(re.findall(r"var\(--brand-orange\)", css)) == 2  # фон и осветление при наведении
    assert css.count(".lp-cta") >= 1
    assert "linear-gradient" not in css and "text-transform: uppercase" not in css
