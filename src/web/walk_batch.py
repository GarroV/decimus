"""Мини-апп обхода: пакетный подбор нарушений — `POST /tg/walk/batch`.

Аудитор вкидывает до 5 кадров (карточек), к каждому пишет слова. С одного кадра — несколько
нарушений (D713): карточка отвечает СПИСКОМ строк, по строке на нарушение. Слова с разными
дефектами делит модель (`recognize.split`: «пол грязный, дверь не закрывается» — две строки,
«грязный пол у двери» — одна); слов нет — по строке на каждое нарушение, которое модель видит
на кадре. Каждая строка проходит тот же путь, что одиночный ввод: пункт по кадрам и словам
(`walk_suggest`: быстрый путь → выученная фраза → модель), зона из слов, класс по полным
критериям выбранного пункта (`walk_level`). Ничего не пишет: запись остаётся обычным
`POST /tg/walk/finding` на каждую строку (модель предлагает, фиксирует человек), поэтому журнал
шагов и пополнение словаря работают как у одиночной записи.

Строка может нести решения человека: `code` — пункт выбран руками («Другой пункт»; поиск по
кадрам пропускается, класс считается заново) и `zone` — зона выбрана руками; вместе с `line`
такой запрос повторяет одну строку и не делит слова заново. Карточка занимает один слот общего
предела вызовов модели (строки внутри идут параллельно); сбой карточки не роняет остальные: она
возвращается со своим статусом и текстом.

Повтор здесь не решается: что было в прошлый раз, клиент берёт из данных экрана
(`zones[].previous`), а «то же самое?» спрашивает человека.
"""

from __future__ import annotations

import contextvars
import logging
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from functools import partial
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
from src.recognize.split import split_violations

from . import walk_steps
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

#: Карточек в одном вызове (D712: «лимит до 5 фоток»). Каждая — до двух платных вызовов модели.
MAX_CARDS = 5
#: Предел тела: карточка — до 1000 знаков слов (до 4 байт на знак) и до 20 ссылок на кадры
#: (по ~80 байт) — около 6 КБ; на 5 карточек с большим запасом.
MAX_BATCH_BODY_BYTES = 96 * 1024
BUSY = "busy"
#: Параллельных карточек внутри вызова (как у `mcp.import_match.WORKERS`).
WORKERS = 8
#: Предложений пункта на карточку: первое — выбор системы, остальные — запасные.
MAX_CANDIDATES = 3
#: Строк (нарушений), которые система находит на одной карточке сама (D713): «сколько угодно»
#: упирается в платный класс на каждую; остальное аудитор добавляет строкой руками.
MAX_LINES = 8
#: Строк (нарушений) на весь вызов: платный путь на каждую. Делится поровну между карточками,
#: но не меньше двух на карточку. Строки карточки идут ПО ОДНОЙ в её слоте предела модели:
#: параллелизм вызова ограничен числом слотов, а не числом строк.
MAX_LINES_TOTAL = 12
MIN_LINES_PER_CARD = 2

#: Статус самой карточки: `ok` — строки подобраны; `busy` и `unavailable` — карточка не прошла.
OK = "ok"
#: Статусы строки: `found` — пункт и класс есть, остальное — решает человек.
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
    who: int,
    inspection: Inspection,
    *,
    words: str,
    refs: list[str],
    hint: str | None,
    limit: int = MAX_CANDIDATES,
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
    if words:
        # Слова строки решают пункт, кадр — лишь подспорье: что модель «увидела» на общем кадре
        # сверх слов (`also_seen`) — чужое нарушение, и второй строке с другими словами оно
        # пунктом не становится. Увиденное сверх слов — путь кадра без слов (строка «увидено»).
        offer = replace(offer, also_seen=())
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
    return list(reply["candidates"])[:limit], offer.via


def _line(
    who: int,
    inspection: Inspection,
    *,
    line_id: str,
    words: str,
    refs: list[str],
    hint: str | None,
    pinned: str | None = None,
    human_zone: str | None = None,
    found: list[dict[str, Any]] | None = None,
    via: str | None = None,
    photo_only: bool = False,
) -> dict[str, Any]:
    """Одна строка карточки: пункт → зона → класс. Отказ строки — её статус, не отказ карточки.

    `found` — пункты, уже найденные по кадру (строка «увидено»): поиск не идёт, первый — выбор
    системы. `pinned` — пункт назван человеком.
    """
    out: dict[str, Any] = {
        "id": line_id,
        "status": UNAVAILABLE,
        "candidates": [],
        "words": words,
        # Без слов система смотрит только кадр: клиент просит подтверждения пункта.
        "photo_only": photo_only,
    }
    candidates = found or []
    if via:
        out["via"] = via
    if pinned is None and not candidates:
        candidates, out["via"] = _candidates_of(who, inspection, words=words, refs=refs, hint=hint)
    out["candidates"] = candidates
    if pinned is None and not candidates:
        out["status"] = NO_ITEM
        return out
    code = pinned or candidates[0]["code"]
    levels = get_item(code, chat_id=who).levels
    out["code"] = code
    out["item_levels"] = list(levels)
    out["wording"] = candidates[0]["wording"] if candidates and not pinned else None
    out["suggested"] = (
        {k: candidates[0][k] for k in ("code", "level", "zone", "confidence")}
        if candidates and not pinned
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
        result = _level(who, inspection, code=code, zone=zone, words=words, refs=refs, card=line_id)
    except MissingFacts:
        out["status"] = NO_FACTS
        return out
    out["status"] = FOUND
    out["class"] = {
        key: result.get(key)
        for key in ("status", "level", "provisional_level", "need_fact", "reason")
    }
    return out


def _lines_in_turn(calls: Sequence[Callable[[], dict[str, Any]]]) -> list[dict[str, Any]]:
    """Строки одной карточки — одна за другой, в слоте самой карточки (предел модели считает её)."""
    return [call() for call in calls]


def _cap_of(cards: int) -> int:
    """Сколько строк модель находит на одной карточке: общий предел вызова поровну."""
    return min(MAX_LINES, max(MIN_LINES_PER_CARD, MAX_LINES_TOTAL // max(cards, 1)))


def _split(words: str, cap: int) -> tuple[list[str], bool]:
    """Нарушения комментария и «деление не удалось». Сбой деления — комментарий одной строкой."""
    try:
        parts = split_violations(words, max_parts=cap)
    except (RecognizeError, OSError) as exc:
        logger.warning("Обход: комментарий пачки не поделен: %s", type(exc).__name__)
        return [words], True
    return list(parts), False


def _one(
    who: int, inspection: Inspection, raw: dict[str, Any], hint: str | None, cap: int
) -> dict[str, Any]:
    """Одна карточка: кадры и слова → строки (по нарушению на строку), у каждой пункт, зона, класс.

    Слова с несколькими РАЗНЫМИ дефектами делятся на строки (`split_violations`); слов нет —
    строки по тому, что модель видит на кадре. `line`, `code` или `zone` в запросе — повтор
    одной строки (человек выбрал пункт или зону, дописал слово): деления нет, ответ — одна
    строка с тем же id.
    """
    card = _text(raw, "id")
    out: dict[str, Any] = {"id": card, "status": OK, "lines": []}
    words = _text(raw, "words")
    photos = raw.get("photos")
    # Предел — до разбора ссылок: лишние кадры не читаются с диска и не уходят в модель.
    refs = _refs(
        photos[:MAX_SUGGEST_PHOTOS] if isinstance(photos, list) else photos, who, inspection
    )
    pinned = _code(raw, "code") if raw.get("code") else None
    human_zone = _code(raw, "zone") if raw.get("zone") else None
    line_id = _text(raw, "line")
    if line_id or pinned or human_zone:
        out["lines"] = [
            _line(
                who,
                inspection,
                line_id=line_id or f"{card}-1",
                words=words,
                refs=refs,
                hint=hint,
                pinned=pinned,
                human_zone=human_zone,
                photo_only=raw.get("photo_only") is True,
            )
        ]
        return out
    if words:
        parts, out["split_failed"] = _split(words, cap)
        calls = [
            partial(
                _line,
                who,
                inspection,
                line_id=f"{card}-{n}",
                words=part,
                refs=refs,
                hint=hint,
            )
            for n, part in enumerate(parts, 1)
        ]
        out["lines"] = _lines_in_turn(calls)
        return out
    # Кадр без слов: всё, что видит модель, — каждое отдельной строкой.
    seen, via = _candidates_of(who, inspection, words="", refs=refs, hint=hint, limit=cap)
    if not seen:
        out["lines"] = [
            {
                "id": f"{card}-1",
                "status": NO_ITEM,
                "candidates": [],
                "words": "",
                "photo_only": True,
                "via": via,
            }
        ]
        return out
    out["lines"] = _lines_in_turn(
        [
            partial(
                _line,
                who,
                inspection,
                line_id=f"{card}-{n}",
                words="",
                refs=refs,
                hint=hint,
                found=[found],
                via=via,
                photo_only=True,
            )
            for n, found in enumerate(_distinct(seen)[:cap], 1)
        ]
    )
    return out


def _distinct(found: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Один пункт в одной зоне — одно нарушение: повторы модели строк не множат."""
    seen: set[tuple[str, str | None]] = set()
    out: list[dict[str, Any]] = []
    for item in found:
        key = (item["code"], item.get("zone"))
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def _guarded(
    who: int,
    inspection: Inspection,
    raw: Any,
    hint: str | None,
    lang: str,
    gate: SlowGate,
    cap: int,
) -> dict[str, Any]:
    started = time.monotonic()
    ident = raw.get("id") if isinstance(raw, dict) else None
    card_id = ident if isinstance(ident, str) else ""
    # Каждая карточка — свой слот общего предела вызовов модели, без ожидания.
    if not gate.try_enter():
        return {
            "id": card_id,
            "status": BUSY,
            "lines": [],
            "message": _said("walk.batch.model_busy", lang),
            "error_code": BUSY,
        }
    try:
        if not isinstance(raw, dict):
            raise WalkRefused("walk.err.bad_request")
        card = _one(who, inspection, raw, hint, cap)
        card["ms"] = _since(started)
        return card
    except WalkRefused as exc:
        text, code = _said(str(exc), lang), str(exc)
    except (RecognizeError, DomainError, CriteriaUnavailable, ValidationError, OSError) as exc:
        # Только тип: слова аудитора и текст модели в журнал не идут.
        logger.warning("Обход: карточка пакета не подобрана: %s", type(exc).__name__)
        text, code = _said("walk.err.recognize", lang), type(exc).__name__
    finally:
        gate.leave()
    return {
        "id": card_id,
        "status": UNAVAILABLE,
        "lines": [],
        "message": text,
        # Для журнала шагов: код отказа или тип исключения, без текста.
        "error_code": code,
        "ms": _since(started),
    }


def _since(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _said(key: str, lang: str) -> str:
    entry = WALK_TEXTS[key]
    return entry.get(lang) or entry["ru"]


def _in_parallel(
    who: int, inspection: Inspection, cards: list[Any], hint: str | None, lang: str, gate: SlowGate
) -> list[dict[str, Any]]:
    cap = _cap_of(len(cards))
    contexts = [contextvars.copy_context() for _ in cards]
    with ThreadPoolExecutor(max_workers=min(WORKERS, len(cards))) as pool:
        futures = [
            pool.submit(ctx.run, _guarded, who, inspection, raw, hint, lang, gate, cap)
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

    def refused(key: str, lang: str, status: int = 422, **params: Any) -> tuple[Response, int]:
        walk_steps.note_reason(key)
        message = _said(key, lang)
        return jsonify({"error": "refused", "message": message.format(**params)}), status

    @app.post(BATCH_PATH, endpoint=BATCH_ENDPOINT)
    @walk_steps.logged(walk_steps.KIND_BATCH)
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
        walk_steps.note_run(who, inspection)
        lang = inspection.ui_lang
        if handed_over(who):
            return refused("walk.sealed", lang, 409)
        if "run_id" in body and body["run_id"] != inspection.run_id:
            return refused("walk.err.run_changed", lang, 409)
        cards = body.get("cards")
        if isinstance(cards, list) and len(cards) > MAX_CARDS:
            return refused("walk.batch.too_many", lang, 400, n=MAX_CARDS)
        if not isinstance(cards, list) or not cards:
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
            "Обход: чат %s — пакетный подбор, карточек %s, найдено строк %s",
            log_id(who),
            len(results),
            sum(1 for r in results for line in r["lines"] if line["status"] == FOUND),
        )
        return jsonify({"run_id": inspection.run_id, "cards": results}), 200
