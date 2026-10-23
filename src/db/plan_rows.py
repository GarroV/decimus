"""Строки электронного плана исправлений: модель, чтение, заведение (шаг 2 эпика #1168).

План — не только файл: по каждому нарушению проверки (класс D1–D3, без
рекомендаций) заводится строка — что сделаем, кто отвечает, к какому сроку. Строки
заводит УК в той же транзакции, что и запрос (подтверждение проверки или кнопка),
тяжёлые сверху. Снимок класса, зоны и формулировки лежит в строке: связь с записью
проверки — кодом, формулировка нужна лишь для показа.

**Дни строки — не отсюда.** Их считает движок (`audit.py score`, поле `days` у записи:
дни пункта, не больше потолка класса) — «сроки только через движок» (CLAUDE.md). Блок
`db` движок не зовёт: вызывающий (веб, инструмент) передаёт готовое — `TermsProvider`,
его делает `src/report/plan_terms.py`. Здесь `days` кладётся в строку числом;
действующий срок `due_on` считает база по одной формуле (`plan_row_due`, `0092`) и
держит зеркало в `plan_due.effective_row_due`. «Просрочено» не хранится:
`PlanRow.overdue` считает на чтении.

**Кто что пишет — держит база (`0092`)**, а не этот модуль: партнёр пишет текст
строки и её ход, УК — вердикты. Двери записи — `plan_flow.py`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import psycopg

from src.domain.plan_due import row_due_on

from .errors import ActionPlanError

logger = logging.getLogger(__name__)

ROW_FILLING = "filling"
ROW_IN_WORK = "in_work"
ROW_DONE = "done"
ROW_CONFIRMED = "confirmed"
ROW_RETURNED = "returned"
#: Строка ещё за партнёром: не сделана или сделана, но вернули.
ROW_OPEN_STATUSES = (ROW_FILLING, ROW_IN_WORK, ROW_RETURNED)

#: Пределы текстов — те же, что у ограничений колонок в `0092`.
MAX_MEASURE = 2000
MAX_RESPONSIBLE = 500
MAX_REASON = 2000
MAX_RETURN_REASON = 2000


def row_overdue(status: str, due_on: date, *, today: date) -> bool:
    """Просрочена: срок прошёл, а партнёр не сдал строку (сданная ждёт УК, это не его просрочка)."""
    return status in ROW_OPEN_STATUSES and today > due_on


@dataclass(frozen=True)
class PlanRow:
    """Строка плана в том виде, в каком её рисует экран."""

    id: str
    request_id: str
    finding_id: str
    position: int
    item_code: str
    level: str
    zone: str
    title_ru: str
    title_en: str
    days: int
    measure: str
    responsible: str
    reason: str
    own_due: date | None
    extended_due: date | None
    due_on: date
    status: str
    return_reason: str
    updated_at: datetime

    @property
    def is_filled(self) -> bool:
        """Есть мера и ответственный — минимум, с которым план уходит на согласование."""
        return bool(self.measure.strip() and self.responsible.strip())

    def overdue(self, on: date) -> bool:
        return row_overdue(self.status, self.due_on, today=on)

    def latest_own_due(self, count_from: date) -> date:
        """Самая поздняя дата, которую партнёр может поставить сам: положенный срок строки."""
        return self.extended_due or row_due_on(count_from, self.days)

    def title(self, lang: str) -> str:
        """Формулировка на языке; пусто — на другом, нет ни одной — код пункта."""
        first, second = (
            (self.title_en, self.title_ru) if lang == "en" else (self.title_ru, self.title_en)
        )
        return first or second or self.item_code


@dataclass(frozen=True)
class NewRow:
    """Строка к заведению: снимок записи проверки и дни из методики."""

    finding_id: str
    item_code: str
    level: str
    zone: str
    title_ru: str
    title_en: str
    days: int


_ROWS_SQL = """
select w.id, w.request_id, w.finding_id, w.position, w.item_code, w.level, w.zone,
       w.title_ru, w.title_en, w.days, w.measure, w.responsible, w.reason, w.own_due,
       w.extended_due, w.due_on, w.status, w.return_reason, w.updated_at
from action_plan_rows w
where w.request_id = any(%(ids)s::uuid[])
order by w.request_id, w.position
"""

# Записи проверки, из которых растут строки: нарушения D1–D3, тяжёлые сверху.
# Рекомендации и информационные записи в план не входят.
_FINDINGS_SQL = """
select f.id, f.n, f.code, f.level, f.zone
from findings f
where f.inspection_id = %s and f.level in ('D1', 'D2', 'D3')
order by f.level desc, f.n
"""

_INSERT_ROW_SQL = """
insert into action_plan_rows
    (request_id, finding_id, position, item_code, level, zone, title_ru, title_en, days)
values
    (%(request_id)s, %(finding_id)s, %(position)s, %(item_code)s, %(level)s, %(zone)s,
     %(title_ru)s, %(title_en)s, %(days)s)
"""


def read_rows(cur: psycopg.Cursor[Any], ids: Iterable[str]) -> dict[str, tuple[PlanRow, ...]]:
    """Строки запросов по id запросов. Охват уже наложен вызывающим: id пришли из его чтения."""
    список = list(ids)
    if not список:
        return {}
    cur.execute(_ROWS_SQL, {"ids": список})
    found: dict[str, list[PlanRow]] = {}
    for r in cur.fetchall():
        row = PlanRow(
            id=str(r[0]),
            request_id=str(r[1]),
            finding_id=str(r[2]),
            position=int(r[3]),
            item_code=str(r[4]),
            level=str(r[5]),
            zone=str(r[6]),
            title_ru=str(r[7] or ""),
            title_en=str(r[8] or ""),
            days=int(r[9]),
            measure=str(r[10] or ""),
            responsible=str(r[11] or ""),
            reason=str(r[12] or ""),
            own_due=r[13],
            extended_due=r[14],
            due_on=r[15],
            status=str(r[16]),
            return_reason=str(r[17] or ""),
            updated_at=r[18],
        )
        found.setdefault(row.request_id, []).append(row)
    return {k: tuple(v) for k, v in found.items()}


@dataclass(frozen=True)
class FindingTerms:
    """Что движок сказал о записи проверки: дни на устранение и формулировка пункта."""

    days: int
    title_ru: str
    title_en: str


#: Условия записей проверки от движка: id проверки → {номер записи: условия}. Даёт вызывающий.
TermsProvider = Callable[[str], Mapping[int, FindingTerms]]


def prepare_rows(
    cur: psycopg.Cursor[Any], inspection_id: str, *, terms: TermsProvider | None
) -> tuple[NewRow, ...]:
    """Строки для проверки: по записи D1–D3, дни и формулировки — от движка (`terms`).

    Нарушений нет — пусто (план остаётся файловым). Условий нет (`terms=None`, вызов
    без движка — MCP, сид) — тоже пусто, с предупреждением в журнале: дни строки
    не выдумываем. Движок про запись не сказал (номер не сошёлся) — отказ: молчаливо
    пропущенная строка — нарушение, которое в плане не окажется.
    """
    cur.execute(_FINDINGS_SQL, (inspection_id,))
    записи = cur.fetchall()
    if not записи:
        return ()
    if terms is None:
        logger.warning(
            "проверка %s: условия записей от движка не переданы, план без строк", inspection_id
        )
        return ()
    условия = terms(inspection_id)
    rows = []
    for ident, number, code, level, zone in записи:
        известно = условия.get(int(number))
        if известно is None:
            raise ActionPlanError(
                f"Движок не назвал срок записи {number} проверки: строку плана не завести"
            )
        rows.append(
            NewRow(
                finding_id=str(ident),
                item_code=str(code),
                level=str(level),
                zone=str(zone),
                title_ru=известно.title_ru,
                title_en=известно.title_en,
                days=известно.days,
            )
        )
    return tuple(rows)


def insert_rows(cur: psycopg.Cursor[Any], request_id: str, rows: Iterable[NewRow]) -> int:
    """Положить строки запроса в порядке показа. Роль УК; база сверяет стадию запроса."""
    число = 0
    for number, row in enumerate(rows, start=1):
        cur.execute(
            _INSERT_ROW_SQL,
            {
                "request_id": request_id,
                "finding_id": row.finding_id,
                "position": number,
                "item_code": row.item_code,
                "level": row.level,
                "zone": row.zone,
                "title_ru": row.title_ru or None,
                "title_en": row.title_en or None,
                "days": row.days,
            },
        )
        число += 1
    return число
