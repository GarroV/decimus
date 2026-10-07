"""Мини-апп обхода в Telegram: что на точке ещё не осмотрено и что было здесь в прошлый раз (#418).

Экран отвечает на один вопрос аудитора на ходу: **«что мне ещё посмотреть на
этой точке?»** Два источника ответа:

* **зоны** — пройденные и нет. Зона засчитана, если в ней уже есть запись (раз
  записал, значит был) или аудитор отметил её осмотренной сам: чистая зона
  записей не оставляет, и отличить «осмотрел, всё в порядке» от «не дошёл»
  может только человек;
* **прошлая проверка точки** — что и где тогда записали. Повтор стоит вдвое
  (D191), поэтому прошлое нарушение — первое, на что смотреть.

Фиксация остаётся в чате (D047, `docs/07-roadmap.md`): мини-апп ничего не
пишет в проверку и не предлагает записей — «модель предлагает, фиксирует
человек» здесь соблюдается тем, что записи здесь не рождаются вовсе. Отметки
«зона осмотрена» и «исправлено» — личные пометки аудитора, на оценку не
влияют и хранятся в облачном хранилище Telegram у самого аудитора
(`walk.js`). Поэтому сервер только читает: состояние бота — тем же томом
`:ro`, что и у админки, историю — запросом `previous_findings`.

Два адреса: страница (`/tg/walk`, одинаковая для всех, данных в ней нет) и
данные (`/tg/walk/data`, POST с подписанной строкой Telegram в теле, — в
адресе она осела бы в журналах прокси). Учётка админки здесь не нужна: оба
адреса открыты в `auth.OPEN_ENDPOINTS`, а опознание — `walk_auth.chat_of`.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from flask import Flask, Response, jsonify, render_template, request

from src.db import queries
from src.db.errors import DbError
from src.db.models import PreviousFindings
from src.domain import get_state, list_items, list_zones
from src.domain.errors import DomainError
from src.domain.models import Inspection, Zone

from .errors import WebTextError
from .texts import UI_LANGS
from .texts_walk import WALK_TEXTS
from .walk_auth import (
    DATA_ENDPOINT,
    PAGE_ENDPOINT,
    WalkAccessError,
    WalkSettings,
    chat_of,
    load_walk_settings,
)

logger = logging.getLogger(__name__)

PAGE_PATH = "/tg/walk"
DATA_PATH = "/tg/walk/data"

#: Предел тела запроса данных: строка initData — сотни байт, не мегабайты.
MAX_INIT_DATA = 8192

#: Классы в начале формулировки пункта методики — «(D1, D2) …». В подсказке
#: они лишние: класс прошлой записи показан отдельно и он один.
_LEVEL_PREFIX = re.compile(r"^\(\s*D\d(?:\s*,\s*D\d)*\s*\)\s*")

#: Информационная запись — замер, а не нарушение (docs/02-domain.md).
INFO_LEVEL = "D0"

#: Чем отказывает чтение состояния. Не только `DomainError`: порча файла
#: приходит в `get_state` разными дверями (таблица в `src/bot/inspection.py`),
#: и экран обязан ответить человеческим текстом на любую.
STATE_FAILURES = (DomainError, OSError, UnicodeDecodeError, TypeError, ValueError)


@dataclass(frozen=True)
class PreviousOutcome:
    """Что удалось узнать о прошлой проверке: данные, «не было» или «база молчит»."""

    found: PreviousFindings | None
    unavailable: bool = False


def mark_key(inspection: Inspection) -> str:
    """Ключ личных пометок обхода в облачном хранилище Telegram.

    Свой у каждой проверки: новая проверка той же точки начинается с чистого
    листа, а не с прошлых галочек. Хранилище принимает только `[A-Za-z0-9_-]`
    до 128 знаков — поэтому отпечаток, а не название точки.
    """
    raw = f"{inspection.tenant}|{inspection.unit}|{inspection.date}|{inspection.kind}"
    return "walk_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _question_text(raw: str) -> str:
    return _LEVEL_PREFIX.sub("", raw).strip()


def build_walk(
    inspection: Inspection,
    zones: Iterable[Zone],
    previous: PreviousOutcome,
    *,
    lang: str,
    question: Callable[[str], str | None],
) -> dict[str, Any]:
    """Данные экрана обхода. Чистая функция: всё нужное приходит аргументами.

    Порядок зон — порядок методики: аудитор ходит в свободном порядке, и
    прыгающий список (неосмотренные наверх) терял бы глазом только что
    отмеченную зону. Зона прошлой записи, которой в методике этой проверки
    нет, не теряется — она добавляется в конец под своим кодом.
    """
    found = previous.found
    again = {(f.code, f.zone) for f in inspection.findings if f.level != INFO_LEVEL}
    by_zone: dict[str, dict[str, Any]] = {}
    for zone in zones:
        by_zone[zone.code] = {
            "code": zone.code,
            "title": zone.title(lang),
            "recorded": [],
            "previous": [],
        }

    def slot(code: str) -> dict[str, Any]:
        return by_zone.setdefault(
            code, {"code": code, "title": code, "recorded": [], "previous": []}
        )

    for finding in inspection.findings:
        slot(finding.zone)["recorded"].append(
            {"n": finding.n, "code": finding.code, "level": finding.level, "text": finding.text}
        )
    for old in found.findings if found else ():
        slot(old.zone)["previous"].append(
            {
                "code": old.code,
                "level": old.level,
                "text": old.text or _question_text(question(old.code) or old.code),
                "again": (old.code, old.zone) in again,
            }
        )
    return {
        "state": "active",
        "lang": lang,
        "unit": inspection.unit,
        "date": str(inspection.date),
        "key": mark_key(inspection),
        "previous": (
            {"date": found.date.isoformat(), "count": len(found.findings)} if found else None
        ),
        "previous_unavailable": previous.unavailable,
        "zones": list(by_zone.values()),
    }


def texts_for(lang: str) -> dict[str, str]:
    """Строки экрана на языке проверки — весь каталог обхода разом.

    Отдаются шаблонами («Осмотрено зон: {done} из {total}»): числа меняются
    от нажатия на телефоне, и подставляет их скрипт. Поэтому не `t()` — она
    требует параметры здесь, — а каталог напрямую, с той же проверкой языка.
    """
    if lang not in UI_LANGS:
        raise WebTextError(f"Язык интерфейса «{lang}» не заведён. Доступны: {', '.join(UI_LANGS)}")
    return {key: entry[lang] for key, entry in WALK_TEXTS.items()}


def _previous(inspection: Inspection) -> PreviousOutcome:
    """Прошлая проверка точки. База молчит — обход работает без подсказки."""
    try:
        return PreviousOutcome(
            queries.previous_findings(tenant=inspection.tenant, unit=inspection.unit)
        )
    except DbError:
        logger.warning("Обход: история точки «%s» недоступна", inspection.unit, exc_info=True)
        return PreviousOutcome(None, unavailable=True)


def _questions(chat_id: int, lang: str) -> Mapping[str, str]:
    return {item.code: item.question(lang) for item in list_items(chat_id=chat_id)}


def walk_payload(chat_id: int, *, fallback_lang: str) -> dict[str, Any]:
    """Всё, что отдаётся экрану по чату. Отказ чтения состояния — `STATE_FAILURES`."""
    inspection = get_state(chat_id)
    if inspection is None:
        lang = fallback_lang
        return {"state": "none", "lang": lang, "texts": texts_for(lang)}
    lang = inspection.ui_lang if inspection.ui_lang in UI_LANGS else fallback_lang
    questions = _questions(chat_id, lang)
    payload = build_walk(
        inspection,
        list_zones(chat_id=chat_id),
        _previous(inspection),
        lang=lang,
        question=questions.get,
    )
    return {**payload, "texts": texts_for(lang)}


def install(app: Flask, *, ui_lang: str, settings: WalkSettings | None = None) -> None:
    """Повесить страницу и данные обхода. Без настроек — адреса отвечают 404."""
    conf = settings or load_walk_settings()

    @app.get(PAGE_PATH, endpoint=PAGE_ENDPOINT)
    def walk_page() -> Response | tuple[str, int]:
        if not conf.enabled:
            return "", 404
        return Response(render_template("walk.html", lang=ui_lang))

    @app.post(DATA_PATH, endpoint=DATA_ENDPOINT)
    def walk_data() -> tuple[Response, int]:
        if not conf.enabled:
            return jsonify({"error": "disabled"}), 404
        init_data = request.get_data(as_text=True)[:MAX_INIT_DATA]
        try:
            chat_id = chat_of(init_data, conf)
        except WalkAccessError as exc:
            logger.info("Обход: отказ в опознании — %s", exc)
            return jsonify({"error": "unauthorized"}), 401
        try:
            return jsonify(walk_payload(chat_id, fallback_lang=ui_lang)), 200
        except STATE_FAILURES:
            logger.exception("Обход: состояние чата %s не прочиталось", chat_id)
            return jsonify({"error": "state", "texts": texts_for(ui_lang)}), 500
