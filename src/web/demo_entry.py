"""Вход в открытое демо (D524): выбор роли и сессия без пароля — только на стенде демо.

Маршруты регистрируются ТОЛЬКО при `WEB_DEMO=1`. На проде их нет вовсе, и
`/demo` отвечает 404 тем же путём, что любой несуществующий адрес: проверки
«включено ли» внутри маршрута, которую можно забыть или обойти, здесь нет.

Учётки ролей заводит посев (`tools/seed_open_demo.py`) со случайным паролем;
логины — из общего контракта `src.domain.demo`. Сессия открывается тем же
`open_session`, что у входа паролем, и кладётся той же кукой (`remember`).
"""

from __future__ import annotations

from collections.abc import Callable

from flask import Flask, abort, redirect, render_template, request, url_for
from werkzeug.wrappers import Response

from src.db.web_access import OpenedSession, find_by_login, open_session
from src.domain.demo import DEMO_ROLES, demo_role

from . import journal as web_journal
from .config import Settings
from .origin import refuse_foreign_origin
from .walk_auth import PAGE_PATH as WALK_PAGE_PATH

#: Что в демо выключено: учётки ролей общие на всех посетителей, и один посетитель
#: не должен сломать вход остальным — подключить второй способ (тогда вход без
#: пароля упрётся во вторую ступень), заморозить или понизить учётку, сменить ей
#: пароль, привязать Google или выйти «везде». Ключ модели посетитель не сохраняет:
#: чужие ключи демо не собирает. Сброс раз в час починил бы и это, но час без демо —
#: тоже поломка.
LOCKED_ENDPOINTS = frozenset(
    {
        "freeze_user",
        "unfreeze_user",
        "user_role",
        "user_email",
        "reset_second_factor",
        "security_backup_generate",
        "security_passkey_delete",
        "security_passkey_options",
        "security_passkey_register",
        "security_prove_code",
        "security_relogin",
        "security_totp_confirm",
        "security_totp_remove",
        "security_totp_start",
        "settings_own_password",
        "settings_google_link",
        "settings_google_unlink",
        "settings_bot_link",
        "settings_bot_unlink",
        "settings_claude_token",
        "settings_claude_token_revoke",
        "settings_sign_out_everywhere",
        "model_key_save",
        "model_key_check",
        "model_key_delete",
    }
)

#: Маршруты демо — открытые (без входа): `auth.OPEN_ENDPOINTS`.
ENDPOINTS = frozenset({"demo_pick", "demo_enter", "demo_app"})


def install(
    app: Flask,
    conf: Settings,
    *,
    remember: Callable[[Response, OpenedSession], Response],
) -> None:
    """Плашка демо на всех страницах и, на стенде демо, маршруты входа."""

    @app.context_processor
    def _демо() -> dict[str, object]:
        return {"demo_mode": conf.demo, "demo_url": conf.demo_url}

    if not conf.demo:
        return

    @app.before_request
    def _в_демо_выключено() -> tuple[str, int] | None:
        if request.method == "POST" and request.endpoint in LOCKED_ENDPOINTS:
            return render_template("demo/locked.html"), 403
        return None

    приложение = conf.walk_upstream is not None

    @app.get("/demo", endpoint="demo_pick")
    def demo_pick() -> str:
        return render_template(
            "demo/pick.html",
            roles=DEMO_ROLES,
            walk_href=url_for("demo_app") if приложение else None,
        )

    @app.get("/demo/app", endpoint="demo_app")
    def demo_app() -> str:
        """Мини-апп аудитора в рамке телефона — потрогать без Telegram.

        Сам мини-апп открыт на стенде в режиме просмотра (`WEB_WALK_PREVIEW_CHAT`)
        на идущую проверку, которую собирает посев.
        """
        if not приложение:
            abort(404)
        return render_template("demo/app.html", walk_src=request.script_root + WALK_PAGE_PATH)

    @app.post("/demo/<key>", endpoint="demo_enter")
    def demo_enter(key: str) -> Response | tuple[str, int]:
        refuse_foreign_origin()
        роль = demo_role(key)
        if роль is None:
            abort(404)
        учётка = find_by_login(роль.login)
        if учётка is None or учётка.tenant != роль.tenant:
            # Посев как раз пересобирает базу (раз в час) — не поломка, а минута.
            return (
                render_template("demo/pick.html", roles=DEMO_ROLES, not_ready=True, walk_href=None),
                503,
            )
        откуда, браузер = web_journal.login_origin(conf)
        сессия = open_session(учётка, ip=откуда, user_agent=браузер, step_waived=True)
        return remember(redirect(url_for("home")), сессия)
