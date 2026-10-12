"""Мини-апп как приложение аудитора (D373): настройки и подключение Claude.

`POST /tg/walk/app` — одно действие за запрос (`op`):

- `lang` — язык интерфейса человека (D303). Тот же выбор, что `/lang` бота:
  хранится за Telegram ID (`db.bot_langs`), бот подхватывает его сам;
- `mcp_issue` — готовая команда подключения Claude с личным токеном на
  учётку, к которой привязан бот. Токен показывается один раз и гасит прежний,
  как кнопка `/mcp` (D098). Выпускает себе каждый, кого мини-апп пускает:
  круга доступа нет (D448), права в Claude решает роль учётки;
- `finish_mode` — режим «Завершить» человека (D449): `summary` или `report`,
  хранится за Telegram ID (`db.finish_modes`);
- `translate_mode` — перевод комментариев на язык отчёта (D443): `button` или
  `auto`, хранится за Telegram ID (`db.translate_modes`); перевод идёт при
  сборке отчёта (`bot.finish_translate`);
- `finish` — «Завершить проверку» (D422, D449): в режиме `summary` итог в чат,
  как `/finish`; в `report` — отчёт сразу (`walk_finish.py`).

Правила те же, что у бота, и функция выпуска та же (`db.mcp_access`):
мини-апп — второй вход в одно и то же, а не вторая реализация.

**Выпуск токена — только по свежей подписи** (аудит 12.10,
F-032): подпись Telegram для них годна `MINT_MAX_AGE_SECONDS` (5 минут), а не
шесть часов, как у записи проверки. Строка, утёкшая из журнала или с экрана,
иначе шесть часов выпускала бы токены на чужое имя.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from flask import Flask, Response, jsonify, request

from src.bot.config import BotSettings, load_bot_settings
from src.bot.errors import BotConfigError
from src.bot.mcp_setup import MCP_URL_VAR, setup_command
from src.bot.texts import t
from src.bot.version import build_version
from src.db import bot_langs, finish_modes, mcp_access, translate_modes
from src.db.errors import DbError, UnboundError
from src.domain.log_ids import log_id

from . import walk_finish
from .texts import UI_LANGS
from .texts_walk import WALK_TEXTS
from .walk_auth import (
    APP_ENDPOINT,
    APP_PATH,
    INIT_DATA_HEADER,
    MINT_MAX_AGE_SECONDS,
    WalkAccessError,
    WalkSettings,
    chat_of,
)
from .walk_write import Identify, Respond

logger = logging.getLogger(__name__)


class Refused(Exception):
    """Отказ словами экрана: ключ каталога и код ответа."""

    def __init__(self, key: str, status: int = 422, **extra: Any) -> None:
        """`extra` — число для текста (`{count}`) и поля ответа рядом с `message`."""
        super().__init__(key)
        self.key = key
        self.status = status
        self.extra = extra


def bot_settings() -> BotSettings | None:
    """Настройки бота из того же окружения. Нет или битые — `None`."""
    try:
        return load_bot_settings(os.environ)
    except BotConfigError:
        logger.warning("Мини-апп: настройки бота не прочитались")
        return None


def chosen_lang(chat_id: int) -> str | None:
    """Выбор языка человека (D303). База молчит — как без выбора."""
    try:
        lang = bot_langs.chosen_lang(chat_id)
    except DbError:
        logger.warning("Мини-апп: выбор языка %s не прочитался", log_id(chat_id), exc_info=True)
        return None
    return lang if lang in UI_LANGS else None


def finish_mode_of(chat_id: int) -> str:
    """Режим «Завершить» человека (D449). Не выбирал или база молчит — сначала сводка."""
    try:
        mode = finish_modes.chosen_finish_mode(chat_id)
    except DbError:
        logger.warning(
            "Мини-апп: режим завершения %s не прочитался", log_id(chat_id), exc_info=True
        )
        return finish_modes.DEFAULT_MODE
    return mode if mode in finish_modes.MODES else finish_modes.DEFAULT_MODE


def translate_mode_of(chat_id: int) -> str:
    """Перевод комментариев человека (D443). Не выбирал или база молчит — по кнопке."""
    try:
        mode = translate_modes.chosen_translate_mode(chat_id)
    except DbError:
        logger.warning("Мини-апп: режим перевода %s не прочитался", log_id(chat_id), exc_info=True)
        return translate_modes.DEFAULT_MODE
    return mode if mode in translate_modes.MODES else translate_modes.DEFAULT_MODE


def app_block(chat_id: int, lang: str, bot: BotSettings | None) -> dict[str, Any]:
    """Что знает о человеке главная и настройки.

    `mcp` — показывать ли «Подключить Claude»: стенду с ботом — всем, кого
    мини-апп пускает (D448). Учётки за чатом может не быть (сотрудник УК по
    списку окружения) — тогда выпуск ответит словами, как привязать бота.
    """
    return {
        "me": chat_id,
        "lang": lang,
        "langs": [{"code": code, "label": t("lang.self_name", code)} for code in UI_LANGS],
        "finish_mode": finish_mode_of(chat_id),
        "translate_mode": translate_mode_of(chat_id),
        "version": build_version(),
        "mcp": bot is not None,
        "sections": ["audit"],
    }


def _fresh(who: int, conf: WalkSettings) -> None:
    """Подпись не старше `MINT_MAX_AGE_SECONDS` — для выпуска токена (F-032).

    Просмотр без подписи (стенд без бота) свежестью не меряется: подписи нет,
    а на проде он не включается (`walk_auth.load_walk_settings`).
    """
    if conf.bot_token is None:
        return
    try:
        свежий = chat_of(
            request.headers.get(INIT_DATA_HEADER, ""), conf, max_age=MINT_MAX_AGE_SECONDS
        )
    except WalkAccessError as exc:
        raise Refused("walk.app.err.stale", 401) from exc
    if свежий != who:
        raise Refused("walk.app.err.stale", 401)


def _issue(who: int, lang: str) -> dict[str, Any]:
    try:
        выпущен = mcp_access.issue_token(who)
    except UnboundError as exc:
        raise Refused("walk.app.err.unbound_self") from exc
    url = (os.environ.get(MCP_URL_VAR) or "").strip() or t("mcp.url_unknown", lang)
    return {
        "command": setup_command(url=url, token=выпущен.value),
        "replaced": выпущен.replaced_previous,
        # Срок токена (`MCP_TOKEN_TTL_DAYS`): после него команду берут заново.
        "expires": выпущен.expires_at.date().isoformat(),
    }


def _finish(who: int, conf: WalkSettings, body: dict[str, Any], lang: str) -> tuple[Response, int]:
    """«Завершить проверку» (D422, D449). Сообщение уходит только в чат подписавшего."""
    if conf.bot_token is None:
        raise Refused("walk.finish.err.failed", 503)
    mode = finish_mode_of(who)
    if mode == finish_modes.REPORT:
        return _finish_report(who, conf.bot_token, body, lang)
    outcome = walk_finish.send_summary(conf.bot_token, who)
    if outcome == walk_finish.NO_INSPECTION:
        raise Refused("walk.finish.err.none", 409)
    if outcome == walk_finish.FAILED:
        raise Refused("walk.finish.err.failed", 503)
    return jsonify({"sent": True, "mode": mode}), 200


_REPORT_REFUSALS = {
    walk_finish.NO_INSPECTION: ("walk.finish.err.none", 409),
    walk_finish.LANG_GONE: ("walk.finish.err.lang", 409),
    walk_finish.INFO_MISSING: ("walk.finish.err.info", 409),
    walk_finish.BUSY: ("walk.finish.err.busy", 409),
    walk_finish.FAILED: ("walk.finish.err.failed", 503),
}


def _finish_report(who: int, token: str, body: dict[str, Any], lang: str) -> tuple[Response, int]:
    """Отчёт сразу: язык из перечня страны, сведения заполнены, сборка в фоне."""
    report_lang = body.get("report_lang")
    if report_lang is not None and not isinstance(report_lang, str):
        raise Refused("walk.finish.err.lang", 409)
    started = walk_finish.start_report(token, who, report_lang, lang)
    if started.status != walk_finish.STARTED:
        key, status = _REPORT_REFUSALS[started.status]
        if started.status == walk_finish.INFO_MISSING:
            raise Refused(key, status, count=started.missing, reason="info")
        raise Refused(key, status)
    return jsonify({"sent": True, "mode": finish_modes.REPORT}), 200


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

    def refused(
        key: str, lang: str, status: int, extra: dict[str, Any] | None = None
    ) -> tuple[Response, int]:
        entry = WALK_TEXTS[key]
        text = entry.get(lang) or entry[ui_lang]
        fields = extra or {}
        if "count" in fields:
            text = text.format(count=fields["count"])
        return jsonify({"error": "refused", "message": text, **fields}), status

    @app.after_request
    def no_store(response: Response) -> Response:
        # Команда с токеном — данные одного человека.
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
            if op == "finish_mode":
                mode = body.get("mode")
                if mode not in finish_modes.MODES:
                    raise Refused("walk.app.err.finish_mode")
                finish_modes.choose_finish_mode(who, str(mode))
                return respond(who, ui_lang)
            if op == "translate_mode":
                mode = body.get("mode")
                if mode not in translate_modes.MODES:
                    raise Refused("walk.app.err.translate_mode")
                translate_modes.choose_translate_mode(who, str(mode))
                return respond(who, ui_lang)
            if op == "finish":
                return _finish(who, conf, body, lang)
            if op != "mcp_issue":
                raise Refused("walk.err.bad_request", 400)
            if bot is None:
                raise Refused("walk.app.err.unavailable", 503)
            _fresh(who, conf)
            выпуск = _issue(who, lang)
            # Значения токена в журнале нет: только факт выпуска.
            logger.info("Мини-апп: чат %s выпустил себе токен MCP", log_id(who))
            return jsonify(выпуск), 200
        except Refused as exc:
            return refused(exc.key, lang, exc.status, exc.extra)
        except DbError:
            logger.exception("Мини-апп: действие %s чата %s — база не ответила", op, log_id(who))
            return refused("walk.app.err.unavailable", lang, 503)
