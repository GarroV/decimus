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
#: тоже поломка. И ничего из демо не выходит наружу: ни Google, ни Telegram, ни
#: Claude, ни ключи API — демо показывает продукт, а не выдаёт к нему доступ.
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
        "service_key_save",
        "service_key_check",
        "service_key_delete",
        # Подтверждение входа и «продолжить» выполняют то же намерение, что кнопки
        # выше (`reauth.INTENT_ACTIONS`): закрыта кнопка — закрыт и обход через них.
        "settings_continue",
        "reauth_confirm",
        "reauth_confirm_password",
        "reauth_confirm_google",
        # Круг людей и пространств: новая учётка с паролем пережила бы час до сброса,
        # а перепривязка стран сломала бы роль партнёра всем посетителям.
        "add_user",
        "add_space",
        "space_countries",
        "bot_unlink",
        # Выход наружу — настоящие сервисы под настоящими ключами: ключи API на
        # данные, Google (вход, почта, таблица), сайты агрегаторов.
        "connections_issue",
        "connections_reissue",
        "connections_revoke",
        "connections_update",
        "google_start",
        "google_callback",
        "google_mail_callback",
        "letter_draft",
        "rx_send",
        "ratings_agg_update",
        "ratings_sheet_sync",
    }
)

#: Действия, которые в демо работают: вход и смена роли, язык, фильтры и вся
#: работа с данными демо-сети — проверки, методика, поездки, планы, рейтинги.
#: Сброс раз в час возвращает их к исходному. Каждое действие (не GET) продукта
#: стоит в одном из двух списков — новое не проскочит в демо незамеченным (тест).
OPEN_ENDPOINTS = frozenset(
    {
        "demo_enter",
        "login",
        "logout",
        "passkey_login_options",
        "passkey_login_verify",
        "second_step_code",
        "second_step_passkey_options",
        "second_step_passkey_verify",
        "settings_lang",
        "country_filter",
        "photo_upload_post",
        "rx_create",
        "rx_close",
        "rx_update",
        "rx_request",
        "rx_approve",
        "rx_return",
        "order_reply",
        "actions_new",
        "actions_due",
        "actions_review",
        "plans_upload",
        "methodology_bot",
        "checklists_create",
        "checklists_apply",
        "checklists_master",
        "checklists_state",
        "methodology_add",
        "methodology_edit",
        "methodology_disable",
        "methodology_restore",
        "methodology_publish",
        "methodology_route",
        "methodology_scoring",
        "methodology_zone_add",
        "methodology_zone_remove",
        "methodology_zone_rename",
        "methodology_zone_shares",
        "trip_create",
        "trip_update",
        "trip_delete",
        "trip_step_add",
        "trip_step_delete",
        "country_set_developer",
        "country_set_space",
        "country_save_contract",
        "country_delete_contract",
        "unit_create",
        "do_accept",
        "do_add_finding",
        "do_add_photo",
        "do_revise",
        "save_letter",
        "do_move",
        "do_delete_photo",
        "do_retract",
        "do_suggest",
        "ratings_developer",
        "ratings_coverage_link",
        "ratings_rule_add",
        "ratings_rule_remove",
        "ratings_upload",
        "ratings_layout",
        "ratings_settings",
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
        # Любым методом: вход через Google и возвраты из него — GET.
        if request.endpoint in LOCKED_ENDPOINTS:
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
