"""Блок «Таблица контроля» на «Загрузках»: когда забирали, чем кончилось, кнопка (D464).

Состояние лежит в `ratings.sheet_sync`, забирает бот (`src/bot/sheet_loader.py`);
веб только показывает его и принимает заявку «Забрать сейчас». Сбой видно строкой,
а не тишиной: причина по коду — ключом `texts_ratings`, на языке интерфейса; русский
текст причины остаётся журналу.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from src.db import ratings_sync as state
from src.db.errors import RatingsError
from src.ratings import sheet_sync

from .texts import TEXTS, t

logger = logging.getLogger(__name__)

#: Что сказать после кнопки «Забрать сейчас»: ключ в адресе → ключ текста.
NOTICES = {
    "queued": "ratings.sheet.queued",
    "already": "ratings.sheet.already",
    "db_down": "ratings.sheet.db_down",
}
ARG = "sheet"


@dataclass(frozen=True)
class Row:
    tab: str
    checked_at: datetime
    outcome: str
    counts: tuple[int, int, int, int] | None
    reason: str | None


@dataclass(frozen=True)
class Block:
    configured: bool
    rows: tuple[Row, ...]
    last_at: datetime | None
    failed: int
    pending: state.SyncRequest | None
    #: Состояние не прочиталось: блок не врёт «забирали недавно», а говорит об этом.
    unreadable: bool = False


def reason(note: str | None, lang: str) -> str | None:
    """Причина сбоя на языке интерфейса; русский — с подробностью из журнала."""
    if not note:
        return None
    code = note.split(":", 1)[0]
    key = f"ratings.sheet.err.{code}"
    text = t(key if key in TEXTS else "ratings.sheet.err.unknown", lang)
    detail = note.split(":", 1)[1].strip() if ":" in note else ""
    return f"{text} ({detail})" if lang == "ru" and detail else text


def build(lang: str) -> Block:
    configured = sheet_sync.configured()
    try:
        states = state.states()
        pending = state.open_request()
    except RatingsError:
        logger.warning("рейтинги: состояние забора таблицы не прочиталось", exc_info=True)
        return Block(configured, (), None, 0, None, unreadable=True)
    rows = tuple(
        Row(s.tab, s.checked_at, s.outcome, s.counts, reason(s.note, lang) if s.note else None)
        for s in sorted(states, key=lambda s: s.tab)
    )
    return Block(
        configured,
        rows,
        max((r.checked_at for r in rows), default=None),
        sum(1 for r in rows if r.outcome == state.OUTCOME_FAILED),
        pending,
    )
