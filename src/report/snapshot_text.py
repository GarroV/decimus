"""Derived delivery translations, shared by PDF, letter and archived document cache."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from src.db import document_cache
from src.db.reach import own_reach
from src.domain.config import Settings
from src.domain.engine import chat_dir, state_file
from src.domain.errors import DomainError
from src.domain.models import Inspection
from src.domain.state import _read_raw, _write_atomic, read_state, state_lock

from . import localized
from .errors import ReportError

logger = logging.getLogger(__name__)
MAX_TEXT = 1000
CACHE_FILE = "document-translations.json"


def _sources(inspection: Inspection) -> list[str]:
    return [value for f in inspection.findings for value in (f.text, f.comment)] + [
        row.text for row in inspection.info.values()
    ]


def _key(inspection: Inspection) -> str:
    content = [inspection.run_id, inspection.speech_lang, _sources(inspection)]
    return hashlib.sha256(json.dumps(content, ensure_ascii=False).encode()).hexdigest()


def _memo(
    chat_id: int, env: Settings, inspection: Inspection, *, active_only: bool = False
) -> dict[str, str]:
    path = chat_dir(chat_id, env) / CACHE_FILE
    if not path.exists():
        return {}
    try:
        raw = _read_raw(path)
        if active_only and not raw.get("active", True):
            return {}
        if raw.get("source") == _key(inspection) and raw.get("lang") == inspection.report_lang:
            return dict(raw["memo"])
    except (DomainError, ValueError, KeyError, TypeError, OSError):
        logger.warning("Derived document translations could not be read", exc_info=True)
    return {}


def prepare(chat_id: int, env: Settings) -> int:
    """Cache successful translations without editing inspection.json or its evidence."""
    inspection = read_state(chat_id, env)
    if inspection is None:
        raise ReportError("Снимок проверки отсутствует")
    sources = _sources(inspection)
    path = chat_dir(chat_id, env) / CACHE_FILE
    with state_lock(path):
        memo = _memo(chat_id, env, inspection)
        for source in localized.text_sources(sources):
            if source in memo:
                continue
            try:
                translated = localized.translate_sources([source], lang=inspection.report_lang)[
                    source
                ]
                if len(translated) > MAX_TEXT:
                    raise ReportError("Перевод поля слишком длинный")
                memo[source] = translated
            except ReportError:
                logger.warning("Delivery field translation unavailable", exc_info=True)
        _write_atomic(
            path,
            {
                "source": _key(inspection),
                "lang": inspection.report_lang,
                "memo": memo,
                "active": True,
            },
        )
    return sum(value not in memo for value in sources if localized.text_sources([value]))


def disable(chat_id: int, env: Settings) -> None:
    """Manual mode does not render a previous AUTO attempt; keep its memo for reuse."""
    path = chat_dir(chat_id, env) / CACHE_FILE
    if path.exists():
        with state_lock(path):
            raw = _read_raw(path)
            raw["active"] = False
            _write_atomic(path, raw)


def render_state(chat_id: int, env: Settings) -> tuple[dict[str, Any] | None, str | None]:
    """Return a render-only copy and feedback language; technical evidence stays original."""
    inspection = read_state(chat_id, env)
    if inspection is None:
        return None, None
    memo = _memo(chat_id, env, inspection, active_only=True)
    if not memo:
        return None, None
    raw = _read_raw(state_file(chat_id, env))
    for finding in raw.get("findings", []):
        for field in ("evidence", "comment"):
            value = finding.get(field, "")
            finding[field] = memo.get(value, value)
    # Do not label partially translated feedback as the requested language.
    info_sources = localized.text_sources(row.text for row in inspection.info.values())
    feedback_lang = None
    if all(value in memo for value in info_sources):
        for code, row in inspection.info.items():
            value = raw["info"][code]
            if isinstance(value, dict):
                value["text"] = memo.get(row.text, row.text)
            else:
                raw["info"][code] = memo.get(row.text, row.text)
        feedback_lang = inspection.report_lang
    return raw, feedback_lang


def archive(chat_id: int, env: Settings, inspection_id: str) -> None:
    """Seed the existing scoped document cache; archived source records remain intact."""
    inspection = read_state(chat_id, env)
    if inspection is None:
        return
    memo = _memo(chat_id, env, inspection)
    if memo:
        document_cache.save(
            inspection_id,
            lang=inspection.report_lang,
            kind="translation",
            fingerprint=localized.memo_fingerprint(_sources(inspection)),
            payload={"memo": memo},
            reach=own_reach(inspection.tenant),
        )
