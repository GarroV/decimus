"""Мини-апп как приложение аудитора (D373): настройки и круг доступа к MCP.

`POST /tg/walk/app` — одно действие за запрос (`op`):

- `lang` — язык интерфейса человека (D303). Тот же выбор, что `/lang` бота:
  хранится за Telegram ID (`db.bot_langs`), бот подхватывает его сам;
- `mcp_issue` — готовая команда подключения Claude с личным токеном. Токен
  показывается один раз и гасит прежний, как кнопка `/mcp` (D098);
- `mcp_who`, `mcp_add`, `mcp_revoke` — круг доступа к MCP (D099), только тем,
  кто в нём;
- `stops` — отказы мастера за период (#436), тоже только кругу.

Правила те же, что у бота, и функции те же (`db.mcp_access`, `bot.stops`):
мини-апп — второй вход в одно и то же, а не вторая реализация. Отличие одно:
меню бота у приведённого и отозванного не пересобирается отсюда — пункты
MCP в чате появятся или пропадут после перезапуска бота; главный вход в
настройку теперь мини-апп.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any

from flask import Flask, Response, jsonify, request

from src.bot import stops
from src.bot.config import BotSettings, load_bot_settings
from src.bot.errors import BotConfigError
from src.bot.mcp_setup import MCP_URL_VAR, setup_command
from src.bot.texts import t
from src.bot.version import build_version
from src.db import bot_langs, mcp_access
from src.db.errors import DbError
from src.domain.errors import DomainError

from .texts import UI_LANGS
from .texts_walk import WALK_TEXTS
from .walk_access import space_of
from .walk_auth import APP_ENDPOINT, APP_PATH, WalkSettings
from .walk_write import Identify, Respond

logger = logging.getLogger(__name__)

#: Период счётчика отказов по умолчанию и предел — как у `/stops`.
STOPS_DEFAULT_DAYS = 7
STOPS_MAX_DAYS = stops.STOPS_RETENTION_DAYS


class Refused(Exception):
    """Отказ словами экрана: ключ каталога и код ответа."""

    def __init__(self, key: str, status: int = 422) -> None:
        super().__init__(key)
        self.key = key
        self.status = status


def bot_settings() -> BotSettings | None:
    """Настройки бота из того же окружения. Нет или битые — без круга MCP."""
    try:
        return load_bot_settings(os.environ)
    except BotConfigError:
        logger.warning("Мини-апп: настройки бота не прочитались — круг MCP недоступен")
        return None


def chosen_lang(chat_id: int) -> str | None:
    """Выбор языка человека (D303). База молчит — как без выбора."""
    try:
        lang = bot_langs.chosen_lang(chat_id)
    except DbError:
        logger.warning("Мини-апп: выбор языка %s не прочитался", chat_id, exc_info=True)
        return None
    return lang if lang in UI_LANGS else None


def in_circle(chat_id: int, bot: BotSettings | None, *, restore: bool = True) -> bool:
    """В круге доступа к MCP ли человек. Основатель — по настройке, как у бота.

    `restore` — вернуть основателя в таблицу, как делает бот. На чтении экрана
    (каждые данные) не нужно: там вопрос только «показывать ли пункт».
    """
    if bot is None or bot.mcp_owner_id is None:
        return False
    if chat_id == bot.mcp_owner_id:
        if restore:
            mcp_access.add_admin(chat_id, by=None)
        return True
    return mcp_access.is_admin(chat_id)


def app_block(chat_id: int, lang: str, bot: BotSettings | None) -> dict[str, Any]:
    """Что знает о человеке главная и настройки. Отказ базы — круг скрыт."""
    try:
        circle = in_circle(chat_id, bot, restore=False)
    except DbError:
        logger.warning("Мини-апп: круг MCP не прочитался для %s", chat_id, exc_info=True)
        circle = False
    return {
        "me": chat_id,
        "lang": lang,
        "langs": [{"code": code, "label": t("lang.self_name", code)} for code in UI_LANGS],
        "version": build_version(),
        "mcp": bot is not None and bot.mcp_owner_id is not None,
        "circle": circle,
        "sections": ["audit"],
    }


def _who(row: mcp_access.AdminRow, bot: BotSettings) -> dict[str, Any]:
    return {
        "id": row.telegram_id,
        "name": bot.auditor_names.get(row.telegram_id, ""),
        "live": row.is_live,
        "founder": row.telegram_id == bot.mcp_owner_id,
        "token": row.has_live_token,
        "at": (row.added_at if row.is_live else row.revoked_at or "")[:10],
    }


def _target(body: dict[str, Any]) -> int:
    raw = str(body.get("id", "")).strip()
    if not raw.lstrip("-").isdigit():
        raise Refused("walk.app.err.id")
    return int(raw)


def _circle_op(op: str, body: dict[str, Any], who: int, bot: BotSettings) -> dict[str, Any]:
    """Действия круга. Заслон — здесь: кнопку можно нажать и без меню."""
    if op == "mcp_add":
        кому = _target(body)
        if кому not in bot.allowed_ids:
            raise Refused("walk.app.err.not_allowed")
        mcp_access.add_admin(кому, by=who)
    elif op == "mcp_revoke":
        у_кого = _target(body)
        if у_кого == bot.mcp_owner_id:
            raise Refused("walk.app.err.founder")
        mcp_access.revoke_access(у_кого, by=who)
    elif op == "stops":
        return {"stops": _stops(body)}
    return {"circle": [_who(row, bot) for row in mcp_access.list_admins()]}


def _stops(body: dict[str, Any]) -> list[dict[str, Any]]:
    days = body.get("days", STOPS_DEFAULT_DAYS)
    if not isinstance(days, int) or not 1 <= days <= STOPS_MAX_DAYS:
        raise Refused("walk.app.err.days")
    since = datetime.now(UTC) - timedelta(days=days)
    try:
        counts = stops.count_stops(since)
    except (OSError, DomainError) as exc:
        raise Refused("walk.app.err.unavailable", 503) from exc
    return [
        {"step": c.step, "reason": c.reason, "times": c.times, "people": c.people} for c in counts
    ]


def _issue(who: int, conf: WalkSettings, lang: str) -> dict[str, Any]:
    space = space_of(who, conf)
    if space is None:
        raise Refused("walk.app.err.unavailable", 503)
    выпущен = mcp_access.issue_token(who, tenant=space)
    url = (os.environ.get(MCP_URL_VAR) or "").strip() or t("mcp.url_unknown", lang)
    return {
        "command": setup_command(url=url, token=выпущен.value),
        "replaced": выпущен.replaced_previous,
    }


def install(
    app: Flask,
    *,
    conf: WalkSettings,
    ui_lang: str,
    identify: Identify,
    respond: Respond,
    bot: BotSettings | None,
) -> None:
    """Повесить `POST /tg/walk/app`. Опознание — то же, что у записи."""

    def refused(key: str, lang: str, status: int) -> tuple[Response, int]:
        entry = WALK_TEXTS[key]
        return jsonify({"error": "refused", "message": entry.get(lang) or entry[ui_lang]}), status

    @app.after_request
    def no_store(response: Response) -> Response:
        # Команда с токеном и состав круга — данные одного человека.
        if request.endpoint == APP_ENDPOINT:
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.post(APP_PATH, endpoint=APP_ENDPOINT)
    def walk_app() -> tuple[Response, int]:
        who = identify(conf, ui_lang, header_only=True)
        if not isinstance(who, int):
            return who
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return refused("walk.err.bad_request", ui_lang, 400)
        lang = chosen_lang(who) or ui_lang
        op = body.get("op")
        try:
            if op == "lang":
                code = body.get("lang")
                if code not in UI_LANGS:
                    raise Refused("walk.app.err.lang")
                bot_langs.choose_lang(who, str(code))
                return respond(who, ui_lang)
            if op not in ("mcp_issue", "mcp_who", "mcp_add", "mcp_revoke", "stops"):
                raise Refused("walk.err.bad_request", 400)
            if bot is None or not in_circle(who, bot):
                raise Refused("walk.app.err.not_circle", 403)
            if op == "mcp_issue":
                # Значения токена в журнале нет: только факт выпуска.
                logger.info("Мини-апп: чат %s выпустил токен MCP", who)
                return jsonify(_issue(who, conf, lang)), 200
            return jsonify(_circle_op(op, body, who, bot)), 200
        except Refused as exc:
            return refused(exc.key, lang, exc.status)
        except DbError:
            logger.exception("Мини-апп: действие %s чата %s — база не ответила", op, who)
            return refused("walk.app.err.unavailable", lang, 503)
