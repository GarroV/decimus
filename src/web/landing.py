"""Посадочная страница продукта (D524): что такое Decimus, «Войти» и «Открыть демо».

Её видит только неопознанный посетитель: любой адрес админки ведёт его сюда, а не
на форму входа (`auth._guard`, D544), и выход из учётки тоже; исключение —
согласие Claude, оно идёт сразу на вход. Вошедший на `/` попадает на «Главную», как
и раньше. Кнопка демо ведёт на `WEB_DEMO_URL`, на самом стенде демо — на его
`/demo`; ни того ни другого — кнопки нет.

Страница — стопка листов (D546): каждый раздел наезжает на предыдущий. Картинки на
ней — настоящие снимки демо-стенда (D545), их делает `make landing-shots`.
"""

from __future__ import annotations

import json
from pathlib import Path

from flask import Flask, render_template, request, url_for

from .config import Settings

ENDPOINT = "landing"
PATH = "/welcome"
# Папка снимков и размеры в CSS-пикселях: их пишет `tools/landing_shots.py`.
SHOTS_DIR = "landing"
SHOT_SIZES: dict[str, list[int]] = json.loads(
    (Path(__file__).parent / "static" / SHOTS_DIR / "sizes.json").read_text(encoding="utf-8")
)


def install(app: Flask, conf: Settings) -> None:
    @app.get(PATH, endpoint=ENDPOINT)
    def landing() -> str:
        демо = url_for("demo_pick") if conf.demo else conf.demo_url
        # Куда человек шёл до посадочной (D544): «Войти» несёт адрес дальше, форма
        # входа сама проверяет его на свой ли сайт (`auth.safe_next`).
        return render_template(
            "landing.html",
            demo_href=демо,
            login_href=_login_href(request.args.get("next")),
            shot_sizes=SHOT_SIZES,
        )


def _login_href(next_path: str | None) -> str:
    """Адрес «Войти»: форма входа, а если человек шёл на страницу — с возвратом туда."""
    from .auth import safe_next  # auth сам импортирует этот модуль

    куда = safe_next(next_path)
    return url_for("login", next=куда) if куда else url_for("login")
