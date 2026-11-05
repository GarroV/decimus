"""Журнал шагов обхода (D710): запись шага из обработчиков мини-аппа.

Один декоратор на адрес (`logged`): после того как обработчик ответил — или упал, —
он собирает по запросу и ответу строку журнала и отдаёт её фоновой записи
(`src.db.walk_log.submit`). Обработчики сообщают только то, чего не видно снаружи:
кто и по какой проверке (`note_run`), по какой причине отказ (`note_reason`), чем
кончился сбой (`note_error`), каким путём найден пункт (`note_via`).

**Журнал не меняет шаг.** Любой сбой сборки строки уходит в журнал процесса, ответ
аудитору идёт как шёл; исключение обработчика пробрасывается дальше нетронутым. Кадры
не пишутся — только их число; текст сбоя не пишется — только тип исключения или код
отказа.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import replace
from functools import partial, wraps
from typing import Any, ParamSpec, TypeVar

from flask import Response, g, request

from src.db import walk_log
from src.db.walk_log import (
    OUTCOME_ERROR,
    OUTCOME_OK,
    OUTCOME_REFUSED,
    STEP_CLASS,
    STEP_CLASS_FACTS,
    STEP_CLASS_MANUAL,
    STEP_EDIT,
    STEP_OTHER,
    STEP_REMOVE,
    STEP_SAVE,
    STEP_SUGGEST,
    WalkStep,
)
from src.domain.models import Inspection
from src.domain.tenants import HQ_TENANT

logger = logging.getLogger(__name__)
P = ParamSpec("P")
R = TypeVar("R")

KIND_SUGGEST = "suggest"
KIND_LEVEL = "level"
KIND_FINDING = "finding"
KIND_BATCH = "batch"

#: Сколько предложенных пунктов уходит в журнал (остальные — хвост, он не нужен для разбора).
_CANDIDATES_MAX = 5
_TEXT_MAX = 1000
#: Значение `class_status`, которое экран шлёт, когда класс выбран руками.
CLASS_STATUS_MANUAL = "manual"
#: Модель недоступна, аудитор выбирает пункт вручную (`via` шага подбора).
VIA_FALLBACK = "fallback"
#: Шаг подбора сделан пакетным вводом (`/tg/walk/batch`): одна строка на карточку.
VIA_BATCH = "batch"
#: Статусы карточки пакета, с которыми система не смогла ответить (остальные — исход, а не сбой).
_BATCH_FAILED = {"unavailable", "busy"}
_FINDING_STEPS = {"add": STEP_SAVE, "edit": STEP_EDIT, "drop": STEP_REMOVE}

_RUN = "walk_log_run"
_REASON = "walk_log_reason"
_ERROR = "walk_log_error"
_VIA = "walk_log_via"


def note_run(chat_id: int, inspection: Inspection | None) -> None:
    """Запомнить, чей это шаг: чат и проверка (она может быть ещё не найдена)."""
    setattr(g, _RUN, (chat_id, inspection))


def note_reason(reason: str) -> None:
    """Код отказа (ключ текста), по которому система не приняла шаг."""
    setattr(g, _REASON, reason)


def note_error(error: str) -> None:
    """Код или тип исключения сбоя; текст исключения сюда не передаётся."""
    setattr(g, _ERROR, error)


def note_via(via: str) -> None:
    """Каким путём найден пункт, если это не видно по ответу (`fallback` — модель недоступна)."""
    setattr(g, _VIA, via)


def _json(raw: Any) -> dict[str, Any]:
    return raw if isinstance(raw, dict) else {}


def _body() -> dict[str, Any]:
    try:
        return _json(request.get_json(silent=True))
    except Exception:  # слишком большое или нечитаемое тело: шаг всё равно записывается
        return {}


def _response_json(result: Any) -> dict[str, Any]:
    response = result[0] if isinstance(result, tuple) else result
    if not isinstance(response, Response):
        return {}
    return _json(response.get_json(silent=True))


def _status_of(result: Any) -> int:
    if isinstance(result, tuple) and len(result) > 1 and isinstance(result[1], int):
        return result[1]
    return getattr(result, "status_code", 200)


def _outcome(status: int) -> str:
    if status < 400:
        return OUTCOME_OK
    return OUTCOME_ERROR if status >= 500 else OUTCOME_REFUSED


def _count(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _short(value: Any, limit: int) -> str:
    return _text(value).strip()[:limit]


def _cards(data: dict[str, Any]) -> list[dict[str, Any]]:
    cards = data.get("candidates")
    return [c for c in cards if isinstance(c, dict)] if isinstance(cards, list) else []


def _suggest_fields(body: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    cards = _cards(data)
    first = cards[0] if cards else {}
    resolution = _json(first.get("resolution"))
    return {
        "words": _text(body.get("words")),
        "photos": _count(body.get("photos")),
        "item_code": first.get("code"),
        "zone": resolution.get("zone") or first.get("zone"),
        "level": first.get("level"),
        "via": _text(data.get("via")) or None,
        "detail": {
            "candidates": [
                {"code": c.get("code"), "level": c.get("level"), "zone": c.get("zone")}
                for c in cards[:_CANDIDATES_MAX]
            ],
            "question": _short(data.get("question"), _TEXT_MAX),
            "omitted": data.get("photos_omitted") or 0,
        },
    }


def _batch_card_fields(
    raw: dict[str, Any], card: dict[str, Any], index: int, total: int
) -> dict[str, Any]:
    status = _text(card.get("status"))
    chosen = _json(card.get("class"))
    suggested = _json(card.get("suggested"))
    failed = status in _BATCH_FAILED
    return {
        "words": _text(raw.get("words")),
        "photos": _count(raw.get("photos")),
        "item_code": card.get("code"),
        "zone": card.get("zone"),
        "level": chosen.get("level") or chosen.get("provisional_level") or suggested.get("level"),
        "verdict": status or None,
        "reason": _short(chosen.get("reason"), 1500),
        "via": VIA_BATCH,
        "duration_ms": card.get("ms") if isinstance(card.get("ms"), int) else None,
        "outcome": OUTCOME_ERROR if failed else OUTCOME_OK,
        "error": _short(card.get("error_code") or status, 300) if failed else "",
        "detail": {
            "card": index + 1,
            "of": total,
            "candidates": [
                {"code": c.get("code"), "level": c.get("level"), "zone": c.get("zone")}
                for c in _cards(card)[:_CANDIDATES_MAX]
            ],
            "class_status": chosen.get("status"),
            "zone_source": card.get("zone_source"),
            "photo_only": card.get("photo_only") is True,
            "pinned": bool(raw.get("code")),
        },
    }


def _batch_fields(body: dict[str, Any], data: dict[str, Any]) -> list[dict[str, Any]]:
    """По строке на карточку; вызов, отклоненный целиком, — одна строка без карточек."""
    raw_cards = body.get("cards")
    raws = [c for c in raw_cards if isinstance(c, dict)] if isinstance(raw_cards, list) else []
    by_id = {_text(c.get("id")): c for c in raws}
    answers = [c for c in data.get("cards", []) if isinstance(c, dict)]
    if not answers:
        return [
            {
                "words": "",
                "photos": sum(_count(c.get("photos")) for c in raws),
                "via": VIA_BATCH,
                "detail": {"cards": len(raws)},
            }
        ]
    return [
        _batch_card_fields(by_id.get(_text(card.get("id")), {}), card, i, len(answers))
        for i, card in enumerate(answers)
    ]


def _level_fields(body: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    facts = _count(body.get("clarifications"))
    level = data.get("level") or data.get("provisional_level")
    return {
        "step": STEP_CLASS_FACTS if facts else STEP_CLASS,
        "words": _text(body.get("words")),
        "photos": _count(body.get("photos")),
        "item_code": body.get("code"),
        "zone": body.get("zone"),
        "level": level,
        "verdict": data.get("status"),
        "reason": _short(data.get("reason"), 1500),
        "detail": {
            "clarifications": facts,
            "question": _short(data.get("need_fact"), _TEXT_MAX),
            "provisional": data.get("provisional_level"),
        },
    }


def _finding_fields(body: dict[str, Any]) -> dict[str, Any]:
    op = _text(body.get("op"))
    context = _json(body.get("class_context"))
    return {
        "step": _FINDING_STEPS.get(op, STEP_OTHER),
        "words": _text(body.get("words")),
        "photos": _count(body.get("photos")) or _count(body.get("new_refs")),
        "item_code": body.get("code"),
        "zone": body.get("zone"),
        "level": body.get("level"),
        "verdict": _text(body.get("class_status")) or None,
        "detail": {
            "op": op,
            "n": body.get("n"),
            "text": _short(body.get("text"), _TEXT_MAX),
            "clarifications": _count(context.get("clarifications")),
            "also": body.get("also") is True,
        },
    }


def _step_of(
    fields: dict[str, Any],
    *,
    chat_id: int,
    inspection: Inspection,
    status: int,
    error: Any,
    started: float,
) -> WalkStep:
    """Строка журнала из полей шага; общие для всех видов шага поля — здесь."""
    fields = dict(fields)
    fields["via"] = getattr(g, _VIA, None) or fields.get("via")
    outcome = fields.pop("outcome", None) or _outcome(status)
    row_error = fields.pop("error", None)
    elapsed = fields.pop("duration_ms", None)
    return WalkStep(
        chat_id=int(chat_id),
        step=fields.pop("step"),
        outcome=outcome,
        run_id=inspection.run_id,
        tenant=inspection.tenant or HQ_TENANT,
        unit=inspection.unit,
        visit_date=inspection.visit_date(),
        duration_ms=elapsed if elapsed is not None else int((time.monotonic() - started) * 1000),
        error=row_error if row_error is not None else (_text(error) if status >= 400 else ""),
        **{k: v for k, v in fields.items() if k != "detail"},
        detail={
            **fields.get("detail", {}),
            **({"reason_code": getattr(g, _REASON)} if hasattr(g, _REASON) else {}),
            "status": status,
        },
    )


def _steps(
    kind: str,
    result: Any,
    exc: BaseException | None,
    started: float,
) -> list[WalkStep]:
    chat_id, inspection = getattr(g, _RUN, (None, None))
    if chat_id is None or inspection is None:
        return []
    body = _body()
    status = 500 if exc is not None else _status_of(result)
    data = _response_json(result) if kind != KIND_FINDING and exc is None else {}
    error = type(exc).__name__ if exc is not None else getattr(g, _ERROR, "") or data.get("error")
    build = partial(
        _step_of,
        chat_id=chat_id,
        inspection=inspection,
        status=status,
        error=error,
        started=started,
    )
    if kind == KIND_BATCH:
        # Одна строка на карточку; отказ всего вызова или падение — одна строка с причиной.
        rows = _batch_fields(body, data)
        return [build({"step": STEP_SUGGEST, **row}) for row in rows]
    if kind == KIND_SUGGEST:
        fields = {"step": STEP_SUGGEST, **_suggest_fields(body, data)}
    elif kind == KIND_LEVEL:
        fields = _level_fields(body, data)
    else:
        fields = _finding_fields(body)
    common = build(fields)
    steps = [common]
    if kind == KIND_FINDING and common.step == STEP_SAVE and common.verdict == CLASS_STATUS_MANUAL:
        # Класс вручную виден серверу только в этот миг: выбор делается на экране и
        # уходит вместе с записью, отдельного запроса у него нет.
        steps.insert(0, _manual(common))
    return steps


def _manual(save: WalkStep) -> WalkStep:
    return replace(save, step=STEP_CLASS_MANUAL, outcome=OUTCOME_OK, error="", duration_ms=None)


def _publish(kind: str, result: Any, exc: BaseException | None, started: float) -> None:
    try:
        for step in _steps(kind, result, exc, started):
            walk_log.submit(step)
    except Exception:
        logger.exception("журнал обхода: шаг %s не собран", kind)


def logged(kind: str) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Записать шаг после ответа обработчика (или его падения); ответ не меняется."""

    def decorate(view: Callable[P, R]) -> Callable[P, R]:
        @wraps(view)
        def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            started = time.monotonic()
            try:
                result = view(*args, **kwargs)
            except BaseException as exc:
                _publish(kind, None, exc, started)
                raise
            _publish(kind, result, None, started)
            return result

        return wrapped

    return decorate
