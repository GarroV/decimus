"""Мини-апп обхода: перевод свободного текста на другой язык (D394) — `POST /tg/walk/translate`.

Аудитор пишет «что видно», рекомендацию партнёру, общую заметку и сведения о
визите на языке чек-листа, а читать их может человек на другом. Кнопка у поля просит
перевод, модель его предлагает (`recognize.translate`), аудитор видит результат
в самом поле до сохранения и может поправить — в отчёт идёт только то, что он
сохранил обычной записью (модель предлагает, фиксирует человек). Адрес сам
ничего не пишет.

Язык перевода — другой язык платформы, не язык чек-листа проверки
(`translate_target`): язык отчёта до конца обхода равен языку чек-листа (D415),
и переводить на него бессмысленно. Это и не язык интерфейса: аудитор может
работать в русском интерфейсе над английским чек-листом. Опознание то же, что у
записи: подпись Telegram в заголовке. Сданная проверка не мешает: адрес ничего
не меняет, а проверка нужна лишь затем, чтобы знать язык отчёта.

Ограничения частоты нет (D394): один перевод на чат за раз, как у поиска пункта;
квота на число переводов — отдельное решение, если понадобится.
"""

from __future__ import annotations

import logging
import threading

from flask import Flask, Response, jsonify, request

from src.domain import get_state
from src.domain.models import TEXT_LANGS, Inspection
from src.recognize.errors import RecognizeError
from src.recognize.translate import translate_text

from .texts_walk import WALK_TEXTS
from .walk_auth import TRANSLATE_ENDPOINT, TRANSLATE_PATH, WalkSettings
from .walk_write import MAX_TEXT, Identify, WalkRefused, _text

logger = logging.getLogger(__name__)


def translate_target(inspection: Inspection) -> str | None:
    """Язык перевода: первый язык платформы, не равный языку чек-листа проверки.

    Свободный текст пишется на языке чек-листа и сам не переводится (D416);
    кнопка у поля даёт перевод на ДРУГОЙ язык платформы. `None` — другого языка
    нет (платформа одноязычна), кнопки не будет.
    """
    return next((code for code in TEXT_LANGS if code != inspection.speech_lang), None)


def install(app: Flask, *, conf: WalkSettings, ui_lang: str, identify: Identify) -> None:
    """Повесить перевод. Опознание — то же, что у записи."""
    busy: set[int] = set()
    guard = threading.Lock()

    def refused(key: str, lang: str, status: int = 422) -> tuple[Response, int]:
        entry = WALK_TEXTS[key]
        answer = jsonify({"error": "refused", "message": entry.get(lang) or entry[ui_lang]})
        answer.headers["Cache-Control"] = "no-store"
        return answer, status

    @app.post(TRANSLATE_PATH, endpoint=TRANSLATE_ENDPOINT)
    def walk_translate() -> tuple[Response, int]:
        who = identify(conf, ui_lang, header_only=True)
        if not isinstance(who, int):
            return who
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return refused("walk.err.bad_request", ui_lang, 400)
        inspection = get_state(who)
        if inspection is None:
            return refused("walk.none.title", ui_lang, 409)
        lang = inspection.ui_lang
        try:
            text = _text(body, "text", required=True)
        except WalkRefused as exc:
            return refused(str(exc), lang)
        with guard:
            if who in busy:
                return refused("walk.err.translate_busy", lang, 429)
            busy.add(who)
        target = translate_target(inspection)
        if target is None:
            return refused("walk.err.bad_request", lang, 409)
        try:
            translated = translate_text(text, lang=target)
        except RecognizeError as exc:
            # Модель недоступна — поле остаётся как было, аудитор видит причину
            # в экране. Сырой текст исключения — в журнал, не аудитору.
            logger.warning("Обход: перевод для чата %s не удался: %s", who, exc)
            return refused("walk.err.translate", lang, 503)
        finally:
            with guard:
                busy.discard(who)
        if len(translated) > MAX_TEXT:
            return refused("walk.err.translate_long", lang)
        logger.info("Обход: чат %s — перевод %s знаков на %s", who, len(text), target)
        answer = jsonify({"text": translated, "lang": target})
        answer.headers["Cache-Control"] = "no-store"
        return answer, 200
