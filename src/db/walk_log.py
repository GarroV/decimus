"""Журнал шагов обхода (D710, `0119`): запись шага и чтение для карточки проверки.

**Пишет роль приложения, читает схема.** Запись — прямой `insert` (прав на `select`,
`update`, `delete` у роли нет). Чтение — функцией `walk_log_read`, которая определяет
зрителя по токену его живой сессии: шаги видят главный админ и админ УК, остальным —
пусто.

**Запись не роняет и не тормозит шаг аудитора.** Шаг уже состоялся, а журнал — побочная
запись: `submit` отдаёт её фоновому потоку и сразу возвращается, `record` ловит любой сбой
базы и пишет его в журнал процесса (`logger.exception`). Очередь ограничена
(`MAX_PENDING`): база легла надолго — лишние записи отбрасываются громко, а не копятся
в памяти. Это одно из двух мест, где перехватывается любое исключение (второе —
`model_usage.record`): ни одна поломка учёта не вправе отменить работу аудитора.
"""

from __future__ import annotations

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from .web_access import _connected

logger = logging.getLogger(__name__)

STEP_SUGGEST = "suggest"
STEP_CLASS = "class"
STEP_CLASS_FACTS = "class_facts"
STEP_CLASS_MANUAL = "class_manual"
STEP_SAVE = "save"
STEP_EDIT = "edit"
STEP_REMOVE = "remove"
STEP_OTHER = "other"

OUTCOME_OK = "ok"
OUTCOME_REFUSED = "refused"
OUTCOME_ERROR = "error"

#: Сколько записей ждёт фонового потока; больше — отбрасываются (громко).
MAX_PENDING = 500
_WORDS_MAX = 2000
_REASON_MAX = 1500
_ERROR_MAX = 300

_INSERT_SQL = """
    insert into walk_log
        (run_id, chat_id, tenant_code, unit_label, visit_date, step, outcome, words, photos,
         item_code, zone, level, verdict, reason, via, detail, duration_ms, error)
    values (%(run_id)s, %(chat_id)s, %(tenant)s, %(unit)s, %(visit_date)s, %(step)s,
            %(outcome)s, %(words)s, %(photos)s, %(item_code)s, %(zone)s, %(level)s,
            %(verdict)s, %(reason)s, %(via)s, %(detail)s::jsonb, %(duration_ms)s, %(error)s)
"""
_READ_SQL = "select * from walk_log_read(%s, %s)"
_PURGE_SQL = "select purge_walk_log()"

_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="walk-log")
_state = {"pending": 0}
_lock = threading.Lock()


@dataclass(frozen=True)
class WalkStep:
    """Один шаг обхода так, как он пишется в журнал."""

    chat_id: int
    step: str
    outcome: str
    run_id: str = ""
    tenant: str = ""
    unit: str = ""
    visit_date: date | None = None
    words: str = ""
    photos: int = 0
    item_code: str | None = None
    zone: str | None = None
    level: str | None = None
    verdict: str | None = None
    reason: str = ""
    via: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)
    duration_ms: int | None = None
    error: str = ""


@dataclass(frozen=True)
class StepRow:
    """Строка журнала так, как её показывает карточка проверки."""

    id: int
    at: datetime
    run_id: str
    unit: str
    step: str
    outcome: str
    words: str
    photos: int
    item_code: str | None
    zone: str | None
    level: str | None
    verdict: str | None
    reason: str
    via: str | None
    detail: dict[str, Any]
    duration_ms: int | None
    error: str
    login: str | None


def record(step: WalkStep) -> None:
    """Дописать шаг. Любой сбой — в журнал процесса, шаг аудитора он не отменяет."""
    try:
        with _connected("записать шаг обхода") as conn, conn.cursor() as cur:
            cur.execute(
                _INSERT_SQL,
                {
                    "run_id": step.run_id[:80] or None,
                    "chat_id": step.chat_id,
                    "tenant": step.tenant,
                    "unit": step.unit[:120],
                    "visit_date": step.visit_date,
                    "step": step.step,
                    "outcome": step.outcome,
                    "words": step.words[:_WORDS_MAX],
                    "photos": max(step.photos, 0),
                    "item_code": step.item_code[:60] if step.item_code else None,
                    "zone": step.zone[:60] if step.zone else None,
                    "level": step.level[:20] if step.level else None,
                    "verdict": step.verdict[:30] if step.verdict else None,
                    "reason": step.reason[:_REASON_MAX],
                    "via": step.via[:40] if step.via else None,
                    "detail": json.dumps(step.detail, ensure_ascii=False, default=str),
                    "duration_ms": step.duration_ms,
                    "error": step.error[:_ERROR_MAX],
                },
            )
    except Exception:
        logger.exception(
            "журнал обхода: запись не прошла (шаг %s, исход %s)", step.step, step.outcome
        )


def _run(step: WalkStep) -> None:
    try:
        record(step)
    finally:
        with _lock:
            _state["pending"] -= 1


def submit(step: WalkStep) -> None:
    """Отдать запись фоновому потоку и вернуться сразу; не бросает ничего."""
    try:
        with _lock:
            if _state["pending"] >= MAX_PENDING:
                logger.error("журнал обхода: очередь полна, шаг %s отброшен", step.step)
                return
            _state["pending"] += 1
        try:
            _pool.submit(_run, step)
        except Exception:
            with _lock:
                _state["pending"] -= 1
            raise
    except Exception:
        logger.exception("журнал обхода: шаг %s не поставлен в очередь", step.step)


def read(session_token: str, inspection_id: str) -> tuple[StepRow, ...]:
    """Шаги обхода проверки глазами зрителя; не админу УК и не главному — пусто."""
    with _connected("прочитать журнал обхода") as conn, conn.cursor() as cur:
        cur.execute(_READ_SQL, (session_token, inspection_id))
        rows = cur.fetchall()
    return tuple(
        StepRow(
            id=int(r[0]),
            at=r[1],
            run_id=str(r[2] or ""),
            unit=str(r[3] or ""),
            step=str(r[4]),
            outcome=str(r[5]),
            words=str(r[6] or ""),
            photos=int(r[7] or 0),
            item_code=r[8],
            zone=r[9],
            level=r[10],
            verdict=r[11],
            reason=str(r[12] or ""),
            via=r[13],
            detail=dict(r[14] or {}),
            duration_ms=r[15],
            error=str(r[16] or ""),
            login=r[17],
        )
        for r in rows
    )


def purge() -> int:
    """Убрать записи старше 30 дней. Число убранных."""
    with _connected("убрать старые шаги обхода") as conn, conn.cursor() as cur:
        cur.execute(_PURGE_SQL)
        row = cur.fetchone()
    return int(row[0]) if row else 0
