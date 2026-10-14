"""Экран «Настройки» (`/settings`): настройки своего профиля — всё подключение в одном месте.

Одна страница плитками (D470, как в Swarm Brain): карточка «Профиль» со
строками, малые карточки «Язык» и «Пароль», ниже «Подключения» — плитки Claude
(личный токен и подключение через сайт), бота в Telegram и Google, а справа от
них панель выбранной (`?tile=`, работает без скрипта). Это не админка и не
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

from flask import Flask, current_app, make_response, redirect, render_template, request, url_for
from flask import Response as FlaskResponse
from werkzeug.wrappers import Response

from src.db import bot_links, journals, mcp_access, oauth_store, web_own_profile
from src.db.errors import DbError
from src.db.web_throttle import Verdict, admit_attempt, note_success
from src.domain.journal import METHOD_MCP_TOKEN, RESULT_OK
from src.domain.log_ids import log_id
from src.domain.tenants import HQ_TENANT, canonical_tenant

from . import (
    account_menu,
    accounts,
    auth,
    google_link,
    guard,
    profile,
    reauth,
    ui_lang,
    users_claude,
    users_mcp,
)
from . import journal as web_journal
from .config import WEB_BOT_USERNAME_VAR, Settings
from .db_refusal import note_target_mismatch
from .google_auth import load_hq_domains
from .origin import refuse_foreign_origin
from .remote import client_address
from .sections import section
from .texts import t

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


def _google_result() -> Flash | None:
    """Исход возврата от Google (`?google=`) — только из закрытого списка."""
    ключ = google_link.RESULTS.get(request.args.get(google_link.RESULT_PARAM) or "")
    return None if ключ is None else Flash(ключ[0], ключ[1])


#: Плитки подключений, они же значения `?tile=`: порядок — порядок на экране.
TILES = (
    "profile",
    "language",
    "password",
    "security",
    "signins",
    "signout",
    "claude",
    "bot",
    "google",
)

#: Плитка, к которой относится исход действия: по началу ключа текста.
_FLASH_TILE_PREFIXES = (
    ("settings.google.", "google"),
    ("users.mcp.", "claude"),
    ("users.claude.", "claude"),
    ("users.bot.", "bot"),
    ("profile.bot.", "bot"),
    ("settings.signout.", "signout"),
)


def selected_tile(show: Show, requested: str | None) -> str:
    """Какая плитка раскрыта: явный `?tile=`, иначе — та, чьё дело только что сделано.

    Токен и ссылка привязки показываются один раз ответом на POST, а исход
    действия должен лежать там, где человек нажал кнопку, — не в другой плитке.
    """
    if requested in TILES:
        return str(requested)
    if show.token is not None:
        return "claude"
    if show.bot_link:
        return "bot"
    if show.password is not None:
        return "password"
    if show.flash is not None:
        for префикс, плитка in _FLASH_TILE_PREFIXES:
            if show.flash.key.startswith(префикс):
                return плитка
    return TILES[0]


def tile_states(
    *,
    show: Show,
    mcp: Any,
    claude: Any,
    own_binding: Any,
    own_binding_known: bool,
    has_google: bool,
) -> dict[str, str]:
    """Состояние каждой плитки: `on` / `off` / `unknown` — точка и слово, не цвет один."""
    if show.token is not None or mcp.expires_at or claude.connections:
        claude_state = "on"
    elif not mcp.known or (claude.enabled and not claude.known):
        claude_state = "unknown"
    else:
        claude_state = "off"
    if show.bot_link:
        bot_state = "off"
    elif not own_binding_known:
        bot_state = "unknown"
    else:
        bot_state = "on" if own_binding else "off"
    return {"claude": claude_state, "bot": bot_state, "google": "on" if has_google else "off"}


def _own_tile_states(account: Any, google_login: bool) -> dict[str, str]:
    """Точка плиток собственной учётки: заведено ли то, о чём плитка."""
    return {
        "profile": "on",
        "language": "on",
        "password": "off" if google_login else "on",
        "security": "on" if getattr(account, "has_second_factor", False) else "off",
        "signins": "on",
        "signout": "on",
    }


def _tile_hints(account: Any, lang: str, google_login: bool) -> dict[str, str]:
    """Короткая строка под названием плитки собственной учётки; длинное — в панели."""
    return {
        "profile": str(getattr(account, "display_name", None) or getattr(account, "login", "")),
        "language": lang.upper(),
        "password": t(
            "settings.tile.password_google" if google_login else "settings.tile.password_set", lang
        ),
        "security": t(
            "sf.sec.status_on"
            if getattr(account, "has_second_factor", False)
            else "sf.sec.status_off",
            lang,
        ),
        "signins": t("settings.tile.signins", lang),
        "signout": t("settings.tile.signout", lang),
    }


def render(show: Show | None = None, code: int = 200) -> tuple[str, int]:
    """Страница целиком — для GET и для ответа на любую отправку экрана."""
    show = show or Show(flash=_google_result())
    вошедший = auth.current_account()
    user_id = getattr(вошедший, "id", None)
    привязка, известна = _own_binding()
    статус_токена = users_mcp.own_status(user_id)
    подключение = users_claude.claude_connect(
        user_id, current_app.config.get(users_claude.MCP_URL_KEY)
    )
    has_google_login = bool(getattr(вошедший, "email", None)) and bool(
        current_app.extensions.get(auth.GOOGLE_ENABLED_KEY)
    )
    lang = ui_lang.request_lang(current_app.extensions["decimus_conf"].ui_lang)
    состояния = tile_states(
        show=show,
        mcp=статус_токена,
        claude=подключение,
        own_binding=привязка,
        own_binding_known=известна,
        has_google=has_google_login,
    )
    return (
        render_template(
            "settings/index.html",
            show=show,
            tile=selected_tile(show, request.args.get("tile")),
            tile_states={**состояния, **_own_tile_states(вошедший, has_google_login)},
            tile_hint=_tile_hints(вошедший, lang, has_google_login),
            tiles=TILES,
            me=вошедший,
            base=f"{request.script_root}{section('settings').path}",
            own_binding=привязка,
            own_binding_known=известна,
            bot_username=current_app.config.get(BOT_USERNAME_KEY),
            bot_var=WEB_BOT_USERNAME_VAR,
            mcp=статус_токена,
            claude=подключение,
            min_password=accounts.MIN_PASSWORD_LENGTH,
            max_password=accounts.MAX_PASSWORD_LENGTH,
            hq_account=вошедший is not None and canonical_tenant(вошедший.tenant) == HQ_TENANT,
            hq_domains=", ".join(sorted(load_hq_domains())),
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
    def settings_page() -> FlaskResponse | tuple[str, int]:
        """Чистое чтение: заряженное намерение здесь НИЧЕГО не выпускает.

        Изменение состояния на GET позволило бы чужой странице выполнить действие,
        пока намерение заряжено. Поэтому вместо выполнения — страница с одной
        кнопкой, отправляющей POST (`/settings/continue`) с проверкой происхождения.
        """
        действие = reauth.take_intent(auth.current_account())
        if действие is None:
            return render()
        ответ = make_response(render_template("settings/continue.html", action=действие))
        ответ.headers["Cache-Control"] = "no-store"
        return ответ

    @app.post(f"{base}/continue")
    def settings_continue() -> Response | FlaskResponse | tuple[str, int]:
        """Выполнить то, что человек просил до подтверждения входа (D457)."""
        refuse_foreign_origin()
        действие = reauth.take_intent(auth.current_account())
        if действие is None:
            ответ = redirect(f"{request.script_root}{base}")
            reauth.drop_intent(ответ)
            return ответ
        ответ = make_response(run_intent(conf, действие))
        reauth.drop_intent(ответ)
        # Токен и ссылка в ответе показываются один раз — не в кэше.
        ответ.headers["Cache-Control"] = "no-store"
        return ответ

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
    _install_google(app, base, conf)
    ui_lang.install(app, f"{base}/lang")
    _install_account_menu(app, base, conf)
    _install_claude_token(app, base, conf)
    _install_sign_out_everywhere(app, base)
    if conf.oauth_enabled:
        _install_claude_connection(app, base)


#: Сколько браузер держит своё фото без вопросов. Адрес несёт версию
#: (`?v=<avatar_etag>`), поэтому смена фото — новый адрес, а не ожидание.
AVATAR_MAX_AGE_SECONDS = 86400


def _install_account_menu(app: Flask, base: str, conf: Settings) -> None:
    """Своё фото и подгружаемая часть меню учётки (D468)."""

    @app.get(f"{base}/avatar")
    def settings_avatar() -> FlaskResponse | Response:
        """Фото ВОШЕДШЕГО из Google. Чужое по ключу не отдаётся: ключа нет вовсе.

        Чьё фото — решает сессия этого запроса (`web_own_profile.own_avatar`
        выбирает строку по её токену); в адрес и форму ничего, называющего
        учётку, не входит. Ответ `private`: общий кэш прокси фото человека не
        хранит.
        """
        try:
            найдено = web_own_profile.own_avatar(auth.current_session_token())
        except DbError as exc:
            note_target_mismatch(exc)
            return make_response("", 503)
        if найдено is None:
            return make_response("", 404)
        данные, тип, версия = найдено
        ответ = make_response(данные)
        ответ.mimetype = тип
        ответ.set_etag(версия)
        ответ.headers["Cache-Control"] = f"private, max-age={AVATAR_MAX_AGE_SECONDS}"
        ответ.headers["Vary"] = "Cookie"
        ответ.headers["X-Content-Type-Options"] = "nosniff"
        return ответ.make_conditional(request)

    @app.get(f"{base}/menu")
    def settings_menu() -> FlaskResponse:
        """Группа «Подключения» меню учётки — фрагмент, а не страница.

        Подгружается при первом открытии меню: состояния стоят трёх запросов,
        и каждая страница их платить не должна.
        """
        вошедший = auth.current_account()
        if вошедший is None:
            raise RuntimeError("меню без вошедшего: маршрут прошёл мимо заслона")
        строки = account_menu.connections(
            str(вошедший.id),
            email=вошедший.email,
            google_enabled=bool(current_app.extensions.get(auth.GOOGLE_ENABLED_KEY)),
            mcp_url=current_app.config.get(users_claude.MCP_URL_KEY),
        )
        ответ = make_response(render_template("_account_menu_connections.html", rows=строки))
        ответ.headers["Cache-Control"] = "no-store"
        return ответ


def _install_sign_out_everywhere(app: Flask, base: str) -> None:
    """«Выйти везде» (D462): все свои сессии, подключения Claude и личный токен. Бот остаётся."""

    @app.post(f"{base}/sign-out-everywhere")
    def settings_sign_out_everywhere() -> Response | tuple[str, int]:
        """Закрыть всё, чем вошёл человек, и увести на вход. Чья учётка — решает сессия."""
        refuse_foreign_origin()
        чей = _current_id()
        try:
            закрыто = accounts.sign_out_everywhere(auth.current_session_token())
        except DbError as exc:
            note_target_mismatch(exc)
            return render(Show(flash=_flash("settings.signout.failed", ok=False)), 503)
        if закрыто:
            logger.info("Веб: учётка %s вышла везде", log_id(чей))
        # Сессия закрыта и в базе, и в браузере: кука больше ничего не значит.
        ответ = redirect(url_for("login"))
        ответ.delete_cookie(auth.COOKIE_NAME, path="/")
        return ответ


def _issue_bot_link(conf: Settings, base: str) -> tuple[str, int]:
    """Выпустить ссылку привязки бота своей учётке: кнопка и выполнение после подтверждения."""
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


def _start_google_link(conf: Settings, base: str) -> Response:
    """Увести к Google привязывать почту: кнопка и выполнение после подтверждения."""
    вошедший = auth.current_account()
    if вошедший is not None and вошедший.email:
        return google_link.back_to_settings("already")
    return auth.begin_google_link()


def _issue_claude_token(conf: Settings, base: str) -> tuple[str, int]:
    """Выпустить себе токен Claude: кнопка и выполнение после подтверждения."""
    чей = _current_id()
    try:
        выпуск = users_mcp.issue_own(чей)
    except DbError as exc:
        note_target_mismatch(exc)
        return render(Show(flash=_flash("users.mcp.failed", ok=False)), 503)
    # Значения токена в журнале нет: только факт выпуска.
    logger.info("Веб: учётка %s выпустила себе токен MCP", log_id(чей))
    вошедший = auth.current_account()
    откуда, браузер = web_journal.login_origin(conf)
    journals.record_login(
        method=METHOD_MCP_TOKEN,
        result=RESULT_OK,
        user_id=чей,
        ip=откуда,
        user_agent=браузер,
        session_id=вошедший.session_id if вошедший else None,
    )
    return render(Show(token=выпуск))


#: Что выполняется само после подтверждения входа (`reauth.INTENT_ACTIONS`).
_RUN_INTENT = {
    "bot-link": _issue_bot_link,
    "google-link": _start_google_link,
    "claude-token": _issue_claude_token,
}


def run_intent(conf: Settings, action: str) -> Any:
    """Выполнить намерение тем же кодом, что кнопка, и с тем же правом.

    Зовут `POST /settings/continue` и подтверждение паролем (`reauth`): ссылка
    бота — по матрице `inspection.conduct`, как у кнопки.
    """
    if action == "bot-link" and not guard.may("inspection.conduct"):
        return guard.forbidden()
    return _RUN_INTENT[action](conf, section("settings").path)


def _install_bot(app: Flask, base: str, conf: Settings) -> None:
    """Привязка бота к своей учётке и отвязка (D286)."""

    @app.post(f"{base}/bot-link")
    @guard.action("inspection.conduct")
    def settings_bot_link() -> Response | FlaskResponse | tuple[str, int]:
        """Выпустить ссылку привязки бота — ВСЕГДА своей учётке (D286).

        Ключ учётки из формы не читается вовсе: ссылка привязала бы чужой
        Telegram к выбранному человеку.
        """
        refuse_foreign_origin()
        # Создаёт долгоживущий доступ — только по свежему входу (`reauth`).
        if (переспрос := reauth.require_fresh(f"{base}?tile=bot", "bot-link")) is not None:
            return переспрос
        return _issue_bot_link(conf, base)

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


def _install_google(app: Flask, base: str, conf: Settings) -> None:
    """Своя почта Google: привязать (D447) и снять — только зная пароль (D450)."""

    @app.post(f"{base}/google-link")
    def settings_google_link() -> Response:
        """Увести к Google. Только POST со своей страницы: чужая не начнёт привязку."""
        refuse_foreign_origin()
        # Создаёт долгоживущий доступ — только по свежему входу (`reauth`).
        if (переспрос := reauth.require_fresh(f"{base}?tile=google", "google-link")) is not None:
            return переспрос
        return _start_google_link(conf, base)

    @app.post(f"{base}/google-unlink")
    def settings_google_unlink() -> Response | FlaskResponse | tuple[str, int]:
        """Снять свою почту: после снятия вход — паролем, поэтому пароль обязателен.

        Попытки считаются тем же счётчиком, что у входа (как смена пароля): иначе
        форма стала бы вторым входом для подбора пароля из чужой открытой вкладки.
        """
        refuse_foreign_origin()
        # Создаёт долгоживущий доступ — только по свежему входу (`reauth`).
        if (переспрос := reauth.require_fresh(f"{base}?tile=google")) is not None:
            return переспрос
        вошедший = auth.current_account()
        if вошедший is None:
            raise RuntimeError("снятие почты без вошедшего: маршрут прошёл мимо заслона")
        текущий = request.form.get("current") or ""
        if not текущий:
            return render(Show(flash=_flash("settings.google.unlink.empty", ok=False)), 400)
        адрес = client_address(trusted_proxies=conf.trusted_proxies)
        попытка = admit_attempt(tenant=auth.throttle_tenant(), address=адрес, login=вошедший.login)
        if not попытка.admitted:
            return _unlink_locked(попытка.verdict)
        try:
            итог = web_own_profile.unlink_google(auth.current_session_token(), current=текущий)
        except DbError as exc:
            note_target_mismatch(exc)
            return render(Show(flash=_flash("settings.google.done.db", ok=False)), 503)
        if итог == "denied":
            if попытка.verdict.locked:
                return _unlink_locked(попытка.verdict)
            return render(Show(flash=_flash("settings.google.unlink.wrong", ok=False)), 400)
        note_success(tenant=auth.throttle_tenant(), login=вошедший.login)
        if итог == "none":
            return google_link.back_to_settings()
        logger.info(
            "Google: учётка %s сняла почту %s",
            log_id(вошедший.id),
            google_link.mask_email(вошедший.email or ""),
        )
        return google_link.back_to_settings("unlinked")


def _unlink_locked(приговор: Verdict) -> FlaskResponse:
    """Запертому — срок словами и `Retry-After` тем же числом, как у входа."""
    страница, код = render(
        Show(
            flash=_flash(
                "settings.google.unlink.locked", ok=False, minutes=приговор.retry_after_minutes
            )
        ),
        429,
    )
    ответ = make_response(страница, код)
    ответ.headers["Retry-After"] = str(приговор.retry_after_seconds)
    return ответ


def _install_claude_token(app: Flask, base: str, conf: Settings) -> None:
    """Личный токен Claude: выпустить себе и отозвать свой (D447, D448)."""

    @app.post(f"{base}/claude-token")
    def settings_claude_token() -> Response | FlaskResponse | tuple[str, int]:
        """Выпустить себе токен; команда показывается этим ответом один раз."""
        refuse_foreign_origin()
        # Создаёт долгоживущий доступ — только по свежему входу (`reauth`).
        if (переспрос := reauth.require_fresh(f"{base}?tile=claude", "claude-token")) is not None:
            return переспрос
        return _issue_claude_token(conf, base)

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
