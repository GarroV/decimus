"""Selected-item criterion request and a result bound to the exact factual context."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from src.domain import list_zones
from src.domain.clarifications import MAX_LEVEL_WORDS, clarification_chain
from src.domain.criteria import ItemCriteria, item_criteria
from src.domain.errors import ValidationError
from src.domain.findings import check_reading

from .classify import AskArgs
from .client import ModelAnswer
from .config import RecognizeSettings, load_recognize_settings
from .errors import RecognizeError
from .level import level_from, level_request
from .timing import measure

MAX_LEVEL_PHOTOS = 10
MAX_SELECTION_REVISION = 128


class MissingFacts(ValidationError):
    """There is nothing to classify; do not ask a model to invent an observation."""


class UnconfirmedReading(ValidationError):
    """A model's numerical hypothesis is not a human-confirmed measurement."""


@dataclass(frozen=True)
class PreparedLevel:
    ask: AskArgs
    item: ItemCriteria
    levels: tuple[str, ...]
    context: dict[str, Any]


def prepare_selected_level(
    chat_id: int,
    *,
    code: str,
    zone: str | None,
    words: str,
    photo_refs: Sequence[str],
    photos: Sequence[bytes],
    selection_revision: str,
    reading_c: float | None = None,
    reading_confirmed: bool = False,
    reading_source: str | None = None,
    settings: RecognizeSettings | None = None,
    clarifications: Any = None,
) -> PreparedLevel:
    if (
        not isinstance(selection_revision, str)
        or not 1 <= len(selection_revision) <= MAX_SELECTION_REVISION
    ):
        raise ValidationError("Нужна ревизия выбранного пункта")
    if not isinstance(words, str) or len(words) > MAX_LEVEL_WORDS:
        raise ValidationError("Слова аудитора превышают предел запроса")
    chain = clarification_chain([] if clarifications is None else clarifications, words=words)
    if len(photo_refs) != len(photos) or len(photos) > MAX_LEVEL_PHOTOS:
        raise ValidationError("Список кадров запроса не совпадает с приложенными изображениями")
    if reading_c is not None:
        check_reading(reading_c)
        if reading_confirmed is not True or reading_source not in ("human", "model"):
            raise UnconfirmedReading("Показание должен явно подтвердить человек")
    if not words.strip() and not photos and reading_c is None and not chain:
        raise MissingFacts("Нет фактов для выбранного пункта")
    item = item_criteria(chat_id, code)
    if zone is not None and zone not in {z.code for z in list_zones(chat_id=chat_id)}:
        raise ValidationError("Выбранной зоны нет в издании проверки")
    facts = {
        "words": words.strip(),
        "clarifications": chain,
        "photo_refs": list(photo_refs),
        "reading_c": reading_c,
        "reading_confirmed": reading_c is not None,
        "reading_source": reading_source if reading_c is not None else None,
    }
    facts_key = hashlib.sha256(
        json.dumps(facts, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    context: dict[str, Any] = {
        "run_id": item.run_id,
        "checklist_version": item.checklist_version,
        "code": item.code,
        "zone": zone,
        "selection_revision": selection_revision,
        "facts_key": facts_key,
        "criteria_hash": item.criteria_hash,
        "photo_refs": list(photo_refs),
        "facts_from": {
            "words": bool(words.strip()),
            "confirmed_reading": reading_c is not None,
            "photos": len(photos),
        },
    }
    binding = {
        key: context[key]
        for key in ("run_id", "checklist_version", "code", "zone", "photo_refs", "criteria_hash")
    }
    binding["clarifications"] = chain
    context["clarifications"] = chain
    context["clarification_hash"] = hashlib.sha256(
        json.dumps(binding, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
    note = words.strip()
    if reading_c is not None:
        note += f"\nПодтверждённое человеком показание термометра: {reading_c:g} °C."
    if zone is not None:
        note += f"\nЯвно выбранная зона: {zone}."
    ask = level_request(
        note,
        code=item.code,
        levels=item.levels,
        criteria=item.criteria,
        lang=item.lang,
        settings=settings or load_recognize_settings(),
        photos=photos,
        allow_no_violation=True,
        clarifications=chain,
    )
    return PreparedLevel(ask, item, item.levels, context)


def finish_selected_level(prepared: PreparedLevel, answer: ModelAnswer) -> dict[str, Any]:
    with measure("parse"):
        found = level_from(answer, prepared.levels, allow_no_violation=True)
    if found is None:
        raise RecognizeError("Ответ по критериям неполон или не соответствует допустимым классам")
    missing = bool(found.need_fact)
    return {
        **prepared.context,
        "status": "needs_fact"
        if missing
        else "not_established"
        if found.level is None
        else "ready",
        "level": None if missing else found.level,
        "provisional_level": found.level if missing else None,
        "need_fact": found.need_fact if missing or found.level is not None else None,
        "reason": found.reason,
    }


def evaluate_selected_level(prepared: PreparedLevel) -> dict[str, Any]:
    return finish_selected_level(prepared, prepared.ask.call())
