"""Authenticated acknowledgement of technical checkpoints in the current walk."""

from __future__ import annotations

import logging
from collections.abc import Callable

from flask import Flask, Response, jsonify, request

from src.domain import get_state
from src.domain.errors import DomainError
from src.domain.handover import HandedOverError
from src.domain.technical import TechnicalConflict, TechnicalRefused, confirm

from .texts_technical_errors import TECHNICAL_ERROR_TEXTS
from .walk_auth import TECHNICAL_ENDPOINT, TECHNICAL_PATH, WalkSettings

logger = logging.getLogger(__name__)
PATH = TECHNICAL_PATH
ENDPOINT = TECHNICAL_ENDPOINT


def install(
    app: Flask,
    *,
    conf: WalkSettings,
    ui_lang: str,
    identify: Callable[..., int | tuple[Response, int]],
    respond: Callable[[int, str], tuple[Response, int]],
) -> None:
    @app.post(PATH, endpoint=ENDPOINT)
    def acknowledge() -> tuple[Response, int]:
        who = identify(conf, ui_lang, header_only=True)
        if not isinstance(who, int):
            return who
        lang = ui_lang
        try:
            body = request.get_json(silent=True)
            if not isinstance(body, dict):
                raise TechnicalRefused()
            current = get_state(who)
            if current is None:
                raise TechnicalConflict()
            lang = current.ui_lang
            for field in ("run_id", "check_id", "zone", "status"):
                if not isinstance(body.get(field), str):
                    raise TechnicalRefused()
            expected = body.get("revision")
            if expected is not None and not isinstance(expected, str):
                raise TechnicalRefused()
            if (
                body.get("checklist_version", current.checklist_version)
                != current.checklist_version
            ):
                raise TechnicalConflict()
            confirm(
                who,
                run_id=body["run_id"],
                check_id=body["check_id"],
                zone=body["zone"],
                status=body["status"],
                reason=body.get("reason", ""),
                finding_numbers=body.get("finding_numbers"),
                expected_revision=expected,
            )
        except TechnicalRefused as exc:
            key = str(exc)
            entry = TECHNICAL_ERROR_TEXTS[key]
            return jsonify(
                {
                    "error": "technical_conflict"
                    if isinstance(exc, TechnicalConflict)
                    else "technical_refused",
                    "reason": key,
                    "message": entry.get(lang) or entry["en"],
                }
            ), (409 if isinstance(exc, TechnicalConflict) else 422)
        except HandedOverError:
            from .texts_walk import WALK_TEXTS

            entry = WALK_TEXTS["walk.sealed"]
            return jsonify({"error": "sealed", "message": entry.get(lang) or entry["en"]}), 409
        except (DomainError, OSError):
            logger.exception("Technical checkpoint confirmation failed")
            entry = TECHNICAL_ERROR_TEXTS["walk.technical.err.invalid"]
            return jsonify({"error": "server", "message": entry.get(lang) or entry["en"]}), 503
        return respond(who, ui_lang)
