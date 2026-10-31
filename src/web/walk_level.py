"""Classify only the selected item, using its complete pinned criterion and fresh facts."""

from __future__ import annotations

import logging

from flask import Flask, Response, jsonify, request
from werkzeug.exceptions import RequestEntityTooLarge

from src.db.busy_lock import WALK_SUGGEST, try_hold
from src.domain import get_state, handed_over, upload_file
from src.domain.config import check_environment
from src.domain.criteria import CriteriaUnavailable, item_criteria
from src.domain.errors import DomainError, ValidationError
from src.domain.handover import HandedOverError
from src.domain.model_usage import KIND_SUGGEST, usage_scope
from src.recognize.errors import RecognizeError
from src.recognize.selected_level import (
    MAX_LEVEL_PHOTOS,
    MissingFacts,
    UnconfirmedReading,
    evaluate_selected_level,
    prepare_selected_level,
)
from src.recognize.timing import collect, measure

from .texts_walk import WALK_TEXTS
from .walk_auth import LEVEL_ENDPOINT, LEVEL_PATH, WalkSettings
from .walk_model_session import ModelSession
from .walk_write import Identify, WalkRefused, _code, _refs, _text, reading_of

logger = logging.getLogger(__name__)
MAX_LEVEL_BODY_BYTES = 32 * 1024
MAX_LEVEL_IMAGE_BYTES = 20 * 1024 * 1024


def _images(refs: list[str]) -> tuple[bytes, ...]:
    settings = check_environment()
    result = []
    total = 0
    for ref in refs:
        path = upload_file(ref, settings)
        if path is None:
            raise WalkRefused("walk.err.photo_lost")
        total += path.stat().st_size
        if total > MAX_LEVEL_IMAGE_BYTES:
            raise WalkRefused("walk.level.too_large")
        result.append(path.read_bytes())
    return tuple(result)


def install(
    app: Flask,
    *,
    conf: WalkSettings,
    ui_lang: str,
    identify: Identify,
    session: ModelSession | None = None,
) -> None:
    resources = session or ModelSession()
    busy, guard, gate = resources.busy, resources.guard, resources.gate

    def refused(error: str, key: str, lang: str, status: int = 422) -> tuple[Response, int]:
        entry = WALK_TEXTS[key]
        return jsonify(
            {
                "error": error,
                "status": "unavailable",
                "level": None,
                "message": entry.get(lang) or entry[ui_lang],
            }
        ), status

    def read_level() -> tuple[Response, int]:
        who = identify(conf, ui_lang, header_only=True)
        if not isinstance(who, int):
            return who
        inspection = get_state(who)
        if inspection is None:
            return refused("run_changed", "walk.none.title", ui_lang, 409)
        lang = inspection.ui_lang
        request.max_content_length = MAX_LEVEL_BODY_BYTES
        try:
            body = request.get_json(silent=True)
        except RequestEntityTooLarge:
            return refused("invalid_request", "walk.level.too_large", lang, 413)
        if not isinstance(body, dict) or not isinstance(body.get("run_id"), str):
            return refused("invalid_request", "walk.err.bad_request", lang, 400)
        if body["run_id"] != inspection.run_id:
            return refused("run_changed", "walk.err.run_changed", lang, 409)
        if (
            "checklist_version" in body
            and body["checklist_version"] != inspection.checklist_version
        ):
            return refused("context_changed", "walk.level.changed", lang, 409)
        if handed_over(who):
            return refused("run_changed", "walk.sealed", lang, 409)
        with guard:
            if who in busy:
                return refused("busy", "walk.err.suggest_busy", lang, 429)
            busy.add(who)
        hold = try_hold(WALK_SUGGEST, str(who))
        if not hold.acquired:
            with guard:
                busy.discard(who)
            return refused("busy", "walk.err.suggest_busy", lang, 429)
        if not gate.try_enter():
            hold.release()
            with guard:
                busy.discard(who)
            return refused("busy", "walk.err.overloaded", lang, 503)
        try:
            code = _code(body, "code")
            zone = _code(body, "zone") if body.get("zone") else None
            words = _text(body, "words")
            revision = body.get("selection_revision")
            if not isinstance(revision, str):
                return refused("invalid_request", "walk.err.bad_request", lang, 400)
            refs = body.get("photos", [])
            if not isinstance(refs, list) or len(refs) > MAX_LEVEL_PHOTOS:
                return refused("invalid_request", "walk.level.too_large", lang, 422)
            if "reading_confirmed" in body and not isinstance(body["reading_confirmed"], bool):
                return refused("invalid_request", "walk.err.bad_request", lang, 400)
            with measure("frames"):
                canonical = _refs(refs, who, inspection) if refs else []
                images = _images(canonical)
            with measure("level_prepare"):
                prepared = prepare_selected_level(
                    who,
                    code=code,
                    zone=zone,
                    words=words,
                    photo_refs=canonical,
                    photos=images,
                    selection_revision=revision,
                    clarifications=body.get("clarifications", []),
                    reading_c=reading_of(body),
                    reading_confirmed=body.get("reading_confirmed") is True,
                    reading_source=body.get("reading_source"),
                )
            if prepared.item.run_id != body["run_id"]:
                return refused("run_changed", "walk.err.run_changed", lang, 409)
            with usage_scope(
                kind=KIND_SUGGEST,
                telegram_id=who,
                tenant=inspection.tenant,
                inspection_ref=prepared.item.run_id,
                inspection_label=" · ".join((inspection.unit, inspection.date)),
            ):
                with measure("level"):
                    result = evaluate_selected_level(prepared)
            # A paid read can outlive a new run or a methodology rebind. Never
            # return its class as current if its server context changed.
            with measure("level_recheck"):
                state = get_state(who)
                if state is None or state.run_id != prepared.item.run_id:
                    return refused("run_changed", "walk.err.run_changed", lang, 409)
                if state.checklist_version != prepared.item.checklist_version:
                    return refused("context_changed", "walk.level.changed", lang, 409)
                current = item_criteria(who, code)
            if current != prepared.item:
                return refused("context_changed", "walk.level.changed", lang, 409)
            return jsonify(result), 200
        except MissingFacts:
            return refused("missing_facts", "walk.level.missing_facts", lang)
        except UnconfirmedReading:
            return refused("reading_unconfirmed", "walk.level.reading_unconfirmed", lang)
        except CriteriaUnavailable:
            return refused("criteria_unavailable", "walk.level.no_criteria", lang)
        except HandedOverError:
            return refused("run_changed", "walk.sealed", lang, 409)
        except WalkRefused as exc:
            return refused("invalid_request", str(exc), lang)
        except ValidationError:
            return refused("invalid_selection", "walk.err.rejected", lang)
        except (RecognizeError, DomainError, OSError):
            # Numerical timing only: criteria, raw facts and model output are
            # deliberately absent from logs, including failure paths.
            logger.warning("Обход: критерии выбранного пункта не проверены")
            return refused("unavailable", "walk.err.recognize", lang, 503)
        finally:
            gate.leave()
            hold.release()
            with guard:
                busy.discard(who)

    @app.post(LEVEL_PATH, endpoint=LEVEL_ENDPOINT)
    def walk_level() -> tuple[Response, int]:
        with collect() as timing:
            status = 500
            try:
                result = read_level()
                status = result[1]
                result[0].headers["Cache-Control"] = "no-store"
                return result
            finally:
                logger.info("Обход: время класса status=%s timing=%s", status, timing.report())
