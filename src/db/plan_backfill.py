"""Догон строк для старых открытых запросов плана (#1168, спека «Что со старыми запросами»).

Запросы, заведённые до электронного плана, строк не имеют. Открытый запрос без файла и
без строк становится электронным: строки — по нарушениям его проверки, сроки — от
начала отсчёта запроса. Запрос с файлом, принятый и закрытый не трогаются: у них свой
путь. Прогон идемпотентен — запрос, у которого строки уже есть, не берётся. Уведомлений
нет: партнёр о запросе знал, а «запрошен план» второй раз — шум.

Это явная операция владельца базы (`tools/plan_rows_backfill.py`), а не запись при
чтении: открытие экрана данные не меняет. По умолчанию — только счёт («что было бы»).
Работает под ролью УК, мимо охвата: охват у пакетной операции — вся сеть.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import psycopg

from .action_plans import _admin_write
from .errors import ActionPlanError
from .plan_flow import _SIGN_SQL
from .plan_rows import TermsProvider, insert_rows, prepare_rows

logger = logging.getLogger(__name__)

#: Подпись операции в истории запроса.
BACKFILL_ACTOR = "plan-rows-backfill"

_CANDIDATES_SQL = """
select r.id::text, r.inspection_id::text
from action_plan_requests r
where r.status = 'requested'
  and not r.electronic
  and not exists (select 1 from action_plan_files f where f.request_id = r.id)
  and not exists (select 1 from action_plan_rows w where w.request_id = r.id)
order by r.requested_at, r.id
"""

_MAKE_ELECTRONIC_SQL = "update action_plan_requests set electronic = true where id = %s"


@dataclass(frozen=True)
class BackfillReport:
    """Итог прогона: сколько запросов взято, сколько строк заведено и что пропущено."""

    candidates: int
    converted: int
    rows: int
    skipped: tuple[str, ...]
    applied: bool


def backfill_rows(*, terms: TermsProvider, apply: bool = False) -> BackfillReport:
    """Завести строки открытым запросам без файла. `apply=False` — ничего не пишет.

    `terms` — сроки записей от движка (`report.plan_terms.provider`): блок `db` движок
    не зовёт, поставщика даёт инструмент. Запрос, по которому строк не вышло (в проверке
    нет D1–D3) или движок сроков не дал, остаётся файловым и попадает в `skipped` с
    причиной: молча пропущенный запрос — тот, о котором никто не узнает.
    """
    skipped: list[str] = []
    converted = 0
    created_rows = 0
    try:
        with _admin_write("Догнать строки плана") as conn, conn.cursor() as cur:
            cur.execute(_CANDIDATES_SQL)
            candidates = [(str(r[0]), str(r[1])) for r in cur.fetchall()]
            for request_id, inspection_id in candidates:
                try:
                    rows = prepare_rows(cur, inspection_id, terms=terms)
                except ActionPlanError as exc:
                    # Движок сроков не дал (методика издания не читается) — свои не выдумываем.
                    logger.warning("строки запроса %s не собраны: %s", request_id, exc)
                    skipped.append(f"{request_id}: {exc}")
                    continue
                if not rows:
                    skipped.append(f"{request_id}: в проверке нет D1–D3")
                    continue
                if apply:
                    cur.execute(_SIGN_SQL, (BACKFILL_ACTOR,))
                    created_rows += insert_rows(cur, request_id, rows)
                    cur.execute(_MAKE_ELECTRONIC_SQL, (request_id,))
                else:
                    created_rows += len(rows)
                converted += 1
            if apply:
                conn.commit()
    except psycopg.Error as exc:
        raise ActionPlanError(f"Догнать строки плана не удалось ({type(exc).__name__})") from exc
    return BackfillReport(len(candidates), converted, created_rows, tuple(skipped), apply)
