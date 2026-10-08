"""Запись из мини-аппа обхода (D312): кадр, нарушение, замер, рекомендация, сведения о визите.

Мини-апп пишет в ту же проверку, что и бот, и теми же функциями домена:
второй дороги в `inspection.json` нет, а правила методики — допустимый класс,
пара «пункт + зона», зона из списка пункта — проверяет движок один раз для
обеих поверхностей. Отсюда же ответы: отказ движка показывается аудитору его
словами (как и в чате), а успех возвращает свежие данные экрана целиком —
экран не собирает состояние по кусочкам и не расходится с проверкой.

Что здесь решено:

* **Кадр сначала, запись потом.** Кадр уходит на сервер сразу после снимка
  (`/tg/walk/photo`) и возвращается ссылкой, а запись ссылается на уже
  лежащие кадры. Так «Сохранить» не ждёт загрузки на плохой связи, а запись
  рождается сразу с кадрами одним вызовом движка (D078: без кадра записи нет).
* **Зону называет человек** — он выбрал её на экране, поэтому зона вне списка
  пункта принимается с пометкой (`zone_by_person`, D206), как в чате.
* **Источник — слова аудитора** (`SOURCE_COMMENT`, D044): формулировку он
  написал сам, модель в мини-аппе не участвует.
* **Повтор ставит человек** (D191): флаг приходит только с его нажатия.
* **Сданная проверка не правится** (D080): тот же признак, что у бота
  (`domain.handed_over`). Ранняя проверка отвечает быстро и до чтения тела,
  а решающая — под замком заметок вместе с самой записью (`domain.while_open`):
  сдача, пришедшая между ними, получает отказ, а не запись после себя.
* **Кадр показывается только хозяину**: ссылка должна висеть на записи или
  сведении его проверки.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from datetime import datetime
from typing import Any

from flask import Flask, Response, jsonify, request

from src.bot.phrases import learn
from src.domain import (
    SOURCE_COMMENT,
    HandedOverError,
    add_finding,
    attach_photo,
    check_environment,
    detach_photo,
    drop_finding,
    edit_finding,
    get_item,
    get_state,
    handed_over,
    is_upload_ref,
    save_upload,
    set_info,
    upload_file,
    while_open,
)
from src.domain.errors import DomainError, EngineError, ValidationError
from src.domain.info_fields import FIELDS, KIND_DATE, KIND_TEXT, KIND_YES_NO
from src.domain.models import Inspection, Suggestion
from src.domain.uploads import MAX_UPLOAD_BYTES
from src.recognize.models import UNKNOWN_ZONE

from .texts_walk import WALK_TEXTS
from .walk_auth import (
    FINDING_ENDPOINT,
    FINDING_PATH,
    INFO_ENDPOINT,
    INFO_PATH,
    PHOTO_ENDPOINT,
    PHOTO_PATH,
    PHOTO_VIEW_ENDPOINT,
    PHOTO_VIEW_PATH,
    WalkSettings,
)

logger = logging.getLogger(__name__)

#: Предел формулировки и рекомендации. Абзац, а не страница: длиннее аудитор
#: на ходу не пишет, а отчёт партнёру читается построчно.
MAX_TEXT = 1000

#: Классы, у которых повтор удваивает вычет: D0 — замер, D3 сжигает зону целиком.
REPEAT_LEVELS = ("D1", "D2")

#: Номер записи, код пункта, класс, зона — короткие слова, не тексты.
_CODE = re.compile(r"^[A-Za-z0-9_]{1,32}$")
_LEVEL = re.compile(r"^(?:D[0-3]|R)$")

#: Рекомендация без нарушения (D201) и общая заметка (D314): кадр по желанию,
#: текст обязателен — подставлять формулировку пункта на месте совета нельзя.
ADVICE_LEVEL = "R"

#: Классы в начале формулировки пункта — «(D1, D2) …» (см. `walk._LEVEL_PREFIX`).
_LEVEL_PREFIX = re.compile(r"^\(\s*D\d(?:\s*,\s*D\d)*\s*\)\s*")

#: Значения дат из полей телефона: дата и дата со временем.
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")

#: Управляющие символы в тексте: NUL роняет запуск движка, остальные партнёру
#: в отчёте не нужны. Перевод строки и табуляция — законные.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]|[\ud800-\udfff]")

Identify = Callable[..., "int | tuple[Response, int]"]
Respond = Callable[[int, str], "tuple[Response, int]"]


class WalkRefused(Exception):
    """Запись не принята. Аргумент — ключ текста для аудитора в `WALK_TEXTS`."""


def _text(body: dict[str, Any], name: str, *, required: bool = False) -> str:
    value = body.get(name, "")
    if not isinstance(value, str):
        raise WalkRefused("walk.err.bad_request")
    clean = value.strip()
    if _CONTROL.search(clean):
        raise WalkRefused("walk.err.bad_request")
    if len(clean) > MAX_TEXT:
        raise WalkRefused("walk.err.too_long")
    if required and not clean:
        raise WalkRefused("walk.err.empty_text")
    return clean


def _code(body: dict[str, Any], name: str, pattern: re.Pattern[str] = _CODE) -> str:
    value = body.get(name)
    if not isinstance(value, str) or not pattern.match(value):
        raise WalkRefused("walk.err.bad_request")
    return value


def _number(body: dict[str, Any]) -> int:
    value = body.get("n")
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise WalkRefused("walk.err.bad_request")
    return value


def _refs(value: Any) -> list[str]:
    """Кадры, к которым ссылается запрос: только снятые в мини-аппе и на месте."""
    if not isinstance(value, list) or not value:
        raise WalkRefused("walk.err.photo_required")
    settings = check_environment()
    refs: list[str] = []
    for ref in value:
        if not isinstance(ref, str) or not is_upload_ref(ref):
            raise WalkRefused("walk.err.bad_request")
        if upload_file(ref, settings) is None:
            raise WalkRefused("walk.err.photo_lost")
        if ref not in refs:
            refs.append(ref)
    return refs


def _ref(body: dict[str, Any]) -> str:
    return _refs([body.get("ref")])[0]


def _default_text(chat_id: int, code: str, lang: str) -> str:
    """Формулировка, если аудитор не написал своей: вопрос пункта без классов (Q045)."""
    return _LEVEL_PREFIX.sub("", get_item(code, chat_id=chat_id).question(lang)).strip()


def _suggested(value: Any) -> tuple[Suggestion | None, bool]:
    """Что предложила система до решения аудитора (T164, D330) и учиться ли на нём.

    Так же, как у бота: предложение модели пишется с уверенностью, быстрого
    пути — без неё (её никто не считал), выученной фразы — не пишется вовсе.
    Учится карта синонимов (D119) только на предложении модели: быстрый путь и
    выученная фраза и так находят пункт без неё.

    Кривая тройка — не отказ записи, а «предложения не было»: запись аудитора
    важнее статистики модели.
    """
    if not isinstance(value, dict) or value.get("via") not in ("fast", "model"):
        return None, False
    confidence = value.get("confidence")
    model = value.get("via") == "model"
    try:
        return Suggestion(
            code=_code(value, "code"),
            level=_code(value, "level", _LEVEL),
            zone=_code(value, "zone") if value.get("zone") else UNKNOWN_ZONE,
            confidence=float(confidence)
            if model and isinstance(confidence, (int, float)) and 0 <= confidence <= 1
            else None,
        ), model
    except WalkRefused:
        return None, model


def _add(chat_id: int, inspection: Inspection, body: dict[str, Any]) -> None:
    code = _code(body, "code")
    level = _code(body, "level", _LEVEL)
    zone = _code(body, "zone")
    advice = level == ADVICE_LEVEL
    photos = [] if advice and not body.get("photos") else _refs(body.get("photos"))
    if advice:
        text = _text(body, "text", required=True)
    else:
        text = _text(body, "text") or _default_text(chat_id, code, inspection.report_lang)
    words = _text(body, "words")
    suggested, learns = _suggested(body.get("suggested"))
    add_finding(
        chat_id,
        code=code,
        level=level,
        zone=zone,
        text=text,
        comment=_text(body, "comment"),
        source=SOURCE_COMMENT,
        zone_by_person=True,
        # Замер (D0) и D3 повтором не удваиваются (docs/02-domain.md).
        repeat=body.get("repeat") is True and level in REPEAT_LEVELS,
        photos=photos,
        words=words,
        suggested=suggested,
    )
    if words and learns:
        # Запомнить сказанное синонимом выбранного пункта (D119) — как бот после
        # записи по предложению: в следующий раз эти слова найдут его без модели.
        learn(words, item_code=code, lang=inspection.speech_lang, chat_id=chat_id)


def _edit(chat_id: int, inspection: Inspection, body: dict[str, Any]) -> None:
    n = _number(body)
    current = inspection.finding(n)
    if current is None:
        raise WalkRefused("walk.err.bad_request")
    fields: dict[str, str] = {}
    if "text" in body:
        fields["text"] = _text(body, "text", required=True)
    if "comment" in body:
        fields["comment"] = _text(body, "comment")
    if "code" in body:
        fields["code"] = _code(body, "code")
    if "level" in body:
        fields["level"] = _code(body, "level", _LEVEL)
    if "zone" in body:
        fields["zone"] = _code(body, "zone")
    repeat = body.get("repeat")
    level = fields.get("level", current.level)
    # Повтор удваивает только D1 и D2: у замера и D3 он выглядел бы в отчёте
    # пометкой о цене, которой нет. Поставить такой — отказ; смена класса на
    # такой снимает прежний явно.
    if repeat is True and level not in REPEAT_LEVELS:
        raise WalkRefused("walk.err.repeat_level")
    if repeat is None and current.repeat and level not in REPEAT_LEVELS:
        repeat = False
    edit_finding(
        chat_id,
        n,
        zone_by_person="zone" in fields,
        repeat=repeat if isinstance(repeat, bool) else None,
        **fields,
    )


def _finding_op(chat_id: int, inspection: Inspection, body: dict[str, Any]) -> None:
    op = body.get("op")
    if op == "add":
        _add(chat_id, inspection, body)
    elif op == "edit":
        _edit(chat_id, inspection, body)
    elif op == "drop":
        drop_finding(chat_id, _number(body))
    elif op == "attach":
        attach_photo(chat_id, _number(body), _ref(body))
    elif op == "detach":
        ref = body.get("ref")
        if not isinstance(ref, str):
            raise WalkRefused("walk.err.bad_request")
        detach_photo(chat_id, _number(body), ref)
    else:
        raise WalkRefused("walk.err.bad_request")


def _info_value(kind: str, raw: Any, report_lang: str) -> str:
    """Ответ поля словами отчёта: «Да» на языке партнёра, дата — как печатает движок."""
    if not isinstance(raw, str) or not raw.strip():
        raise WalkRefused("walk.err.empty_answer")
    value = raw.strip()
    if kind == KIND_YES_NO:
        if value not in ("yes", "no"):
            raise WalkRefused("walk.err.bad_request")
        entry = WALK_TEXTS[f"walk.info.{value}"]
        return entry.get(report_lang, entry["en"])
    if kind == KIND_DATE:
        if _DATETIME.match(value):
            return datetime.strptime(value, "%Y-%m-%dT%H:%M").strftime("%d.%m.%Y %H:%M")
        if _DATE.match(value):
            return datetime.strptime(value, "%Y-%m-%d").strftime("%d.%m.%Y")
        raise WalkRefused("walk.err.bad_date")
    if kind == KIND_TEXT:
        if len(value) > MAX_TEXT:
            raise WalkRefused("walk.err.too_long")
        return value
    raise WalkRefused("walk.err.bad_request")


def _info_op(chat_id: int, inspection: Inspection, body: dict[str, Any]) -> None:
    code = _code(body, "code")
    field = next((f for f in FIELDS if f.code == code), None)
    if field is None:
        raise WalkRefused("walk.err.bad_request")
    set_info(chat_id, code, _info_value(field.kind, body.get("value"), inspection.report_lang))


def _owns(inspection: Inspection, ref: str) -> bool:
    if any(ref in f.photos for f in inspection.findings):
        return True
    return any(ref in answer.photos for answer in inspection.info.values())


def install(
    app: Flask, *, conf: WalkSettings, ui_lang: str, identify: Identify, respond: Respond
) -> None:
    """Повесить адреса записи. Опознание и ответ данными — те же, что у чтения."""

    def refused(text: str, status: int = 422) -> tuple[Response, int]:
        return jsonify({"error": "refused", "message": text}), status

    def said(key: str, lang: str) -> str:
        entry = WALK_TEXTS[key]
        return entry.get(lang) or entry[ui_lang]

    def writable(chat_id: int) -> Inspection | tuple[Response, int]:
        inspection = get_state(chat_id)
        if inspection is None:
            return refused(said("walk.none.title", ui_lang), 409)
        if handed_over(chat_id):
            return refused(said("walk.sealed", inspection.ui_lang), 409)
        return inspection

    def write(op: Callable[[int, Inspection, dict[str, Any]], None]) -> tuple[Response, int]:
        who = identify(conf, ui_lang, header_only=True)
        if not isinstance(who, int):
            return who
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return refused(said("walk.err.bad_request", ui_lang), 400)
        lang = ui_lang
        try:
            inspection = writable(who)
            if not isinstance(inspection, Inspection):
                return inspection
            lang = inspection.ui_lang
            # Решающая проверка сдачи — под замком заметок вместе с записью:
            # ранняя выше могла пройти за миг до того, как бот отдал отчёт.
            with while_open(who):
                op(who, inspection, body)
        except HandedOverError:
            logger.info("Обход: чат %s сдал проверку во время записи — отказ", who)
            return refused(said("walk.sealed", lang), 409)
        except WalkRefused as exc:
            return refused(said(str(exc), lang))
        except (ValidationError, EngineError) as exc:
            # Отказ движка или домена — его словами, как в чате: аудитор видит,
            # что именно не так (пара занята, класс не разрешён для пункта).
            logger.info("Обход: запись чата %s отклонена — %s", who, type(exc).__name__)
            return refused(str(exc))
        except DomainError:
            # Прочее (битые заметки, занятый замок) — внутренности сервера:
            # пути и подробности в журнал, аудитору — общее «не вышло».
            logger.exception("Обход: запись чата %s не удалась", who)
            return refused(said("walk.err.server", lang), 500)
        return respond(who, ui_lang)

    @app.post(PHOTO_PATH, endpoint=PHOTO_ENDPOINT)
    def walk_photo() -> tuple[Response, int]:
        request.max_content_length = MAX_UPLOAD_BYTES
        who = identify(conf, ui_lang, header_only=True)
        if not isinstance(who, int):
            return who
        try:
            inspection = writable(who)
            if not isinstance(inspection, Inspection):
                return inspection
            ref = save_upload(request.get_data(cache=False), check_environment())
        except DomainError as exc:
            logger.info("Обход: кадр чата %s не принят — %s", who, exc)
            return refused(said("walk.err.photo_bad", ui_lang))
        logger.info("Обход: чат %s прислал кадр %s", who, ref)
        return jsonify({"ref": ref}), 201

    @app.post(PHOTO_VIEW_PATH, endpoint=PHOTO_VIEW_ENDPOINT)
    def walk_photo_view() -> Response | tuple[Response, int]:
        who = identify(conf, ui_lang, header_only=True)
        if not isinstance(who, int):
            return who
        body = request.get_json(silent=True)
        ref = body.get("ref") if isinstance(body, dict) else None
        if not isinstance(ref, str) or not is_upload_ref(ref):
            return refused(said("walk.err.bad_request", ui_lang), 400)
        inspection = get_state(who)
        if inspection is None or not _owns(inspection, ref):
            return jsonify({"error": "not_found"}), 404
        path = upload_file(ref, check_environment())
        if path is None:
            return jsonify({"error": "not_found"}), 404
        ответ = Response(path.read_bytes(), mimetype="image/jpeg")
        ответ.headers["Cache-Control"] = "no-store"
        return ответ

    @app.post(FINDING_PATH, endpoint=FINDING_ENDPOINT)
    def walk_finding() -> tuple[Response, int]:
        return write(_finding_op)

    @app.post(INFO_PATH, endpoint=INFO_ENDPOINT)
    def walk_info() -> tuple[Response, int]:
        return write(_info_op)
