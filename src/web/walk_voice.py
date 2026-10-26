"""Мини-апп обхода: голос → текст в поле (D652) — `POST /tg/walk/transcribe`.

Рядом с полями «Что не так» и комментария — кнопка микрофона. Телефон пишет речь,
адрес расшифровывает её той же функцией, что голосовые в чате (`recognize.transcribe`),
и отдаёт текст; клиент кладёт его в поле, где аудитор видит и правит его до
сохранения. Адрес сам ничего не пишет в проверку: в отчёт идёт только то, что
аудитор сохранил обычной записью (модель предлагает, фиксирует человек).

Тело запроса — сама запись (любой формат, что отдаёт `MediaRecorder`: WebM/Opus на
Android, MP4 на iOS; ffmpeg внутри `transcribe` разбирает любой). Предел размера —
`MAX_VOICE_BYTES`, предел длительности держит сама расшифровка. Язык речи — язык
чек-листа проверки (`speech_lang`). Опознание то же, что у записи: подпись Telegram
в заголовке. Одна расшифровка на чат за раз — как у перевода и поиска пункта.
"""

from __future__ import annotations

import logging
import threading

from flask import Flask, Response, jsonify, request
from werkzeug.exceptions import RequestEntityTooLarge

from src.bot import journal
from src.bot.usage import chat_usage
from src.db.busy_lock import WALK_VOICE, try_hold
from src.domain import get_state
from src.domain.log_ids import log_id
from src.domain.model_usage import usage_scope
from src.recognize.errors import RecognizeError
from src.recognize.transcribe import transcribe

from .server_limits import walk_model_gate
from .texts_walk import WALK_TEXTS
from .walk_auth import MAX_VOICE_BYTES, VOICE_ENDPOINT, VOICE_PATH, WalkSettings
from .walk_write import MAX_TEXT, Identify

logger = logging.getLogger(__name__)


def install(app: Flask, *, conf: WalkSettings, ui_lang: str, identify: Identify) -> None:
    """Повесить расшифровку голоса. Опознание — то же, что у записи.

    Одна расшифровка на чат за раз — на все процессы: внутри процесса держит набор,
    между процессами — замок в базе (`src/db/busy_lock.py`, F-110).
    """
    busy: set[int] = set()
    guard = threading.Lock()
    gate = walk_model_gate()

    def refused(key: str, lang: str, status: int = 422) -> tuple[Response, int]:
        entry = WALK_TEXTS[key]
        answer = jsonify({"error": "refused", "message": entry.get(lang) or entry[ui_lang]})
        answer.headers["Cache-Control"] = "no-store"
        return answer, status

    def read_audio() -> bytes | None:
        """Тело запроса; `None` — больше предела."""
        if (request.content_length or 0) > MAX_VOICE_BYTES:
            return None
        try:
            return request.get_data(cache=False)
        except RequestEntityTooLarge:
            return None

    @app.post(VOICE_PATH, endpoint=VOICE_ENDPOINT)
    def walk_voice() -> tuple[Response, int]:
        request.max_content_length = MAX_VOICE_BYTES
        who = identify(conf, ui_lang, header_only=True)
        if not isinstance(who, int):
            return who
        inspection = get_state(who)
        if inspection is None:
            return refused("walk.none.title", ui_lang, 409)
        lang = inspection.ui_lang
        audio = read_audio()
        if audio is None:
            return refused("walk.err.voice_big", lang, 413)
        if not audio:
            return refused("walk.err.bad_request", lang, 400)
        with guard:
            if who in busy:
                return refused("walk.err.voice_busy", lang, 429)
            busy.add(who)
        hold = try_hold(WALK_VOICE, str(who))
        if not hold.acquired:
            with guard:
                busy.discard(who)
            return refused("walk.err.voice_busy", lang, 429)
        if not gate.try_enter():
            hold.release()
            with guard:
                busy.discard(who)
            return refused("walk.err.overloaded", lang, 503)
        try:
            with usage_scope(telegram_id=who, tenant=inspection.tenant), chat_usage(who):
                text = transcribe(audio, lang=inspection.speech_lang)
        except RecognizeError as exc:
            # Нет ключа, ffmpeg не разобрал, пустая речь — поле остаётся как было, аудитор
            # видит просьбу сказать ещё раз. Сырой текст исключения — в журнал, не аудитору.
            logger.warning("Обход: расшифровка для чата %s не удалась: %s", log_id(who), exc)
            return refused("walk.err.voice", lang, 503)
        finally:
            gate.leave()
            hold.release()
            with guard:
                busy.discard(who)
        text = text[:MAX_TEXT]
        journal.note(who, "walk_voice", lang=inspection.speech_lang, bytes=len(audio), text=text)
        logger.info("Обход: чат %s — расшифровка голоса, %s знаков", log_id(who), len(text))
        answer = jsonify({"text": text})
        answer.headers["Cache-Control"] = "no-store"
        return answer, 200
