"""Мини-апп обхода: пакетный подбор нарушений — `POST /tg/walk/batch` (прототип).

Аудитор вкидывает несколько кадров, к каждому пишет слова; система по каждой
карточке параллельно проходит тот же путь, что одиночный ввод: пункт по кадрам и
словам (`walk_suggest`: быстрый путь → выученная фраза → модель), зона из слов,
класс по полным критериям выбранного пункта (`walk_level`). Ничего не пишет: ответ
— по карточке на карточку, а запись остаётся обычным `POST /tg/walk/finding`
(модель предлагает, фиксирует человек), поэтому журнал шагов и пополнение словаря
работают как у одиночной записи.

Карточка может нести решения человека: `code` — пункт выбран руками («Другой
пункт»; поиск по кадрам пропускается, класс считается заново) и `zone` — зона
выбрана руками. Сбой одной карточки не роняет остальные: она возвращается со
своим статусом и текстом.

Повтор здесь не решается: что было в прошлый раз, клиент берёт из данных экрана
(`zones[].previous`), а «то же самое?» спрашивает человека.
"""

from __future__ import annotations

import contextvars
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from flask import Flask, Response, jsonify, request
from werkzeug.exceptions import RequestEntityTooLarge

from src.bot import journal
from src.bot.propose import propose
from src.bot.zones import allowed_zones, zone_from_words
from src.db.busy_lock import WALK_SUGGEST, try_hold
from src.domain import get_item, get_state, handed_over
from src.domain.criteria import CriteriaUnavailable
from src.domain.errors import DomainError, ValidationError
from src.domain.log_ids import log_id
from src.domain.model_usage import KIND_SUGGEST, usage_scope
from src.domain.models import Inspection
from src.recognize.errors import RecognizeError
from src.recognize.selected_level import (
    MissingFacts,
    evaluate_selected_level,
    prepare_selected_level,
)

from .server_limits import SlowGate
from .texts_walk import WALK_TEXTS
from .walk_auth import BATCH_ENDPOINT, BATCH_PATH, WalkSettings
from .walk_level import _images
from .walk_model_session import ModelSession
from .walk_suggest import MAX_SUGGEST_PHOTOS, Ask, _frames, _usual_zone, answer
from .walk_unseen import INFO_LEVEL
from .walk_write import Identify, WalkRefused, _code, _refs, _text
from .walk_zone import resolve_item_zone

logger = logging.getLogger(__name__)

#: Карточек в одном вызове. Каждая — до двух платных вызовов модели.
MAX_CARDS = 12
#: Предел тела: карточка — до 1000 знаков слов (до 4 байт на знак) и до 20 ссылок на кадры
#: (по ~80 байт) — около 6 КБ; на 12 карточек с запасом.
MAX_BATCH_BODY_BYTES = 96 * 1024
BUSY = "busy"
#: Параллельных карточек внутри вызова (как у `mcp.import_match.WORKERS`).
WORKERS = 8
#: Предложений пункта на карточку: первое — выбор системы, остальные — запасные.
MAX_CANDIDATES = 3

#: Статусы карточки: `found` — пункт и класс есть, остальное — решает человек.
FOUND = "found"
NO_ITEM = "no_item"
NEED_ZONE = "need_zone"
MEASURE = "measure"
NO_FACTS = "no_facts"
UNAVAILABLE = "unavailable"


def _zone_of(
    code: str, *, words: str, human: str | None, hint: str | None, who: int, tenant: str | None
) -> tuple[str | None, str, tuple[str, ...]]:
    """Зона записи: человек → слова → пункт/модель/экран → зона экрана. Источник — для подписи."""
    options = allowed_zones(code, chat_id=who)
    if human:
        return human, "human", options
    found = resolve_item_zone(
        options,
        spoken=zone_from_words(words, chat_id=who),
        model=None,
        hint=hint,
        usual=lambda: _usual_zone(tenant, code),
    )
    if found.zone:
        return found.zone, found.source, found.options
    # Зона не названа и пункт бывает в нескольких: берём зону экрана, карточка так и подпишет.
    return hint, "screen" if hint else "ask", found.options


def _level(
    who: int,
    inspection: Inspection,
    *,
    code: str,
    zone: str,
    words: str,
    refs: list[str],
    card: str,
) -> dict[str, Any]:
    """Класс выбранного пункта по полным критериям — тот же вызов, что у `walk_level`."""
    images = _images(refs)
    prepared = prepare_selected_level(
        who,
        code=code,
        zone=zone,
        words=words,
        photo_refs=refs,
        photos=images,
        selection_revision=f"batch-{card}"[:64],
        clarifications=[],
    )
    with usage_scope(
        kind=KIND_SUGGEST,
        telegram_id=who,
        tenant=inspection.tenant,
        inspection_ref=prepared.item.run_id,
        inspection_label=" · ".join((inspection.unit, inspection.date)),
    ):
        return evaluate_selected_level(prepared)


def _candidates_of(
    who: int, inspection: Inspection, *, words: str, refs: list[str], hint: str | None
) -> tuple[list[dict[str, Any]], str]:
    """Пункты по кадрам и словам — тем же путём, что одиночный подбор; и чем найдены."""
    frames = _frames(refs)
    with usage_scope(kind=KIND_SUGGEST, telegram_id=who, tenant=inspection.tenant):
        offer = propose(
            words,
            frames,
            zone=hint,
            chat_id=who,
            ui_lang=inspection.ui_lang,
            speech_lang=inspection.speech_lang,
            report_lang=inspection.report_lang,
        )
    ask = Ask(
        chat_id=who,
        spoken=zone_from_words(words, chat_id=who),
        hint=hint,
        tenant=inspection.tenant,
        frame_refs=tuple(refs),
    )
    reply = answer(offer, ask)
    journal.note(
        who,
        "walk_batch_card",
        via=offer.via,
        words=words,
        zone=hint,
        frames=len(frames),
        candidates=journal.candidates(offer.candidates),
    )
    return list(reply["candidates"])[:MAX_CANDIDATES], offer.via


def _one(who: int, inspection: Inspection, raw: dict[str, Any], hint: str | None) -> dict[str, Any]:
    """Одна карточка: пункт → зона → класс. Отказ карточки — её статус, а не отказ вызова."""
    card = _text(raw, "id")
    out: dict[str, Any] = {"id": card, "status": UNAVAILABLE, "candidates": []}
    words = _text(raw, "words")
    photos = raw.get("photos")
    # Предел — до разбора ссылок: лишние кадры не читаются с диска и не уходят в модель.
    refs = _refs(
        photos[:MAX_SUGGEST_PHOTOS] if isinstance(photos, list) else photos, who, inspection
    )
    pinned = _code(raw, "code") if raw.get("code") else None
    human_zone = _code(raw, "zone") if raw.get("zone") else None
    candidates: list[dict[str, Any]] = []
    if pinned is None:
        candidates, out["via"] = _candidates_of(who, inspection, words=words, refs=refs, hint=hint)
        out["candidates"] = candidates
        if not candidates:
            out["status"] = NO_ITEM
            return out
    code = pinned or candidates[0]["code"]
    levels = get_item(code, chat_id=who).levels
    out["code"] = code
    out["item_levels"] = list(levels)
    out["wording"] = candidates[0]["wording"] if candidates else None
    out["suggested"] = (
        {k: candidates[0][k] for k in ("code", "level", "zone", "confidence")}
        if candidates
        else None
    )
    zone, source, options = _zone_of(
        code, words=words, human=human_zone, hint=hint, who=who, tenant=inspection.tenant
    )
    out.update(zone=zone, zone_source=source, zone_options=list(options))
    if list(levels) == [INFO_LEVEL]:
        out["status"] = MEASURE
        return out
    if zone is None:
        out["status"] = NEED_ZONE
        return out
    try:
        result = _level(who, inspection, code=code, zone=zone, words=words, refs=refs, card=card)
    except MissingFacts:
        out["status"] = NO_FACTS
        return out
    out["status"] = FOUND
    out["class"] = {
        key: result.get(key)
        for key in ("status", "level", "provisional_level", "need_fact", "reason")
    }
    return out


def _guarded(
    who: int, inspection: Inspection, raw: Any, hint: str | None, lang: str, gate: SlowGate
) -> dict[str, Any]:
    ident = raw.get("id") if isinstance(raw, dict) else None
    card_id = ident if isinstance(ident, str) else ""
    # Каждая карточка — свой слот общего предела вызовов модели, без ожидания.
    if not gate.try_enter():
        return {
            "id": card_id,
            "status": BUSY,
            "candidates": [],
            "message": _said("walk.batch.model_busy", lang),
        }
    try:
        if not isinstance(raw, dict):
            raise WalkRefused("walk.err.bad_request")
        return _one(who, inspection, raw, hint)
    except WalkRefused as exc:
        text = _said(str(exc), lang)
    except (RecognizeError, DomainError, CriteriaUnavailable, ValidationError, OSError) as exc:
        # Только тип: слова аудитора и текст модели в журнал не идут.
        logger.warning("Обход: карточка пакета не подобрана: %s", type(exc).__name__)
        text = _said("walk.err.recognize", lang)
    finally:
        gate.leave()
    return {
        "id": card_id,
        "status": UNAVAILABLE,
        "candidates": [],
        "message": text,
    }


def _said(key: str, lang: str) -> str:
    entry = WALK_TEXTS[key]
    return entry.get(lang) or entry["ru"]


def _in_parallel(
    who: int, inspection: Inspection, cards: list[Any], hint: str | None, lang: str, gate: SlowGate
) -> list[dict[str, Any]]:
    contexts = [contextvars.copy_context() for _ in cards]
    with ThreadPoolExecutor(max_workers=min(WORKERS, len(cards))) as pool:
        futures = [
            pool.submit(ctx.run, _guarded, who, inspection, raw, hint, lang, gate)
            for ctx, raw in zip(contexts, cards, strict=True)
        ]
    return [f.result() for f in futures]


def install(
    app: Flask,
    *,
    conf: WalkSettings,
    ui_lang: str,
    identify: Identify,
    session: ModelSession | None = None,
) -> None:
    """Повесить пакетный подбор. Замки — те же, что у одиночного: один подбор на чат за раз."""
    resources = session or ModelSession()
    busy, guard, gate = resources.busy, resources.guard, resources.gate

    def refused(key: str, lang: str, status: int = 422) -> tuple[Response, int]:
        return jsonify({"error": "refused", "message": _said(key, lang)}), status

    @app.post(BATCH_PATH, endpoint=BATCH_ENDPOINT)
    def walk_batch() -> tuple[Response, int]:
        who = identify(conf, ui_lang, header_only=True)
        if not isinstance(who, int):
            return who
        request.max_content_length = MAX_BATCH_BODY_BYTES
        try:
            body = request.get_json(silent=True)
        except RequestEntityTooLarge:
            return refused("walk.level.too_large", ui_lang, 413)
        if not isinstance(body, dict):
            return refused("walk.err.bad_request", ui_lang, 400)
        inspection = get_state(who)
        if inspection is None:
            return refused("walk.none.title", ui_lang, 409)
        lang = inspection.ui_lang
        if handed_over(who):
            return refused("walk.sealed", lang, 409)
        if "run_id" in body and body["run_id"] != inspection.run_id:
            return refused("walk.err.run_changed", lang, 409)
        cards = body.get("cards")
        if not isinstance(cards, list) or not cards or len(cards) > MAX_CARDS:
            return refused("walk.err.bad_request", lang, 400)
        with guard:
            if who in busy:
                return refused("walk.err.suggest_busy", lang, 429)
            busy.add(who)
        hold = try_hold(WALK_SUGGEST, str(who))
        if not hold.acquired:
            with guard:
                busy.discard(who)
            return refused("walk.err.suggest_busy", lang, 429)
        try:
            try:
                hint = _code(body, "zone_hint") if body.get("zone_hint") else None
            except WalkRefused as exc:
                return refused(str(exc), lang, 400)
            results = _in_parallel(who, inspection, cards, hint, lang, gate)
        finally:
            hold.release()
            with guard:
                busy.discard(who)
        logger.info(
            "Обход: чат %s — пакетный подбор, карточек %s, найдено %s",
            log_id(who),
            len(results),
            sum(1 for r in results if r["status"] == FOUND),
        )
        return jsonify({"run_id": inspection.run_id, "cards": results}), 200
