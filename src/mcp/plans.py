"""Электронный план исправлений через Claude (#1168, шаг 6; D620).

Всё, что делается с планом в вебе и боте, делается и здесь — теми же дверьми:
читает `src.db.action_plans`, пишет `src.db.plan_flow`. Своего SQL нет, как нет и
своих прав: вердикты УК (`plan.manage`) и работа партнёра (`plan.submit`) решает
матрица ролей на входе (`policy.TOOL_ACTIONS`), а переходы и охват — те же двери и
сторожа базы (`0092`). Уведомления внутри приложения пишут сами двери.

**Охват — по токену.** Аргумента `tenant` нет: чьё пространство, говорит токен
(`reach_of`). Партнёр видит планы своих стран, УК — всех; чужой план отвечает так же,
как несуществующий.

**Ответы короткие** (как после #1016). Список — по строке на план со счётчиками; план —
шапка и строки без снимков записей и без пустых полей; запись отвечает статусом плана,
счётчиком строк по статусам и той строкой, которой коснулись, — не всем планом.

**Заполнение строки не стирает то, чего не назвали.** Дверь веба `save_row` пишет строку
целиком (пустое поле стирает прежнее); агенту, который назвал одну меру, это стёрло бы
ответственного. Поэтому здесь неназванное поле берётся из строки как есть, а стереть можно
только названной пустой строкой.
"""

from __future__ import annotations

from collections import Counter
from datetime import date
from typing import TYPE_CHECKING, Any

from ..db.errors import ActionPlanError, DbError
from ..db.errors import ConfigError as DbConfigError
from .db_target import config_refusal
from .errors import ToolError
from .tools import _parse_date

if TYPE_CHECKING:
    from ..db.action_plans import PlanRequest
    from ..db.plan_rows import PlanRow

NOT_CONNECTED = (
    "Планы исправлений на этом стенде не подключены: не задана переменная окружения базы "
    "(DATABASE_URL для чтения и работы партнёра, DATABASE_RETRACTION_URL для вердиктов УК). "
    "Это отказ настройки, а не отсутствие планов"
)
READ_FAILED = "Планы не прочитались: база отказала. Это отказ чтения, а не отсутствие планов"
NO_PLAN = "Плана нет (или он вне вашего охвата)"
NO_ROW = "В этом плане такой строки нет"
NOTHING_TO_FILL = "Нечего записывать: назовите measure, responsible, reason или own_due"

#: Статусы плана — те же, что `src.db.action_plans.STATUSES` (сверяет тест): каталог не
#: тянет блок `db` при импорте, а схема инструмента перечисляет их сразу.
PLAN_STATUSES = ("requested", "on_review", "accepted", "in_work", "closed")
#: Читающие инструменты плана: автора не берут и в журнал действий не идут
#: (`rpc._call_tool`, `audit.READ_ONLY_TOOLS`). Остальные инструменты вида пишут.
READ_TOOLS = frozenset({"list_action_plans", "get_action_plan"})
DEFAULT_LIMIT = 50
MAX_LIMIT = 200
#: Текст строки в ответе плана режется по этому числу знаков, а полный — в вебе: ответ
#: уходит в модель, а мера и причина бывают в две тысячи знаков каждая.
SHOWN_TEXT = 300


def _cut(text: str) -> str:
    return text if len(text) <= SHOWN_TEXT else text[: SHOWN_TEXT - 1].rstrip() + "…"


def _row_view(row: PlanRow, *, on: date) -> dict[str, Any]:
    """Строка плана в ответе: без снимков и пустых полей, срок — действующий."""
    view: dict[str, Any] = {
        "id": row.id,
        "n": row.position,
        "code": row.item_code,
        "level": row.level,
        "zone": row.zone,
        "title": _cut(row.title("ru")),
        "status": row.status,
        "due_on": row.due_on.isoformat(),
        "overdue": row.overdue(on),
    }
    for name, value in (
        ("measure", row.measure),
        ("responsible", row.responsible),
        ("reason", row.reason),
        ("return_reason", row.return_reason),
    ):
        if value.strip():
            view[name] = _cut(value)
    if row.own_due is not None:
        view["own_due"] = row.own_due.isoformat()
    if row.extended_due is not None:
        view["extended_due"] = row.extended_due.isoformat()
    return view


def _row_counts(item: PlanRequest) -> dict[str, int]:
    """Строки по статусам — только те, что есть."""
    return dict(Counter(row.status for row in item.rows))


def _head(item: PlanRequest, *, on: date) -> dict[str, Any]:
    head: dict[str, Any] = {
        "id": item.id,
        "unit": item.unit_name,
        "country": item.country,
        "inspection_date": item.inspection_date.isoformat(),
        "grade": item.grade,
        "status": item.status,
        "state": item.state,
        "due_on": item.due_on.isoformat(),
        "overdue": item.overdue(on),
        "count_from": item.count_from.isoformat(),
        "electronic": item.electronic,
    }
    if item.electronic:
        head["rows"] = {
            "total": len(item.rows),
            "filled": item.filled_rows,
            "overdue": item.overdue_rows(on),
            "by_status": _row_counts(item),
        }
    return head


def _read(work: Any) -> Any:
    """Чтение планов: отказ окружения и базы — отказом инструмента, а не сбоем разбора."""
    try:
        return work()
    except DbConfigError as exc:
        raise config_refusal(exc, NOT_CONNECTED) from None
    except DbError as exc:
        raise ToolError(f"{READ_FAILED} ({type(exc).__name__})") from None


# ── Чтение ──────────────────────────────────────────────────────────────────


def list_action_plans(
    *,
    tenant: str,
    status: str | None = None,
    country: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, object]:
    """Планы в охвате токена: открытые по сроку; принятые и закрытые — по названному статусу."""
    from ..db import action_plans as plans
    from ..db.reach import reach_of

    if status is not None and status not in PLAN_STATUSES:
        raise ToolError(f"Статус «{status}» не знаком. Есть: {', '.join(PLAN_STATUSES)}")
    if not 1 <= limit <= MAX_LIMIT:
        raise ToolError(f"limit от 1 до {MAX_LIMIT}: так ответ остаётся коротким")
    код_страны = (country or "").strip().upper() or None
    reach = _read(lambda: reach_of(tenant))
    выдача = _read(
        lambda: plans.list_requests(
            reach=reach,
            country=код_страны,
            accepted=status in plans.FINISHED_STATUSES,
        )
    )
    сегодня = plans.today()
    найденные = [item for item in выдача.rows if status is None or item.status == status]
    return {
        "plans": [_head(item, on=сегодня) for item in найденные[:limit]],
        "total": len(найденные),
        "truncated": выдача.truncated or len(найденные) > limit,
        "today": сегодня.isoformat(),
        "note": (
            "Без status — только открытые (ждут строк, согласования или работы); принятые и "
            "закрытые — status=accepted или closed. overdue считается на сегодня"
        ),
    }


def get_action_plan(*, tenant: str, request_id: str) -> dict[str, object]:
    """Один план: шапка, комментарий последнего возврата и строки с сроками и просрочкой."""
    from ..db import action_plans as plans
    from ..db.reach import reach_of

    reach = _read(lambda: reach_of(tenant))
    item = _read(lambda: plans.get_request(request_id, reach=reach))
    if item is None:
        raise ToolError(NO_PLAN)
    сегодня = plans.today()
    ответ: dict[str, Any] = _head(item, on=сегодня)
    if item.last_comment:
        ответ["return_comment"] = _cut(item.last_comment)
    ответ["rows"] = [_row_view(row, on=сегодня) for row in item.rows]
    if not item.electronic:
        ответ["note"] = (
            "Файловый план: строк нет, его принимают и возвращают по версии файла в вебе"
        )
    return ответ


# ── Запись: общий каркас ────────────────────────────────────────────────────


def _written(
    tenant: str, request_id: str, note: str, *, row_id: str | None = None
) -> dict[str, object]:
    """Короткий ответ записи: статус плана, строки по статусам, затронутая строка.

    Запись уже прошла; не прочитали её итог — ответ скромнее, но не отказ: агент не должен
    пересказать человеку «не удалось» про то, что сделано.
    """
    from ..db import action_plans as plans
    from ..db.reach import reach_of

    ответ: dict[str, object] = {"request_id": request_id, "note": note}
    try:
        item = plans.get_request(request_id, reach=reach_of(tenant))
    except DbError:
        ответ["warning"] = "Записано, но итог не прочитался: проверьте get_action_plan"
        return ответ
    if item is None:
        return ответ
    ответ["status"] = item.status
    if item.electronic:
        ответ["rows_by_status"] = _row_counts(item)
    if row_id is not None:
        строка = next((row for row in item.rows if row.id == row_id), None)
        if строка is not None:
            ответ["row"] = _row_view(строка, on=plans.today())
    return ответ


def _door(what: str, call: Any) -> None:
    """Вызов двери: её отказ — словами человеку, окружение — «не подключено»."""
    try:
        call()
    except ActionPlanError as exc:
        raise ToolError(str(exc)) from None
    except DbConfigError as exc:
        raise config_refusal(exc, NOT_CONNECTED) from None
    except DbError as exc:
        raise ToolError(f"{what} не удалось ({type(exc).__name__}). Ничего не изменено") from None


# ── Запись: вердикты УК ─────────────────────────────────────────────────────


def accept_action_plan(*, tenant: str, actor: str, request_id: str) -> dict[str, object]:
    """Принять заполненный план: он идёт в работу."""
    from ..db import plan_flow as flow

    _door("Принять план", lambda: flow.accept_plan(request_id, actor=actor))
    return _written(tenant, request_id, "plan accepted; it is in work, the partner is notified")


def return_action_plan(
    *, tenant: str, actor: str, request_id: str, comment: str
) -> dict[str, object]:
    """Вернуть план партнёру на доработку: комментарий обязателен."""
    from ..db import plan_flow as flow

    _door("Вернуть план", lambda: flow.return_plan(request_id, actor=actor, comment=comment))
    return _written(tenant, request_id, "plan returned for rework; the partner is notified")


def confirm_plan_row(*, tenant: str, actor: str, request_id: str, row_id: str) -> dict[str, object]:
    """Подтвердить сданную строку; подтверждены все — план закрыт."""
    from ..db import plan_flow as flow

    _door("Подтвердить строку", lambda: flow.confirm_row(request_id, row_id, actor=actor))
    return _written(tenant, request_id, "row confirmed", row_id=row_id)


def return_plan_row(
    *, tenant: str, actor: str, request_id: str, row_id: str, reason: str
) -> dict[str, object]:
    """Вернуть сданную строку партнёру: причина обязательна."""
    from ..db import plan_flow as flow

    _door("Вернуть строку", lambda: flow.return_row(request_id, row_id, actor=actor, reason=reason))
    return _written(tenant, request_id, "row returned to the partner", row_id=row_id)


def set_plan_count_from(
    *, tenant: str, actor: str, request_id: str, count_from: str
) -> dict[str, object]:
    """Сдвинуть начало отсчёта: срок плана и сроки строк (кроме перенесённых) считаются заново."""
    from ..db import plan_flow as flow

    начало = _parse_date(count_from, field="count_from")
    if начало is None:
        raise ToolError("Назовите count_from датой ГГГГ-ММ-ДД")
    _door(
        "Сдвинуть начало отсчёта",
        lambda: flow.set_count_from(request_id, actor=actor, count_from=начало),
    )
    return _written(tenant, request_id, "count-from moved; due dates recalculated")


# ── Запись: партнёр ─────────────────────────────────────────────────────────


def fill_plan_row(
    *,
    tenant: str,
    actor: str,
    request_id: str,
    row_id: str,
    measure: str | None = None,
    responsible: str | None = None,
    reason: str | None = None,
    own_due: str | None = None,
) -> dict[str, object]:
    """Записать меру, ответственного, причину и свой срок строки; неназванное остаётся как есть."""
    from ..db import action_plans as plans
    from ..db import plan_flow as flow
    from ..db.reach import reach_of

    if measure is None and responsible is None and reason is None and own_due is None:
        raise ToolError(NOTHING_TO_FILL)
    срок = _parse_date(own_due, field="own_due") if own_due is not None else None
    item = _read(lambda: plans.get_request(request_id, reach=reach_of(tenant)))
    if item is None:
        raise ToolError(NO_PLAN)
    строка = next((row for row in item.rows if row.id == row_id), None)
    if строка is None:
        raise ToolError(NO_ROW)
    _door(
        "Сохранить строку плана",
        lambda: flow.save_row(
            request_id,
            row_id,
            reach=reach_of(tenant),
            tenant=tenant,
            actor=actor,
            measure=строка.measure if measure is None else measure,
            responsible=строка.responsible if responsible is None else responsible,
            reason=строка.reason if reason is None else reason,
            own_due=строка.own_due if own_due is None else срок,
        ),
    )
    return _written(tenant, request_id, "row saved", row_id=row_id)


def submit_action_plan(*, tenant: str, actor: str, request_id: str) -> dict[str, object]:
    """Отправить заполненный план на согласование: у каждой строки есть мера и ответственный."""
    from ..db import plan_flow as flow
    from ..db.reach import reach_of

    _door(
        "Отправить план на согласование",
        lambda: flow.submit_plan(request_id, reach=reach_of(tenant), tenant=tenant, actor=actor),
    )
    return _written(tenant, request_id, "plan sent for review; the management company is notified")


def start_plan_row(*, tenant: str, actor: str, request_id: str, row_id: str) -> dict[str, object]:
    """«Взяли в работу»: строка принятого плана — в работу."""
    from ..db import plan_flow as flow
    from ..db.reach import reach_of

    _door(
        "Отметить строку плана",
        lambda: flow.start_row(
            request_id, row_id, reach=reach_of(tenant), tenant=tenant, actor=actor
        ),
    )
    return _written(tenant, request_id, "row is in work", row_id=row_id)


def finish_plan_row(*, tenant: str, actor: str, request_id: str, row_id: str) -> dict[str, object]:
    """«Сделано»: строка уходит на подтверждение УК."""
    from ..db import plan_flow as flow
    from ..db.reach import reach_of

    _door(
        "Отметить строку плана",
        lambda: flow.finish_row(
            request_id, row_id, reach=reach_of(tenant), tenant=tenant, actor=actor
        ),
    )
    return _written(tenant, request_id, "row done; waits for confirmation", row_id=row_id)
