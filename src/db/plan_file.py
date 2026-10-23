"""Файл «туда и обратно» электронного плана: сверка строк файла с планом (шаг 3 эпика #1168).

Партнёр выгружает план в xlsx, заполняет «что сделаем», «кто отвечает», «почему», «срок» и
загружает обратно. Разбор файла (граница системы, файл недоверенный) — в вебе
(`src/web/plan_sheet.py`); сюда приходят уже готовые значения. Здесь — чистая сверка с
тем, что на экране, без базы: какие строки файла ложатся в план, какие нет и почему.
Запись идёт той же дверью, что правка на экране (`plan_flow.apply_file_rows`): права и
сторожа базы те же, срок строки проверяется тем же правилом (`plan_due.own_due_problem`).

Файл — вся правда о строке, с которой он спарен (так же, как форма на экране правит
строку целиком): пустая ячейка стирает прежнее значение. Строки плана, которых в файле
нет, не трогаются. Срок, который не принят (не дата, позже положенного, уже прошёл), не
мешает остальным полям строки: они ложатся, срок остаётся прежним.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date

from src.domain.plan_due import own_due_problem

from .plan_rows import MAX_MEASURE, MAX_REASON, MAX_RESPONSIBLE, PlanRow

#: Строка файла без пары: такой строки в плане нет / тот же id второй раз / текст длиннее предела.
SKIP_UNKNOWN = "unknown"
SKIP_DUPLICATE = "duplicate"
SKIP_TOO_LONG = "too_long"

#: Срок строки не принят: не дата. Остальные коды — `plan_due.OWN_DUE_LATE` / `OWN_DUE_PAST`.
DUE_NOT_DATE = "not_date"


@dataclass(frozen=True)
class FileRow:
    """Строка файла, как её прочёл разбор: значения, не формулы."""

    #: Номер строки в файле — для сообщений человеку.
    line: int
    row_id: str
    measure: str
    responsible: str
    reason: str
    due: date | None
    #: В ячейке срока что-то есть, но это не дата.
    due_unreadable: bool = False


@dataclass(frozen=True)
class Change:
    """Что файл меняет в строке: новые значения и строка на экране до них."""

    row: PlanRow
    measure: str
    responsible: str
    reason: str
    own_due: date | None


@dataclass(frozen=True)
class DueRefused:
    """Срок строки не принят: код причины и граница (для «позже» и «уже прошёл»)."""

    position: int
    code: str
    bound: date | None = None


@dataclass(frozen=True)
class Skipped:
    """Строка файла, которую в план не положили."""

    line: int
    code: str


@dataclass(frozen=True)
class Reconciled:
    """Итог сверки файла с планом."""

    #: Строк данных в файле.
    read: int
    changes: tuple[Change, ...]
    #: Спарено и совпало с экраном — писать нечего.
    unchanged: int
    #: Номера строк плана, где после файла нет меры или ответственного.
    unfilled: tuple[int, ...]
    due_refused: tuple[DueRefused, ...]
    skipped: tuple[Skipped, ...]
    #: Номера строк плана, которых в файле нет (остаются как на экране).
    absent: tuple[int, ...]


@dataclass(frozen=True)
class FileApplied:
    """Итог записи файла: сверка и сколько строк легло. Конфликт — ничего не легло."""

    reconciled: Reconciled
    written: int
    #: Ревизия плана не совпала с ожидаемой: план на экране поменяли — ничего не записано.
    conflict: bool
    revision: int


def _own_due(
    file_row: FileRow, row: PlanRow, *, count_from: date, today: date
) -> tuple[date | None, DueRefused | None]:
    """Свой срок строки после файла и отказ, если срок из файла не принят (тогда — прежний)."""
    if file_row.due_unreadable:
        return row.own_due, DueRefused(row.position, DUE_NOT_DATE)
    problem = own_due_problem(
        file_row.due,
        row.own_due,
        count_from=count_from,
        days=row.days,
        extended=row.extended_due,
        today=today,
    )
    if problem is not None:
        code, bound = problem
        return row.own_due, DueRefused(row.position, code, bound)
    return file_row.due, None


def reconcile(
    file_rows: Iterable[FileRow], rows: Sequence[PlanRow], *, count_from: date, today: date
) -> Reconciled:
    """Сверить строки файла со строками плана. Ничего не пишет."""
    by_id = {row.id: row for row in rows}
    seen: set[str] = set()
    changes: list[Change] = []
    refused: list[DueRefused] = []
    skipped: list[Skipped] = []
    unfilled: list[int] = []
    unchanged = 0
    read = 0
    for item in file_rows:
        read += 1
        row = by_id.get(item.row_id)
        if row is None:
            skipped.append(Skipped(item.line, SKIP_UNKNOWN))
            continue
        if item.row_id in seen:
            skipped.append(Skipped(item.line, SKIP_DUPLICATE))
            continue
        seen.add(item.row_id)
        measure, responsible, reason = (
            item.measure.strip(),
            item.responsible.strip(),
            item.reason.strip(),
        )
        if (
            len(measure) > MAX_MEASURE
            or len(responsible) > MAX_RESPONSIBLE
            or len(reason) > MAX_REASON
        ):
            skipped.append(Skipped(item.line, SKIP_TOO_LONG))
            continue
        own_due, refusal = _own_due(item, row, count_from=count_from, today=today)
        if refusal is not None:
            refused.append(refusal)
        if not measure or not responsible:
            unfilled.append(row.position)
        current = (row.measure, row.responsible, row.reason, row.own_due)
        if (measure, responsible, reason, own_due) == current:
            unchanged += 1
        else:
            changes.append(Change(row, measure, responsible, reason, own_due))
    absent = tuple(row.position for row in rows if row.id not in seen)
    return Reconciled(
        read=read,
        changes=tuple(changes),
        unchanged=unchanged,
        unfilled=tuple(unfilled),
        due_refused=tuple(refused),
        skipped=tuple(skipped),
        absent=absent,
    )
