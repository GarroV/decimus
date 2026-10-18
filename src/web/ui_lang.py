"""Язык сайта: из профиля учётки, `?lang=` — разовый перекрёсток (D447).

Порядок один на все экраны (`request_lang`): язык, названный в адресе, если он
заведён; иначе язык из «Настроек» вошедшего (`web_users.web_lang`, `0061`);
иначе язык стенда. Выбор в «Настройках» и в пилюле меню сохраняется в профиль
(`POST /settings/lang`) — пилюля у вошедшего отправляет форму, а не ведёт по
ссылке. До входа профиля нет, и пилюля остаётся ссылкой с `?lang=`.

Бот и мини-апп хранят свой язык отдельно («Язык — параметр»): здесь только сайт.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlencode

from flask import Flask, current_app, redirect, request, url_for
from werkzeug.wrappers import Response

from src.db import web_own_profile
from src.db.errors import DbError

from . import auth
from .origin import over_https, refuse_foreign_origin
from .texts import UI_LANGS, lang_or_default

logger = logging.getLogger(__name__)

# На стенде открытого демо (D524) учётки ролей общие: язык, сохранённый в профиль,
# одному посетителю переключал бы его всем остальным. Там выбор живёт в куке
# браузера, а профиль не трогается.
DEMO_LANG_COOKIE = "decimus_demo_lang"
_DEMO_FLAG = "DECIMUS_DEMO_LANG_IN_COOKIE"
_DEMO_LANG_MAX_AGE_S = 7 * 24 * 3600


def own_lang(fallback: str) -> str:
    """Язык из профиля вошедшего, если он заведён; иначе `fallback` (язык стенда).

    В демо вместо профиля — кука этого браузера (`DEMO_LANG_COOKIE`).
    """
    if current_app.config.get(_DEMO_FLAG):
        выбранный = request.cookies.get(DEMO_LANG_COOKIE)
        return выбранный if выбранный in UI_LANGS else fallback
    выбранный = getattr(auth.current_account(), "web_lang", None)
    return выбранный if выбранный in UI_LANGS else fallback


def request_lang(stand_lang: str) -> str:
    """Язык этого запроса: `?lang=` → язык профиля → язык стенда."""
    return lang_or_default(request.args.get("lang"), fallback=own_lang(stand_lang))


def here_without_lang() -> str:
    """Путь этой страницы с её параметрами, но без `lang` — куда вернуть после выбора."""
    прочие = [(к, з) for к, з in request.args.items(multi=True) if к != "lang"]
    return f"{request.path}?{urlencode(прочие)}" if прочие else request.path


def _safe_back(raw: str | None) -> str | None:
    """Путь внутри приложения — или `None`: открытого редиректа здесь не будет."""
    if not raw or not raw.startswith("/") or raw.startswith("//"):
        return None
    if "\\" in raw or any(not знак.isprintable() for знак in raw):
        return None
    return raw


def _with_lang(path: str, lang: str) -> str:
    return f"{path}{'&' if '?' in path else '?'}{urlencode({'lang': lang})}"


def _remember_in_browser(назад: str, язык: str) -> Response:
    ответ = redirect(f"{request.script_root}{назад}")
    ответ.set_cookie(
        DEMO_LANG_COOKIE,
        язык,
        max_age=_DEMO_LANG_MAX_AGE_S,
        httponly=True,
        samesite="Lax",
        secure=over_https(),
        path="/",
    )
    return ответ


def install(app: Flask, path: str, *, demo: bool = False) -> None:
    """Маршрут сохранения языка и `lang_next` для пилюли в шаблонах."""
    app.config[_DEMO_FLAG] = demo

    @app.context_processor
    def _lang_next() -> dict[str, Any]:
        return {"lang_next": here_without_lang, "lang_save_path": path}

    @app.post(path)
    def settings_lang() -> Response:
        """Сохранить язык сайта своей учётке и вернуть туда, откуда выбрали.

        Не сохранилось (база молчит) — язык всё равно сменится на эту страницу
        через `?lang=`: человек нажал кнопку и должен увидеть результат, а
        сбой уходит в журнал.
        """
        refuse_foreign_origin()
        язык = request.form.get("lang") or ""
        назад = (
            _safe_back(request.form.get("next"))
            or url_for("settings_page")[len(request.script_root) :]
        )
        if язык not in UI_LANGS:
            return redirect(f"{request.script_root}{назад}")
        if demo:
            return _remember_in_browser(назад, язык)
        try:
            сохранён = web_own_profile.set_web_lang(auth.current_session_token(), язык)
        except DbError:
            logger.exception("язык сайта: сохранить в профиль не удалось")
            сохранён = False
        if not сохранён:
            return redirect(f"{request.script_root}{_with_lang(назад, язык)}")
        return redirect(f"{request.script_root}{назад}")
