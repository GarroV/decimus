"""Экран «Настройки» (`/settings`): настройки своего профиля — всё подключение в одном месте.

Одна страница, разделы сверху вниз: Claude (личный токен и подключение через
сайт), бот в Telegram, Google, язык интерфейса, пароль. Это не админка и не
второй «Пользователи»: людей здесь нет, только учётка самого вошедшего.
Откройте её любой ролью — у каждой роли свои права в Claude и боте, но
подключает их человек сам, и никто никому доступ не выдаёт (D448).

**Чья учётка — решает сессия, а не форма.** Ни один маршрут не читает
`user_id` из запроса: выпустить токен, привязать бота, сменить пароль или
отозвать подключение чужой учётке отсюда нечем. Заслон: общий заслон
происхождения приложения (чужая страница — 403 на любой POST), затем
`refuse_foreign_origin()` ещё раз, затем разбор формы.

**Секрет показывается один раз.** Токен Claude и ссылка привязки бота
уходят в ответ на POST, без перенаправления (адрес оседает в истории браузера
и журнале прокси), и нигде не хранятся; в журнал пишется факт выпуска, не
значение.

Работа с базой — слои `src/db/` (`mcp_access`, `bot_links`, `oauth_store`);
выпуск токена — одна функция на все двери, `mcp_access.issue_for_account`.
Те же дела в мини-аппе и боте идут через неё же: второй реализации нет.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from flask import Flask, current_app, make_response, render_template, request
from flask import Response as FlaskResponse

from src.db import bot_links, mcp_access, oauth_store
from src.db.errors import DbError
from src.domain.log_ids import log_id

from . import accounts, auth, guard, profile, users_claude, users_mcp
from .config import WEB_BOT_USERNAME_VAR, Settings
from .db_refusal import note_target_mismatch
from .origin import refuse_foreign_origin
from .remote import client_address
from .sections import section

logger = logging.getLogger(__name__)

#: Где приложение держит имя бота для ссылки привязки (`WEB_BOT_USERNAME`).
BOT_USERNAME_KEY = "DECIMUS_BOT_USERNAME"


def link_url(bot_username: str, token: str) -> str:
    """Ссылка привязки бота: Telegram передаст метку боту командой `/start` (D286)."""
    return f"https://t.me/{bot_username}?start={bot_links.LINK_PREFIX}{token}"


@dataclass(frozen=True)
class Flash:
    """Исход действия: ключ текста, тон и параметры подстановки."""

    key: str
    ok: bool
    params: dict[str, Any] | None = None


@dataclass(frozen=True)
class Show:
    """Что показать этим ответом поверх того, что есть в базе."""

    flash: Flash | None = None
    password: profile.Outcome | None = None
    bot_link: str | None = None
    bot_link_until: datetime | None = None
    #: Только что выпущенная команда Claude Desktop с личным токеном: живёт до
    #: ответа страницы и больше нигде не хранится.
    token: users_mcp.Issued | None = None


def _flash(key: str, *, ok: bool, **params: object) -> Flash:
    return Flash(key, ok, dict(params))


def _own_binding() -> tuple[Any, bool]:
    """Привязка бота вошедшего и «удалось ли прочитать»: молчание базы — не «не привязан»."""
    вошедший = auth.current_account()
    if вошедший is None:
        return None, True
    try:
        return bot_links.binding_of(вошедший.id), True
    except DbError as exc:
        note_target_mismatch(exc)
        return None, False


def render(show: Show | None = None, code: int = 200) -> tuple[str, int]:
    """Страница целиком — для GET и для ответа на любую отправку экрана."""
    show = show or Show()
    вошедший = auth.current_account()
    user_id = getattr(вошедший, "id", None)
    привязка, известна = _own_binding()
    return (
        render_template(
            "settings/index.html",
            show=show,
            me=вошедший,
            base=f"{request.script_root}{section('settings').path}",
            own_binding=привязка,
            own_binding_known=известна,
            bot_username=current_app.config.get(BOT_USERNAME_KEY),
            bot_var=WEB_BOT_USERNAME_VAR,
            mcp=users_mcp.own_status(user_id),
            claude=users_claude.claude_connect(
                user_id, current_app.config.get(users_claude.MCP_URL_KEY)
            ),
            min_password=accounts.MIN_PASSWORD_LENGTH,
            max_password=accounts.MAX_PASSWORD_LENGTH,
        ),
        code,
    )


def _current_id() -> str:
    вошедший = auth.current_account()
    if вошедший is None:
        raise RuntimeError("настройки без вошедшего: маршрут прошёл мимо заслона")
    return str(вошедший.id)


def install(app: Flask, conf: Settings) -> None:
    """Маршруты «Настроек»: страница и свои дела вошедшего."""
    base = section("settings").path
    app.config[BOT_USERNAME_KEY] = conf.bot_username
    app.config[users_claude.MCP_URL_KEY] = conf.mcp_public_url if conf.oauth_enabled else None

    @app.get(base)
    def settings_page() -> tuple[str, int]:
        return render()

    @app.post(f"{base}/password")
    def settings_own_password() -> FlaskResponse | tuple[str, int]:
        """Сменить СВОЙ пароль (#324). Чей — решает сессия этого запроса, не форма."""
        refuse_foreign_origin()
        вошедший = auth.current_account()
        if вошедший is None:
            raise RuntimeError("смена пароля без вошедшего: маршрут прошёл мимо заслона")
        исход = profile.change_own(
            current=request.form.get("current") or "",
            new=request.form.get("new") or "",
            repeat=request.form.get("repeat") or "",
            token=auth.current_session_token(),
            login=вошедший.login,
            stand=auth.throttle_tenant(),
            address=client_address(trusted_proxies=conf.trusted_proxies),
        )
        страница, код = render(Show(password=исход), исход.status)
        if исход.retry_after_seconds is None:
            return страница, код
        ответ = make_response(страница, код)
        ответ.headers["Retry-After"] = str(исход.retry_after_seconds)
        return ответ

    _install_bot(app, base, conf)
    _install_claude_token(app, base)
    if conf.oauth_enabled:
        _install_claude_connection(app, base)


def _install_bot(app: Flask, base: str, conf: Settings) -> None:
    """Привязка бота к своей учётке и отвязка (D286)."""

    @app.post(f"{base}/bot-link")
    @guard.action("inspection.conduct")
    def settings_bot_link() -> FlaskResponse | tuple[str, int]:
        """Выпустить ссылку привязки бота — ВСЕГДА своей учётке (D286).

        Ключ учётки из формы не читается вовсе: ссылка привязала бы чужой
        Telegram к выбранному человеку.
        """
        refuse_foreign_origin()
        чей = _current_id()
        if not conf.bot_username:
            return render(
                Show(flash=_flash("profile.bot.unset", ok=False, var=WEB_BOT_USERNAME_VAR)), 503
            )
        try:
            ссылка = bot_links.issue_link(чей)
        except DbError as exc:
            note_target_mismatch(exc)
            return render(Show(flash=_flash("profile.bot.link_failed", ok=False)), 503)
        return render(
            Show(
                bot_link=link_url(conf.bot_username, ссылка.token),
                bot_link_until=ссылка.expires_at,
            )
        )

    @app.post(f"{base}/bot-unlink")
    @guard.action("inspection.conduct")
    def settings_bot_unlink() -> FlaskResponse | tuple[str, int]:
        """Отвязать СВОЕГО бота. Чужую привязку снимает админ с карточки человека."""
        refuse_foreign_origin()
        чей = _current_id()
        try:
            отвязано = bot_links.unbind(чей)
        except DbError as exc:
            note_target_mismatch(exc)
            return render(Show(flash=_flash("users.bot.unlink_failed", ok=False)), 503)
        исход = "users.bot.unlinked" if отвязано else "users.bot.unlink_missing"
        return render(Show(flash=_flash(исход, ok=отвязано)))


def _install_claude_token(app: Flask, base: str) -> None:
    """Личный токен Claude: выпустить себе и отозвать свой (D447, D448)."""

    @app.post(f"{base}/claude-token")
    def settings_claude_token() -> FlaskResponse | tuple[str, int]:
        """Выпустить себе токен; команда показывается этим ответом один раз."""
        refuse_foreign_origin()
        чей = _current_id()
        try:
            выпуск = users_mcp.issue_own(чей)
        except DbError as exc:
            note_target_mismatch(exc)
            return render(Show(flash=_flash("users.mcp.failed", ok=False)), 503)
        # Значения токена в журнале нет: только факт выпуска.
        logger.info("Веб: учётка %s выпустила себе токен MCP", log_id(чей))
        return render(Show(token=выпуск))

    @app.post(f"{base}/claude-token-revoke")
    def settings_claude_token_revoke() -> FlaskResponse | tuple[str, int]:
        """Отозвать свой живой токен сразу."""
        refuse_foreign_origin()
        чей = _current_id()
        try:
            погашено = mcp_access.revoke_tokens(чей)
        except DbError as exc:
            note_target_mismatch(exc)
            return render(Show(flash=_flash("users.mcp.failed", ok=False)), 503)
        исход = "users.mcp.revoked" if погашено else "users.mcp.nothing"
        return render(Show(flash=_flash(исход, ok=bool(погашено))))


def _install_claude_connection(app: Flask, base: str) -> None:
    """Отключить своё подключение Claude через сайт (D417). Чужое — не найдётся."""

    @app.post(f"{base}/claude-revoke")
    def settings_claude_revoke() -> FlaskResponse | tuple[str, int]:
        """Отозвать подключение. Номер — из формы, владелец — всегда вошедший."""
        refuse_foreign_origin()
        чей = _current_id()
        номер = (request.form.get("connection_id") or "").strip()
        try:
            отозвано = oauth_store.revoke_connection(номер, user_id=чей)
        except DbError as exc:
            note_target_mismatch(exc)
            return render(Show(flash=_flash("users.claude.failed", ok=False)), 503)
        исход = "users.claude.revoked" if отозвано else "users.claude.revoke_missing"
        return render(Show(flash=_flash(исход, ok=отозвано)))
