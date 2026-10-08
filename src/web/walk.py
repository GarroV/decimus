"""Мини-апп обхода в Telegram: что на точке ещё не осмотрено и что было здесь в прошлый раз (#418).

Экран отвечает на один вопрос аудитора на ходу: **«что мне ещё посмотреть на
этой точке?»** Два источника ответа:

* **зоны** — пройденные и нет. Зона засчитана, если в ней уже есть запись (раз
  записал, значит был) или аудитор отметил её осмотренной сам: чистая зона
  записей не оставляет, и отличить «осмотрел, всё в порядке» от «не дошёл»
  может только человек;
* **прошлая проверка точки** — что и где тогда записали. Повтор стоит вдвое
  (D191), поэтому прошлое нарушение — первое, на что смотреть.

С D312 экран ещё и пишет: кадры, нарушение, замер, рекомендацию партнёру и
сведения о визите — через те же функции домена, что и бот, в ту же проверку.
Запись живёт в `walk_write.py`; здесь — чтение и опознание, общее для обоих.
Отметки «зона осмотрена» и «исправлено» по-прежнему личные пометки аудитора в
облачном хранилище Telegram (`walk.js`): на оценку они не влияют.

Два адреса: страница (`/tg/walk`, одинаковая для всех, данных в ней нет) и
данные (`/tg/walk/data`, POST с подписанной строкой Telegram в теле, — в
адресе она осела бы в журналах прокси). Учётка админки здесь не нужна: оба
адреса открыты в `auth.OPEN_ENDPOINTS`, а опознание — `walk_auth.chat_of`.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from flask import Flask, Response, jsonify, render_template, request

from src.db import bot_links, queries
from src.db.errors import DbError
from src.db.models import PreviousFindings
from src.domain import get_item, get_state, handed_over, is_upload_ref, list_items, list_zones
from src.domain.errors import DomainError
from src.domain.info_fields import FIELDS
from src.domain.models import NON_DEDUCTING, ChecklistItem, Inspection, Zone
from src.domain.walk_users import walk_open_to

from . import walk_write
from .errors import WebTextError
from .texts import UI_LANGS
from .texts_walk import WALK_TEXTS
from .walk_auth import (
    DATA_ENDPOINT,
    DATA_PATH,
    INIT_DATA_HEADER,
    PAGE_ENDPOINT,
    PAGE_PATH,
    WalkAccessError,
    WalkSettings,
    chat_of,
    load_walk_settings,
)

logger = logging.getLogger(__name__)

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


def _photo(ref: str) -> dict[str, Any]:
    """Кадр записи для экрана. Кадр из чата мини-апп показать не может — токена у
    веба на скачивание нет, — поэтому он помечается, а не прячется."""
    return {"ref": ref, "own": is_upload_ref(ref)}


def _catalogue(items: Iterable[ChecklistItem], lang: str) -> list[dict[str, Any]]:
    """Пункты, которые аудитор может записать: нарушения и замеры (D0).

    Служебные (`aggregate`, `info`) не предлагаются — правило фиксации 8.
    """
    return [
        {
            "code": item.code,
            "q": _question_text(item.question(lang)),
            "process": item.process(lang),
            "levels": list(item.levels),
            "zones": [] if not item.zones or item.zones == ["*"] else list(item.zones),
            "measure": item.levels == [INFO_LEVEL],
        }
        for item in items
        if item.kind == "violation"
    ]


def build_walk(
    inspection: Inspection,
    zones: Iterable[Zone],
    previous: PreviousOutcome,
    *,
    lang: str,
    question: Callable[[str], str | None],
    items: Iterable[ChecklistItem] = (),
    info: list[dict[str, Any]] | None = None,
    sealed: bool = False,
) -> dict[str, Any]:
    """Данные экрана обхода. Чистая функция: всё нужное приходит аргументами.

    Порядок зон — порядок методики: аудитор ходит в свободном порядке, и
    прыгающий список (неосмотренные наверх) терял бы глазом только что
    отмеченную зону. Зона прошлой записи, которой в методике этой проверки
    нет, не теряется — она добавляется в конец под своим кодом.
    """
    found = previous.found
    again = {(f.code, f.zone) for f in inspection.findings if f.level not in NON_DEDUCTING}
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
            {
                "n": finding.n,
                "code": finding.code,
                "level": finding.level,
                "text": finding.text,
                "comment": finding.comment,
                "repeat": finding.repeat,
                "unusual": finding.zone_unusual,
                "photos": [_photo(ref) for ref in finding.photos],
            }
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
        "sealed": sealed,
        "previous": (
            {"date": found.date.isoformat(), "count": len(found.findings)} if found else None
        ),
        "previous_unavailable": previous.unavailable,
        "zones": list(by_zone.values()),
        "items": _catalogue(items, lang),
        "info": info or [],
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


def revoked(chat_id: int) -> bool:
    """Сняли ли у человека доступ — привязку бота или учётку (`src/bot/access.py`, п.5).

    Проверка ЕГО проверки ещё лежит на диске, но бот его уже не пускает — и
    экран обхода не должен становиться обходным путём. Привязки не было
    никогда — не отказ: такой человек мог завести проверку только по старому
    списку бота, и раз она есть, бот его пустил. База молчит — `DbError`
    наверх: сверить снятие нечем, а отвечать «пускаю» вслепую нельзя.
    """
    положение = bot_links.standing(chat_id)
    return положение.binding is None and положение.ever_bound


def info_fields(inspection: Inspection, lang: str) -> list[dict[str, Any]]:
    """Сведения о визите: поля методики этой проверки с уже данными ответами.

    Поле, которого в методике нет, не показывается — состав задаёт управляющая
    компания (`src/bot/info.py`).
    """
    out = []
    for field in FIELDS:
        try:
            asked = get_item(field.code, chat_id=inspection.chat_id).question(lang)
        except DomainError:
            continue
        answer = inspection.info.get(field.code)
        out.append(
            {
                "code": field.code,
                "kind": field.kind,
                "q": _question_text(asked),
                "value": answer.text if answer else "",
            }
        )
    return out


def walk_payload(chat_id: int, *, fallback_lang: str) -> dict[str, Any]:
    """Всё, что отдаётся экрану по чату. Отказ чтения состояния — `STATE_FAILURES`."""
    inspection = get_state(chat_id)
    if inspection is None:
        lang = fallback_lang
        return {"state": "none", "lang": lang, "texts": texts_for(lang)}
    lang = inspection.ui_lang if inspection.ui_lang in UI_LANGS else fallback_lang
    items = list_items(chat_id=chat_id)
    questions = {item.code: item.question(lang) for item in items}
    payload = build_walk(
        inspection,
        list_zones(chat_id=chat_id),
        _previous(inspection),
        lang=lang,
        question=questions.get,
        items=items,
        info=info_fields(inspection, lang),
        sealed=handed_over(chat_id),
    )
    return {**payload, "texts": texts_for(lang)}


def init_data_of() -> str:
    """Подписанная строка Telegram: заголовок у запросов записи, тело у чтения."""
    header = request.headers.get(INIT_DATA_HEADER)
    if header is not None:
        return header[:MAX_INIT_DATA]
    return request.get_data(as_text=True)[:MAX_INIT_DATA]


def identify(
    conf: WalkSettings, ui_lang: str, *, header_only: bool = False
) -> int | tuple[Response, int]:
    """Чей это запрос — номер чата или готовый отказ.

    Одна дверь на чтение и запись: подпись, затем снятый доступ. Запись
    (`header_only`) берёт подпись только из заголовка. Снятие
    сверяется только при живом токене — на стенде без бота его не с чем
    сверить. База молчит — 503, а не «пускаю вслепую».
    """
    if not conf.enabled:
        return jsonify({"error": "disabled"}), 404
    if header_only and INIT_DATA_HEADER not in request.headers:
        # Запись принимает подпись только заголовком: тело (кадр до 10 МБ) не
        # читается, пока не известно, чьё оно (ревью 07.10.2026).
        return jsonify({"error": "unauthorized"}), 401
    try:
        chat_id = chat_of(init_data_of(), conf)
    except WalkAccessError as exc:
        logger.info("Обход: отказ в опознании — %s", exc)
        return jsonify({"error": "unauthorized"}), 401
    if not walk_open_to(conf.users, chat_id):
        # Пробный запуск на боевом боте: кнопки у человека нет, а адрес мог
        # прийти пересланным — страница пускает ровно тех же, что и кнопка.
        logger.info("Обход: чат %s не в круге тестеров — отказ", chat_id)
        return jsonify({"error": "closed", "texts": texts_for(ui_lang)}), 403
    try:
        if conf.bot_token is not None and revoked(chat_id):
            logger.info("Обход: доступ чата %s снят — отказ", chat_id)
            return jsonify({"error": "unauthorized"}), 401
    except DbError:
        logger.warning("Обход: снятие доступа не сверить — база молчит", exc_info=True)
        return jsonify({"error": "unavailable", "texts": texts_for(ui_lang)}), 503
    return chat_id


def payload_response(chat_id: int, ui_lang: str) -> tuple[Response, int]:
    """Свежие данные экрана — ответ на чтение и на каждую запись."""
    try:
        ответ = jsonify(walk_payload(chat_id, fallback_lang=ui_lang))
    except STATE_FAILURES:
        logger.exception("Обход: состояние чата %s не прочиталось", chat_id)
        return jsonify({"error": "state", "texts": texts_for(ui_lang)}), 500
    # Данные одного человека: ни прокси, ни WebView не должны их помнить.
    ответ.headers["Cache-Control"] = "no-store"
    return ответ, 200


def install(app: Flask, *, ui_lang: str, settings: WalkSettings | None = None) -> None:
    """Повесить страницу, данные и запись обхода. Без настроек — адреса отвечают 404."""
    conf = settings or load_walk_settings()

    @app.get(PAGE_PATH, endpoint=PAGE_ENDPOINT)
    def walk_page() -> Response | tuple[str, int]:
        if not conf.enabled:
            return "", 404
        return Response(render_template("walk.html", lang=ui_lang))

    @app.post(DATA_PATH, endpoint=DATA_ENDPOINT)
    def walk_data() -> tuple[Response, int]:
        who = identify(conf, ui_lang)
        if not isinstance(who, int):
            return who
        return payload_response(who, ui_lang)

    walk_write.install(app, conf=conf, ui_lang=ui_lang, identify=identify, respond=payload_response)
