"""Посадочная страница продукта (D524): что такое Decimus, «Войти» и «Открыть демо».

Её видит только неопознанный посетитель: корень админки ведёт его сюда, а не
сразу на форму входа (`auth._guard`). Вошедший на `/` попадает на «Главную», как
и раньше. Кнопка демо ведёт на `WEB_DEMO_URL`, на самом стенде демо — на его
`/demo`; ни того ни другого — кнопки нет.
"""

from __future__ import annotations

from flask import Flask, render_template, url_for

from .config import Settings

ENDPOINT = "landing"
PATH = "/welcome"


def install(app: Flask, conf: Settings) -> None:
    @app.get(PATH, endpoint=ENDPOINT)
    def landing() -> str:
        демо = url_for("demo_pick") if conf.demo else conf.demo_url
        return render_template("landing.html", demo_href=демо)
