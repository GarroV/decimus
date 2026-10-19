"""Расход модели (D537, `0078`): запись вызова и чтение сводки для экрана.

**Пишет роль приложения, читает схема.** Запись — прямой `insert` (прав на `select`,
`update`, `delete` у роли нет). Чтение — функцией `model_usage_read`, которая определяет
зрителя по токену его живой сессии: расход видят главный админ и админ УК, остальным —
пусто.

**Запись не должна ронять то, что учитывается.** Вызов провайдера уже состоялся и
оплачен; если база недоступна, отказ уходит в журнал процесса (`logger.exception`), а
человек получает свой результат. Это единственное место, где перехватывается любое
исключение: учёт — побочная запись, и ни одна её поломка не вправе отменить работу.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from src.domain.model_usage import ModelCall

from .web_access import _connected

logger = logging.getLogger(__name__)

DIM_DAY = "day"
DIM_KIND = "kind"
DIM_PERSON = "person"
DIM_INSPECTION = "inspection"

_INSERT_SQL = """
    insert into model_usage
        (kind, model, input_tokens, output_tokens, audio_seconds, ok,
         user_id, telegram_id, tenant_code, inspection_ref)
    values (%(kind)s, %(model)s, %(input)s, %(output)s, %(audio)s, %(ok)s,
            %(user)s, %(telegram)s, %(tenant)s, %(inspection)s)
"""
_READ_SQL = "select * from model_usage_read(%s, %s, %s)"


@dataclass(frozen=True)
class UsageRow:
    """Сумма расхода по одному значению среза и одной модели."""

    dim: str
    key: str
    label: str
    model: str
    calls: int
    failed: int
    input_tokens: int
    output_tokens: int
    audio_seconds: float


def record(call: ModelCall) -> None:
    """Дописать вызов. Любой сбой — в журнал процесса, вызов он не отменяет."""
    try:
        with _connected("записать расход модели") as conn, conn.cursor() as cur:
            cur.execute(
                _INSERT_SQL,
                {
                    "kind": call.kind,
                    "model": call.model[:120],
                    "input": call.input_tokens,
                    "output": call.output_tokens,
                    "audio": call.audio_seconds,
                    "ok": call.ok,
                    "user": call.user_id,
                    "telegram": call.telegram_id,
                    "tenant": call.tenant,
                    "inspection": call.inspection_ref[:80] if call.inspection_ref else None,
                },
            )
    except Exception:
        logger.exception(
            "расход модели: запись не прошла (вид %s, модель %s)", call.kind, call.model
        )


def read(
    session_token: str, *, start: datetime | None = None, end: datetime | None = None
) -> tuple[UsageRow, ...]:
    """Сводка расхода за период глазами зрителя; не админу — пусто. `end` не включается."""
    with _connected("прочитать расход модели") as conn, conn.cursor() as cur:
        cur.execute(_READ_SQL, (session_token, start, end))
        rows = cur.fetchall()
    return tuple(
        UsageRow(
            dim=str(r[0]),
            key=str(r[1]),
            label=str(r[2]),
            model=str(r[3]),
            calls=int(r[4]),
            failed=int(r[5]),
            input_tokens=int(r[6]),
            output_tokens=int(r[7]),
            audio_seconds=float(r[8] or Decimal(0)),
        )
        for r in rows
    )
