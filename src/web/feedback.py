"""Кнопка «Обратная связь» (D761 п.6) и одноимённая вкладка «Администрирования».

**Кнопка.** Плавающая, справа снизу, на каждой странице для вошедшего (`base.html`), любой
роли и любого пространства; в мини-аппе обхода (`/tg/walk`) её нет. Окно шлёт форму сюда
(`POST /feedback`, JSON в ответ): текст до `MAX_TEXT` знаков и до `MAX_PHOTOS` фото. Тип фото
определяется по байтам (`db.photo_intake.sniff_image`), а не по имени и заголовку клиента;
сохраняется сжатая JPEG-копия (`db.previews.make_preview`, тот же путь, что у кадров проверок).
Автоматически прикладываются адрес страницы (без хоста), язык, учётка, роль, пространство,
время. Предел — `db.feedback.MAX_PER_HOUR` отзывов в час на учётку; сверх него отказ.

Отправлять может любой вошедший: маршрут в `guard.EXEMPT_ENDPOINTS`, как прочие дела самого
человека. Читать отзывы — нет: вкладку, фото и отметку «разобрано» открывает `service.settings`
(главный админ и админ УК), чат Telegram задаёт только `keys.manage` (главный админ).

**Telegram.** После записи отзыв уходит в чат из настройки (`feedback_telegram`); чат не задан —
ничего не уходит. Сбой отправки отзыв не ломает.

В демо (`demo_entry.LOCKED_ENDPOINTS`) кнопка есть, а отправка закрыта: окно говорит об этом
само и поля в нём отключены.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from urllib.parse import urlsplit

import psycopg
from flask import (
    Flask,
    Response,
    abort,
    g,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
)
from werkzeug.datastructures import FileStorage
from werkzeug.exceptions import RequestEntityTooLarge

from src.db import feedback as db_feedback
from src.db.errors import DbError, StorageError
from src.db.photo_intake import sniff_image
from src.db.previews import make_preview
from src.domain.tenants import canonical_tenant
from src.domain.uploads import MAX_UPLOAD_BYTES

from . import administration, auth, feedback_telegram, guard, ui_lang
from .config import Settings
from .origin import refuse_foreign_origin
from .sections import section
from .texts import t

logger = logging.getLogger(__name__)

SEND_PATH = "/feedback"
TAB = "feedback"
#: Длина сообщения, знаков (проверка базы `0136` — те же 4000).
MAX_TEXT = 4000
#: Сколько фото в одном отзыве.
MAX_PHOTOS = 5
#: Типы фото, которые принимаются (по содержимому, не по имени).
PHOTO_TYPES = frozenset({"jpeg", "png", "webp"})
#: Поля формы и границы частей поверх самих файлов.
FORM_OVERHEAD_BYTES = 64 * 1024
MAX_PAGE_CHARS = 500
#: Номер чата Telegram: цифры, у групп минус впереди (как проверка базы `0136`).
_CHAT_RE = re.compile(r"-?[0-9]{5,20}")
OPENING_ACTION = "service.settings"
CHAT_ACTION = "keys.manage"


def _mb() -> int:
    return MAX_UPLOAD_BYTES // (1024 * 1024)


def page_of(raw: str | None) -> str:
    """Адрес страницы, с которой пишут: путь и запрос без хоста, не длиннее предела."""
    parts = urlsplit((raw or "").strip())
    path = parts.path or "/"
    query = f"?{parts.query}" if parts.query else ""
    return f"{path}{query}"[:MAX_PAGE_CHARS]


class Refused(Exception):
    """Отзыв не принят: код отказа (ключ `feedback.err.*`), его параметры и статус ответа."""

    def __init__(self, code: str, status: int = 400, **params: object) -> None:
        super().__init__(code)
        self.code = code
        self.status = status
        self.params = params


def read_photos(files: list[FileStorage]) -> list[bytes]:
    """Кадры формы: пустые поля пропускаются; тип — по сигнатуре, размер и число — по пределам."""
    given = [f for f in files if f.filename]
    if len(given) > MAX_PHOTOS:
        raise Refused("too_many_photos", max=MAX_PHOTOS)
    ready: list[bytes] = []
    for file in given:
        data = file.stream.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise Refused("photo_big", 413, mb=_mb())
        if sniff_image(data) not in PHOTO_TYPES:
            raise Refused("photo_type")
        try:
            ready.append(make_preview(data))
        except StorageError as exc:
            raise Refused("photo_type") from exc
    return ready


def _answer(lang: str, *, ok: bool, key: str, status: int = 200, **params: object) -> Response:
    return make_response(jsonify(ok=ok, message=t(key, lang, **params)), status)


def _send(conf: Settings) -> Response:
    refuse_foreign_origin()
    lang = ui_lang.request_lang(conf.ui_lang)
    account = auth.current_account()
    if account is None:
        abort(403)
    request.max_content_length = MAX_UPLOAD_BYTES * MAX_PHOTOS + FORM_OVERHEAD_BYTES
    try:
        body = (request.form.get("text") or "").strip()
        page = page_of(request.form.get("page"))
        if not body:
            raise Refused("empty")
        if len(body) > MAX_TEXT:
            raise Refused("too_long", max=MAX_TEXT)
        photos = read_photos(request.files.getlist("photos"))
    except RequestEntityTooLarge:
        return _answer(lang, ok=False, key="feedback.err.photo_big", status=413, mb=_mb())
    except Refused as refusal:
        return _answer(
            lang,
            ok=False,
            key=f"feedback.err.{refusal.code}",
            status=refusal.status,
            **refusal.params,
        )
    space = canonical_tenant(account.tenant)
    g.journal_target = f"photos={len(photos)}"
    try:
        feedback_id = db_feedback.save(
            tenant=space,
            login=account.login,
            role=account.role,
            page=page,
            lang=lang,
            body=body,
            photos=photos,
        )
    except db_feedback.FeedbackRateLimited:
        return _answer(lang, ok=False, key="feedback.err.rate", status=429)
    except (DbError, psycopg.Error):
        logger.exception("Отзыв не сохранён")
        return _answer(lang, ok=False, key="feedback.err.failed", status=503)
    feedback_telegram.deliver(
        feedback_id,
        login=account.login,
        role=account.role,
        space=space,
        page=page,
        body=body,
        photos=len(photos),
    )
    return _answer(lang, ok=True, key="feedback.sent")


def show(conf_lang: str, *, notice: str = "", status: int = 200) -> Response:
    """Вкладка: список отзывов (новые сверху), отметки и — главному админу — чат Telegram."""
    if not guard.may(OPENING_ACTION):
        abort(404)
    ui_lang.request_lang(conf_lang)
    try:
        entries = db_feedback.entries()
        chat = db_feedback.chat_id() if guard.may(CHAT_ACTION) else None
        failed = False
    except (DbError, psycopg.Error):
        logger.exception("Отзывы не прочитаны")
        entries, chat, failed, status = (), None, True, 503
    return make_response(
        render_template(
            "administration/feedback.html",
            entries=entries,
            chat=chat,
            may_set_chat=guard.may(CHAT_ACTION),
            failed=failed,
            at=moment_text,
            notice=notice or request.args.get("notice", ""),
            **administration.nav(TAB),
        ),
        status,
    )


def _back(notice: str = "") -> Response:
    return make_response(redirect(administration.url(TAB, notice=notice), code=303))


def install(app: Flask, conf: Settings) -> None:
    """Маршруты кнопки и вкладки."""
    base = section("administration").path + "/feedback"

    @app.context_processor
    def _feedback_limits() -> dict[str, int]:
        return {
            "feedback_max_photos": MAX_PHOTOS,
            "feedback_max_bytes": MAX_UPLOAD_BYTES,
            "feedback_max_mb": _mb(),
            "feedback_max_text": MAX_TEXT,
        }

    @app.post(SEND_PATH, endpoint="feedback_send")
    def feedback_send() -> Response:
        return _send(conf)

    @app.get(base + "/photo/<photo_id>", endpoint="feedback_photo")
    def feedback_photo(photo_id: str) -> Response:
        if not guard.may(OPENING_ACTION):
            abort(404)
        try:
            found = db_feedback.photo(photo_id)
        except DbError:
            abort(404)
        except psycopg.Error:
            logger.exception("Кадр отзыва не прочитан")
            abort(503)
        if found is None:
            abort(404)
        content_type, data = found
        reply = make_response(data)
        reply.headers["Content-Type"] = content_type
        reply.headers["Cache-Control"] = "private, max-age=3600"
        reply.headers["X-Content-Type-Options"] = "nosniff"
        return reply

    @app.post(base + "/<feedback_id>/review", endpoint="feedback_review")
    @guard.action(OPENING_ACTION)
    def feedback_review(feedback_id: str) -> Response:
        refuse_foreign_origin()
        value = request.form.get("reviewed")
        if value not in {"0", "1"}:
            abort(400)
        account = auth.current_account()
        if account is None:
            abort(403)
        g.journal_target = f"feedback={feedback_id} reviewed={value}"
        try:
            found = db_feedback.mark_reviewed(feedback_id, reviewed=value == "1", by=account.login)
        except DbError:
            abort(404)
        except psycopg.Error:
            logger.exception("Отметка отзыва не сохранена")
            return show(conf.ui_lang, notice="review_failed", status=503)
        if not found:
            abort(404)
        return _back()

    @app.post(base + "/chat", endpoint="feedback_chat")
    @guard.action(CHAT_ACTION, hidden=True)
    def feedback_chat() -> Response:
        refuse_foreign_origin()
        account = auth.current_account()
        if account is None:
            abort(403)
        if request.form.get("disable") == "1":
            chat: str | None = None
        else:
            chat = (request.form.get("chat_id") or "").strip()
            if not _CHAT_RE.fullmatch(chat):
                return show(conf.ui_lang, notice="chat_bad", status=400)
        g.journal_target = "chat=off" if chat is None else "chat=set"
        try:
            db_feedback.set_chat_id(chat, by=account.login)
        except (DbError, psycopg.Error):
            logger.exception("Чат Telegram для отзывов не сохранён")
            return show(conf.ui_lang, notice="chat_failed", status=503)
        return _back("chat_off" if chat is None else "chat_saved")


def moment_text(moment: datetime) -> str:
    """Время отзыва для экрана: UTC, как в журнале."""
    return moment.astimezone(UTC).strftime("%Y-%m-%d %H:%M")
