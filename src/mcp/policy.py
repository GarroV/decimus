"""Права MCP по роли учётки сайта — по той же матрице, что веб и бот (D408, D417).

Роль известна у каждой двери (`config.resolve_access`): у личного токена и у
входа через OAuth это роль учётки decimus, у служебного токена из карты
`MCP_TOKENS` в `.env` — роль из записи `арендатор:роль=токен`, а без неё `guest`
(только чтение). Доступа без роли нет: `None` отказывает везде.

Каждый инструмент каталога сводится к одному действию матрицы (`action_of`):
вид задаёт действие по умолчанию, правящие инструменты методики — своё
(`TOOL_ACTIONS`). Открыт ли инструмент роли, решает
`src.domain.permissions.claude_may` — матрица минус закрытое в Claude
(`CLAUDE_CLOSED`). Своей таблицы ролей здесь нет: вторая копия разошлась бы с
вебом молча.

Снятие проверки (`KIND_RETRACTION`) не открыто ни одной роли намеренно: через
OAuth и личный токен его нет ни у кого (спека D417, D341) — держит
`CLAUDE_CLOSED`, а не отсутствие строки здесь.

**Матрица только сужает.** Прежние заслоны (`rpc._call_tool`: методика по
`MCP_CHECKLIST_TENANTS`, загрузка по `MCP_IMPORT_TENANTS`, рейтинги только УК)
стоят дальше и действуют как раньше.

**Одна функция на `tools/list` и на вызов** (`permits_tool`): инструмент,
скрытый из списка, но открытый на вызове, — дыра, которую видно только перебором
имён. Незнакомая роль закрыта.
"""

from __future__ import annotations

from collections.abc import Mapping

from src.domain.features import action_plans_enabled
from src.domain.permissions import claude_may, require_action

from .catalogue import (
    KIND_CHECKLIST,
    KIND_CHECKLIST_SOURCE,
    KIND_IMPORT,
    KIND_INSPECTIONS,
    KIND_LETTER,
    KIND_MOVE,
    KIND_PLAN,
    KIND_RATINGS,
    KIND_RATINGS_READ,
    KIND_RETRACTION,
    ToolSpec,
)

#: Действие вида: читающий инструмент методики — `checklist.read`, правящий —
#: `checklist.edit`, если не назван в `TOOL_ACTIONS`.
KIND_ACTIONS: Mapping[str, str] = {
    KIND_INSPECTIONS: "inspection.read",
    KIND_CHECKLIST_SOURCE: "checklist.read",
    KIND_CHECKLIST: "checklist.read",
    KIND_RETRACTION: "inspection.retract",
    KIND_IMPORT: "inspection.import",
    KIND_MOVE: "inspection.move",
    KIND_LETTER: "inspection.letter",
    KIND_RATINGS: "ratings.manage",
    KIND_RATINGS_READ: "ratings.read",
    # Чтение плана — как раздел «Действия» в вебе; запись у каждого инструмента своя.
    KIND_PLAN: "view.actions",
}

#: Правящие инструменты методики, чьё действие — не правка пунктов.
TOOL_ACTIONS: Mapping[str, str] = {
    "publish_checklist_version": "checklist.publish",
    # Накопитель непокрытых слов общий на все пространства: только УК.
    "uncovered_phrases": "phrases.raw",
    "retract_learned_phrase": "phrases.manage",
    "repoint_learned_phrase": "phrases.manage",
    "create_checklist": "checklist.manage",
    "rename_checklist": "checklist.manage",
    "set_checklist_state": "checklist.manage",
    "set_checklist_bot_access": "checklist.manage",
    # Указатель прода один на всю сеть — только админы (D440).
    "apply_checklist": "checklist.apply",
    # Новая пиццерия — как кнопка «Добавить пиццерию» в вебе: только УК (D234).
    "create_unit": "unit.create",
    # Электронный план (#1168, D620): вердикты — УК, заполнение и ход строк — партнёр.
    # УК за партнёра не заполняет, партнёр вердиктов не выносит: границу держит матрица
    # (`hq_only` / `partner_only`), и ещё раз — двери `plan_flow`.
    "accept_action_plan": "plan.manage",
    "return_action_plan": "plan.manage",
    "confirm_plan_row": "plan.manage",
    "return_plan_row": "plan.manage",
    "set_plan_count_from": "plan.manage",
    "fill_plan_row": "plan.submit",
    "submit_action_plan": "plan.submit",
    "start_plan_row": "plan.submit",
    "finish_plan_row": "plan.submit",
}


def action_of(spec: ToolSpec) -> str:
    """Действие матрицы, которое открывает инструмент. Незнакомый вид — ошибка кода."""
    if spec.kind == KIND_PLAN and not action_plans_enabled():
        from .plans import READ_TOOLS

        if spec.name in READ_TOOLS:
            return "plan.archive"
    if spec.name in TOOL_ACTIONS:
        return require_action(TOOL_ACTIONS[spec.name]).code
    if spec.kind == KIND_CHECKLIST and spec.writes:
        return "checklist.edit"
    if spec.kind not in KIND_ACTIONS:
        raise ValueError(f"Вид инструмента «{spec.kind}» ({spec.name}) не сведён к матрице")
    return require_action(KIND_ACTIONS[spec.kind]).code


def permits_tool(role: str, tenant: str, spec: ToolSpec) -> bool:
    """Открыт ли инструмент роли учётки. Одна функция и на список, и на вызов."""
    return claude_may(role, tenant, action_of(spec))


def permits(role: str, tenant: str, kind: str) -> bool:
    """Открыт ли роли вид инструментов в целом (действие вида по умолчанию)."""
    действие = KIND_ACTIONS.get(kind)
    return действие is not None and claude_may(role, tenant, действие)


def may_edit_protected(role: str, tenant: str) -> bool:
    """Править главный или применённый к проду чек-лист — только админы (D440)."""
    return claude_may(role, tenant, "checklist.master")
