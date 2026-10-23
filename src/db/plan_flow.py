"""Ход электронного плана исправлений: заполнение, согласование, выполнение (#1168).

Путь: **заполнение** (партнёр правит строки) → «на согласование» → **согласование**
(УК принимает или возвращает с комментарием) → **в работе** (по строке партнёр
«взял в работу» и «сделано», УК «подтвердить» или «вернуть» с причиной) → **закрыт**,
когда подтверждены все строки.

**Кто что — держит база (`0092`)**, а не эти двери: партнёр пишет только текст строки
и её ход, и только строки своей страны; вердикты и закрытие — роль УК. Здесь —
понятные человеку отказы до похода в базу, охват и уведомления внутри приложения
(`plan_notify`), которые ложатся той же транзакцией, что и переход.

Двери партнёра идут ролью приложения, двери УК — администратором истории, как в
`action_plans`. Каждый переход подписан (`decimus.plan_actor`): без подписи база
отказывает, а история получает автора.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Collection, Sequence
from datetime import date
from typing import Any

import psycopg

from src.domain.plan_due import OWN_DUE_LATE, own_due_problem, plan_due_on
from src.domain.tenants import HQ_TENANT

from . import plan_notify as note
from .action_plans import (
    STATUS_IN_WORK,
    STATUS_ON_REVIEW,
    STATUS_REQUESTED,
    _actor,
    _admin_write,
    _translate,
    _uuid_or_none,
    locked_head,
    today,
)
from .config import check_environment
from .errors import ActionPlanError
from .plan_file import FileApplied, FileRow, reconcile
from .plan_rows import (
    MAX_MEASURE,
    MAX_REASON,
    MAX_RESPONSIBLE,
    MAX_RETURN_REASON,
    ROW_CONFIRMED,
    ROW_DONE,
    ROW_FILLING,
    ROW_IN_WORK,
    ROW_RETURNED,
    read_rows,
)
from .pool import connection
from .reach import REACH_SQL, Reach, require_reach

logger = logging.getLogger(__name__)

# Подпись перехода: настройка транзакции, как у срока в 0036.
_SIGN_SQL = "select set_config('decimus.plan_actor', %s, true)"

# Запрос плана для партнёра: охват накладывает вызывающий, замок — на строку запроса.
_PLAN_FOR_PARTNER_SQL = f"""
select r.status, r.electronic
from action_plan_requests r
join inspections i on i.id = r.inspection_id
join units u on u.id = i.unit_id
where {REACH_SQL}
  and i.retracted_at is null
  and r.id = %(request)s
for update of r
"""  # noqa: S608 — в склейке только условие охвата модуля, данные идут параметрами

# Запрос плана под файл: то же охват и замок, плюс начало отсчёта и ревизия.
_PLAN_FOR_FILE_SQL = f"""
select r.status, r.electronic, r.count_from, r.revision
from action_plan_requests r
join inspections i on i.id = r.inspection_id
join units u on u.id = i.unit_id
where {REACH_SQL}
  and i.retracted_at is null
  and r.id = %(request)s
for update of r
"""  # noqa: S608 — в склейке только условие охвата модуля, данные идут параметрами

# Строка плана для партнёра: то же охват и замок, плюс то, чем считается срок и ход.
_ROW_FOR_PARTNER_SQL = f"""
select r.status, r.electronic, r.count_from, w.days, w.extended_due, w.status, w.own_due
from action_plan_rows w
join action_plan_requests r on r.id = w.request_id
join inspections i on i.id = r.inspection_id
join units u on u.id = i.unit_id
where {REACH_SQL}
  and i.retracted_at is null
  and r.id = %(request)s and w.id = %(row)s
for update of w
"""  # noqa: S608 — в склейке только условие охвата модуля, данные идут параметрами

_UNFILLED_SQL = """
select count(*) filter (
           where btrim(coalesce(measure, '')) = '' or btrim(coalesce(responsible, '')) = ''
       ),
       count(*)
from action_plan_rows
where request_id = %s
"""

_SET_PLAN_STATUS_SQL = """
update action_plan_requests set status = %(status)s, review_comment = %(comment)s
where id = %(id)s
"""
_SET_PLAN_STATUS_KEEP_SQL = "update action_plan_requests set status = %(status)s where id = %(id)s"

_UPDATE_TEXT_SQL = """
update action_plan_rows
set measure = %(measure)s, responsible = %(responsible)s, reason = %(reason)s,
    own_due = %(own_due)s
where id = %(row)s
"""
_SET_ROW_STATUS_SQL = "update action_plan_rows set status = %(status)s where id = %(row)s"
_RETURN_ROW_SQL = """
update action_plan_rows set status = 'returned', return_reason = %(reason)s where id = %(row)s
"""

_ROW_OF_REQUEST_SQL = (
    "select status from action_plan_rows where id = %s and request_id = %s for update"
)
_OPEN_ROWS_SQL = (
    "select count(*) from action_plan_rows where request_id = %s and status <> 'confirmed'"
)

_COUNT_FROM_SQL = """
update action_plan_requests set count_from = %(count_from)s, due_on = %(due_on)s
where id = %(id)s
"""


def _clean(value: str | None, limit: int, what: str) -> str | None:
    """Текст поля: без пробелов по краям, пусто — `None`, длиннее предела — отказ, не обрезка."""
    text = (value or "").strip()
    if len(text) > limit:
        raise ActionPlanError(f"{what} длиннее {limit} знаков — сократите")
    return text or None


def own_due_message(own_due: date | None, code: str, bound: date) -> str:
    """Отказ по своему сроку строки словами — для формы на экране."""
    if code == OWN_DUE_LATE:
        return (
            f"Срок {own_due} позже положенного ({bound.isoformat()}). "
            f"Позже срок ставится только переносом с согласием УК"
        )
    return f"Срок {own_due} уже прошёл — назовите будущую дату"


def _ids(request_id: str, row_id: str | None = None) -> tuple[str, str | None]:
    request = _uuid_or_none(request_id)
    if request is None:
        raise ActionPlanError("Запроса нет")
    if row_id is None:
        return request, None
    row = _uuid_or_none(row_id)
    if row is None:
        raise ActionPlanError("Строки нет")
    return request, row


def _require_partner(tenant: str) -> None:
    if tenant == HQ_TENANT:
        raise ActionPlanError("План заполняет партнёр страны, а не УК")


# ── Двери партнёра (роль приложения) ───────────────────────────────────────


def _as_partner(what: str, work: Callable[[psycopg.Cursor[Any]], None]) -> None:
    """Транзакция партнёра: `work` идёт на одном курсоре, затем коммит; отказ базы — понятный."""
    try:
        with connection(check_environment().dsn) as conn, conn.cursor() as cur:
            work(cur)
            conn.commit()
    except psycopg.Error as exc:
        raise _translate(what, exc) from exc


class _Keep:
    """Поле не названо: остаётся как в строке (отличается от «названо пустым» — стереть)."""

    def __repr__(self) -> str:
        return "KEEP"


KEEP = _Keep()

_CURRENT_TEXT_SQL = "select measure, responsible, reason from action_plan_rows where id = %s"


def save_row(
    request_id: str,
    row_id: str,
    *,
    reach: Reach,
    tenant: str,
    actor: str,
    measure: str | None,
    responsible: str | None,
    reason: str | None,
    own_due: date | None,
) -> None:
    """Записать меру, ответственного, причину и свой срок строки. Только пока план в заполнении.

    Свой срок — не позже положенного (дни из методики от начала отсчёта) и не раньше
    начала отсчёта; позже срок ставится только переносом с согласием УК. Пустые поля
    стирают прежнее: партнёр правит строку целиком.
    """
    _write_row(
        request_id,
        row_id,
        reach=reach,
        tenant=tenant,
        actor=actor,
        measure=measure,
        responsible=responsible,
        reason=reason,
        own_due=own_due,
    )


def patch_row(
    request_id: str,
    row_id: str,
    *,
    reach: Reach,
    tenant: str,
    actor: str,
    measure: str | _Keep | None = KEEP,
    responsible: str | _Keep | None = KEEP,
    reason: str | _Keep | None = KEEP,
    own_due: date | _Keep | None = KEEP,
) -> None:
    """Частичная правка строки: названные поля пишутся, остальные остаются как есть.

    Текущая строка читается под тем же замком, что и запись (`save_row`), поэтому
    параллельная правка не теряется; права, охват, сторожа и срок — те же. Названное
    `None` или пустая строка стирает поле. Для агента: веб пишет строку целиком, а тот,
    кто назвал одну меру, не должен стереть ответственного.
    """
    _write_row(
        request_id,
        row_id,
        reach=reach,
        tenant=tenant,
        actor=actor,
        measure=measure,
        responsible=responsible,
        reason=reason,
        own_due=own_due,
    )


def _write_row(
    request_id: str,
    row_id: str,
    *,
    reach: Reach,
    tenant: str,
    actor: str,
    measure: str | _Keep | None,
    responsible: str | _Keep | None,
    reason: str | _Keep | None,
    own_due: date | _Keep | None,
) -> None:
    _actor(actor)
    _require_partner(tenant)
    request, row = _ids(request_id, row_id)
    named: dict[str, str | _Keep | None] = {
        "measure": measure if isinstance(measure, _Keep) else _clean(measure, MAX_MEASURE, "Мера"),
        "responsible": responsible
        if isinstance(responsible, _Keep)
        else _clean(responsible, MAX_RESPONSIBLE, "Ответственный"),
        "reason": reason if isinstance(reason, _Keep) else _clean(reason, MAX_REASON, "Причина"),
    }

    def work(cur: psycopg.Cursor[Any]) -> None:
        head = _partner_row(cur, reach, request, row)
        plan_status, _electronic, count_from, days, extended, _row_status, before = head
        if plan_status != STATUS_REQUESTED:
            raise ActionPlanError("План уже отправлен на согласование — строки больше не правятся")
        cur.execute(_CURRENT_TEXT_SQL, (row,))
        current = cur.fetchone()
        texts = dict(
            zip(("measure", "responsible", "reason"), current or (None, None, None), strict=True)
        )
        данные: dict[str, Any] = {
            name: texts[name] if isinstance(value, _Keep) else value
            for name, value in named.items()
        }
        новый_срок = before if isinstance(own_due, _Keep) else own_due
        проблема = own_due_problem(
            новый_срок, before, count_from=count_from, days=days, extended=extended, today=today()
        )
        if проблема is not None:
            raise ActionPlanError(own_due_message(новый_срок, *проблема))
        cur.execute(_UPDATE_TEXT_SQL, {**данные, "own_due": новый_срок, "row": row})

    _as_partner("Сохранить строку плана", work)


def apply_file_rows(
    request_id: str,
    *,
    reach: Reach,
    tenant: str,
    actor: str,
    file_rows: Sequence[FileRow],
    expected_revision: int,
    take: Collection[str] | None = None,
) -> FileApplied:
    """Положить строки файла в план — той же записью, что правка на экране, одной транзакцией.

    Сверка идёт под замком запроса. Ревизия плана не равна `expected_revision` (в файле — та,
    на которой его выгрузили; при выборе — та, на которой показали разницу) — план на экране
    поменяли: ничего не пишется, результат говорит `conflict`. `take` — какие строки взять
    из файла (id строк плана); `None` — все, что отличаются от экрана. Строки, совпавшие с
    экраном, не пишутся: каждая запись растит ревизию. Срок, не принятый сверкой, остаётся
    прежним; остальное ложится. Права и порядок держит база, как у `save_row`.
    """
    _actor(actor)
    _require_partner(tenant)
    request, _ = _ids(request_id)
    outcome: list[FileApplied] = []

    def work(cur: psycopg.Cursor[Any]) -> None:
        cur.execute(_PLAN_FOR_FILE_SQL, {**require_reach(reach).params(), "request": request})
        head = cur.fetchone()
        if head is None:
            raise ActionPlanError("Запроса нет")
        status, electronic, count_from, revision = head
        if not electronic:
            raise ActionPlanError("План не электронный — строк в нём нет")
        if status != STATUS_REQUESTED:
            raise ActionPlanError("План уже отправлен на согласование — строки больше не правятся")
        rows = read_rows(cur, [request]).get(request, ())
        result = reconcile(file_rows, rows, count_from=count_from, today=today())
        if int(revision) != expected_revision:
            outcome.append(FileApplied(result, 0, True, int(revision)))
            return
        chosen = [c for c in result.changes if take is None or c.row.id in take]
        for change in chosen:
            cur.execute(
                _UPDATE_TEXT_SQL,
                {
                    "row": change.row.id,
                    "measure": change.measure or None,
                    "responsible": change.responsible or None,
                    "reason": change.reason or None,
                    "own_due": change.own_due,
                },
            )
        outcome.append(FileApplied(result, len(chosen), False, int(revision)))

    _as_partner("Загрузить файл плана", work)
    return outcome[0]


def _partner_row(
    cur: psycopg.Cursor[Any], reach: Reach, request: str, row: str | None
) -> tuple[Any, ...]:
    cur.execute(
        _ROW_FOR_PARTNER_SQL, {**require_reach(reach).params(), "request": request, "row": row}
    )
    head = cur.fetchone()
    if head is None:
        raise ActionPlanError("Строки нет")
    if not head[1]:
        raise ActionPlanError("План не электронный — строк в нём нет")
    return tuple(head)


def submit_plan(request_id: str, *, reach: Reach, tenant: str, actor: str) -> None:
    """Отправить заполненный план на согласование: у каждой строки есть мера и ответственный."""
    who = _actor(actor)
    _require_partner(tenant)
    request, _ = _ids(request_id)

    def work(cur: psycopg.Cursor[Any]) -> None:
        cur.execute(_PLAN_FOR_PARTNER_SQL, {**require_reach(reach).params(), "request": request})
        head = cur.fetchone()
        if head is None:
            raise ActionPlanError("Запроса нет")
        if not head[1]:
            raise ActionPlanError("План не электронный — на согласование его не отправляют")
        if head[0] != STATUS_REQUESTED:
            raise ActionPlanError("План уже на согласовании или принят")
        cur.execute(_UNFILLED_SQL, (request,))
        unfilled, total = cur.fetchone() or (0, 0)
        if not total:
            raise ActionPlanError("В плане нет строк — отправлять нечего")
        if unfilled:
            raise ActionPlanError(
                f"Не у каждой строки есть мера и ответственный: не заполнено {unfilled} из {total}"
            )
        cur.execute(_SIGN_SQL, (who,))
        cur.execute(_SET_PLAN_STATUS_KEEP_SQL, {"id": request, "status": STATUS_ON_REVIEW})
        note.notify_event(cur, note.KIND_SUBMITTED, request, actor=who, actor_tenant=tenant)

    _as_partner("Отправить план на согласование", work)


def _move_row(
    request_id: str,
    row_id: str,
    *,
    reach: Reach,
    tenant: str,
    actor: str,
    allowed_from: tuple[str, ...],
    to: str,
    refusal: str,
    kind: str | None,
) -> None:
    who = _actor(actor)
    _require_partner(tenant)
    request, row = _ids(request_id, row_id)

    def work(cur: psycopg.Cursor[Any]) -> None:
        plan_status, _e, _c, _d, _x, row_status, _own = _partner_row(cur, reach, request, row)
        if plan_status != STATUS_IN_WORK:
            raise ActionPlanError("План ещё не принят — строки в работу берут после согласования")
        if row_status not in allowed_from:
            raise ActionPlanError(refusal)
        cur.execute(_SIGN_SQL, (who,))
        cur.execute(_SET_ROW_STATUS_SQL, {"status": to, "row": row})
        if kind is not None:
            note.notify_event(cur, kind, request, actor=who, actor_tenant=tenant, row_id=row)

    _as_partner("Отметить строку плана", work)


def start_row(request_id: str, row_id: str, *, reach: Reach, tenant: str, actor: str) -> None:
    """«Взяли в работу»: строка принятого плана из заполнения — в работу."""
    _move_row(
        request_id,
        row_id,
        reach=reach,
        tenant=tenant,
        actor=actor,
        allowed_from=(ROW_FILLING,),
        to=ROW_IN_WORK,
        refusal="Строка уже в работе или сдана",
        kind=None,
    )


def finish_row(request_id: str, row_id: str, *, reach: Reach, tenant: str, actor: str) -> None:
    """«Сделано»: строка в работе (или возвращённая) уходит на подтверждение УК."""
    _move_row(
        request_id,
        row_id,
        reach=reach,
        tenant=tenant,
        actor=actor,
        allowed_from=(ROW_IN_WORK, ROW_RETURNED),
        to=ROW_DONE,
        refusal="Сначала возьмите строку в работу",
        kind=note.KIND_ROW_DONE,
    )


# ── Двери УК (администратор истории) ───────────────────────────────────────


def accept_plan(request_id: str, *, actor: str) -> None:
    """Принять заполненный план: он идёт в работу."""
    who = _actor(actor)
    request, _ = _ids(request_id)
    try:
        with _admin_write("Принять план") as conn, conn.cursor() as cur:
            _require_on_review(cur, request)
            cur.execute(_SIGN_SQL, (who,))
            cur.execute(_SET_PLAN_STATUS_KEEP_SQL, {"id": request, "status": STATUS_IN_WORK})
            note.notify_event(cur, note.KIND_ACCEPTED, request, actor=who, actor_tenant=HQ_TENANT)
            conn.commit()
    except psycopg.Error as exc:
        raise _translate("Принять план", exc) from exc


def return_plan(request_id: str, *, actor: str, comment: str) -> None:
    """Вернуть план партнёру на доработку; комментарий обязателен: что исправить."""
    who = _actor(actor)
    text = _clean(comment, MAX_REASON, "Комментарий")
    if text is None:
        raise ActionPlanError("Вернуть план можно только с комментарием: что исправить")
    request, _ = _ids(request_id)
    try:
        with _admin_write("Вернуть план") as conn, conn.cursor() as cur:
            _require_on_review(cur, request)
            cur.execute(_SIGN_SQL, (who,))
            cur.execute(
                _SET_PLAN_STATUS_SQL, {"id": request, "status": STATUS_REQUESTED, "comment": text}
            )
            note.notify_event(cur, note.KIND_RETURNED, request, actor=who, actor_tenant=HQ_TENANT)
            conn.commit()
    except psycopg.Error as exc:
        raise _translate("Вернуть план", exc) from exc


def _require_on_review(cur: psycopg.Cursor[Any], request: str) -> None:
    status, electronic = locked_head(cur, request)
    if not electronic:
        raise ActionPlanError("План файловый: его принимают и возвращают по версии файла")
    if status != STATUS_ON_REVIEW:
        raise ActionPlanError("План не на согласовании — принимать или возвращать нечего")


def _verdict_on_row(
    request_id: str, row_id: str, *, actor: str, reason: str | None, what: str
) -> None:
    """Вердикт УК по сданной строке; подтверждена последняя — план закрывается."""
    who = _actor(actor)
    request, row = _ids(request_id, row_id)
    confirm = reason is None
    try:
        with _admin_write(what) as conn, conn.cursor() as cur:
            plan_status, electronic = locked_head(cur, request)
            if not electronic or plan_status != STATUS_IN_WORK:
                raise ActionPlanError("План не в работе — строки не подтверждают")
            cur.execute(_ROW_OF_REQUEST_SQL, (row, request))
            current = cur.fetchone()
            if current is None:
                raise ActionPlanError("Строки нет")
            if current[0] != ROW_DONE:
                raise ActionPlanError("Строка не сдана — подтверждать или возвращать нечего")
            cur.execute(_SIGN_SQL, (who,))
            if confirm:
                cur.execute(_SET_ROW_STATUS_SQL, {"status": ROW_CONFIRMED, "row": row})
                cur.execute(_OPEN_ROWS_SQL, (request,))
                left = cur.fetchone()
                if left is not None and int(left[0]) == 0:
                    cur.execute(_SET_PLAN_STATUS_KEEP_SQL, {"id": request, "status": "closed"})
            else:
                cur.execute(_RETURN_ROW_SQL, {"reason": reason, "row": row})
            note.notify_event(
                cur,
                note.KIND_ROW_CONFIRMED if confirm else note.KIND_ROW_RETURNED,
                request,
                actor=who,
                actor_tenant=HQ_TENANT,
                row_id=row,
            )
            conn.commit()
    except psycopg.Error as exc:
        raise _translate(what, exc) from exc


def confirm_row(request_id: str, row_id: str, *, actor: str) -> None:
    """Подтвердить сданную строку. Подтверждены все — план закрыт."""
    _verdict_on_row(request_id, row_id, actor=actor, reason=None, what="Подтвердить строку")


def return_row(request_id: str, row_id: str, *, actor: str, reason: str) -> None:
    """Вернуть сданную строку партнёру; причина обязательна."""
    text = _clean(reason, MAX_RETURN_REASON, "Причина")
    if text is None:
        raise ActionPlanError("Вернуть строку можно только с причиной: что не так")
    _verdict_on_row(request_id, row_id, actor=actor, reason=text, what="Вернуть строку")


def set_count_from(request_id: str, *, actor: str, count_from: date) -> None:
    """Начало отсчёта срока (D613): сдвигает срок ответа и сроки всех строк, кроме перенесённых.

    Принятый файловый и закрытый план не правятся. Срок ответа пересчитывается от
    новой даты по методике; ручную правку срока (D274) новая дата перекрывает.
    """
    who = _actor(actor)
    request, _ = _ids(request_id)
    try:
        with _admin_write("Сдвинуть начало отсчёта") as conn, conn.cursor() as cur:
            status, _electronic = locked_head(cur, request)
            if status in ("accepted", "closed"):
                raise ActionPlanError("План уже принят — начало отсчёта не правится")
            cur.execute(_SIGN_SQL, (who,))
            cur.execute(
                _COUNT_FROM_SQL,
                {"id": request, "count_from": count_from, "due_on": plan_due_on(count_from)},
            )
            conn.commit()
    except psycopg.Error as exc:
        raise _translate("Сдвинуть начало отсчёта", exc) from exc
