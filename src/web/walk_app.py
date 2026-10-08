"""Сервис мини-аппа обхода: только адреса `/tg/walk*` и статика к ним.

Отдельное приложение, а не часть админки, по одной причине — праву записи.
Мини-апп пишет в идущую проверку (D312), поэтому его контейнер монтирует том
состояния на запись. Админка же состояние только читает, и её контейнер
держит тот же том `:ro`: всё, что открыто в админке, — вход, экраны, формы, —
до идущих проверок и признака сдачи (`bot.json`) дотянуться не может, даже
если в ней найдётся дыра.

Здесь нет ни входа админки, ни её экранов, ни сессий: опознаёт аудитора подпись
Telegram (`walk_auth`), и ничего, кроме адресов обхода, это приложение не
отвечает. Снаружи до него доходят через админку (`walk_proxy.py`).
"""

from __future__ import annotations

from flask import Flask

from . import assets, security_headers, walk
from .config import Settings, load_settings
from .walk_auth import WalkSettings

#: Предел тела по умолчанию. Кадр (до 10 МБ) поднимает его на своём адресе сам
#: (`walk_write.walk_photo`), остальные запросы — строки и короткий JSON.
MAX_BODY_BYTES = 256 * 1024


def create_walk_app(
    settings: Settings | None = None, *, walk_settings: WalkSettings | None = None
) -> Flask:
    """Собрать сервис обхода. Отказ окружения — `WebConfigError` до первого запроса."""
    conf = settings or load_settings()
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_BODY_BYTES
    assets.install(app)
    walk.install(app, ui_lang=conf.ui_lang, settings=walk_settings)
    security_headers.install(app, hsts=conf.hsts)
    return app
