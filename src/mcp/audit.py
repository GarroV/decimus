"""Журнал изменяющих вызовов MCP: кто, какой инструмент, чем кончилось.

Только в stderr процесса, как и остальной журнал сервера (`server.log_message`).
Пишется ЛИЦО и ДЕЙСТВИЕ, а не содержимое: ни токена, ни аргументов вызова, ни
текста ответа (в них история проверок партнёра). Лицо — подпись `Access.actor`
(`web:<логин>`, `mcp:<арендатор>`) и, у служебного токена, его метка-отпечаток.
Читающие вызовы не пишутся: журнал нужен, чтобы по следу изменения найти
автора, а не чтобы дублировать трафик.

**Журнал действий в базе (D462).** Тот же вызов дополнительно ложится в
`action_journal` (`journal_write_call`), если за токеном стоит учётка сайта с ролью
админа или главного админа: служебный токен из `.env` — не человек, у него остаётся
только след выше. Дверь одна — `server._post` после `rpc.handle`, — поэтому новый
инструмент покрыт с первого дня: в журнал не попадают лишь названные здесь читающие.
Аргументы вызова кладутся сводкой по правилу имён полей (`src/domain/journal.py`),
а не целиком.
"""

from __future__ import annotations

import sys
from typing import Any

from src.domain.journal import DOOR_MCP, JOURNALED_ROLES, summarize_target

from .catalogue import find
from .config import Access
from .plans import READ_TOOLS as READ_PLAN_TOOLS

OUTCOME_OK = "ok"
#: Инструмент вызван и ответил отказом или ошибкой (`isError`).
OUTCOME_FAILED = "failed"
#: Запрос отклонён до инструмента: роль, неверные параметры, неизвестное имя.
OUTCOME_REJECTED = "rejected"


#: Инструменты, которые ничего не меняют, хотя каталог по осторожности помечает их
#: `writes=True` (`ToolSpec.writes`: «забыли сказать — значит пишет»). В журнал
#: действий они не идут. Нового имени тут нет — значит, вызов пишется: лишняя строка
#: журнала дешевле пропущенного действия. Сверяет `tests/test_mcp_audit_journal.py`.
READ_ONLY_TOOLS = frozenset(
    {
        "list_inspections",
        "unit_history",
        "network_summary",
        "get_inspection",
        "findings_by_unit",
        "inspection_letter",
        "checklist_source",
        "checklist_source_item",
        "ratings_summary",
        "ratings_units",
        "ratings_unit_periods",
        "aggregators_status",
        "import_get_inspection",
        "import_list_drafts",
        "import_suggest_items",
        "import_match_findings",
    }
    | READ_PLAN_TOOLS
)


def _outcome(answer: dict[str, Any] | None) -> str:
    if answer is None or "error" in answer:
        return OUTCOME_REJECTED
    result = answer.get("result")
    if isinstance(result, dict) and result.get("isError"):
        return OUTCOME_FAILED
    return OUTCOME_OK


def log_write_call(
    message: Any, answer: dict[str, Any] | None, *, actor: str, role: str | None, label: str
) -> None:
    """Записать вызов изменяющего инструмента; всё прочее молча пропустить."""
    if not isinstance(message, dict) or message.get("method") != "tools/call":
        return
    params = message.get("params")
    name = params.get("name") if isinstance(params, dict) else None
    spec = find(name) if isinstance(name, str) else None
    if spec is None or not spec.writes:
        return
    метка = f" token={label}" if label else ""
    print(
        f"[mcp-audit] actor={actor or '-'} role={role or '-'}{метка} "
        f"tool={spec.name} outcome={_outcome(answer)}",
        file=sys.stderr,
    )


def journal_write_call(
    message: Any, answer: dict[str, Any] | None, *, access: Access, ip: str | None
) -> None:
    """Записать изменяющий вызов админа в журнал действий (D462); всё прочее пропустить."""
    if not access.user_id or access.role not in JOURNALED_ROLES:
        return
    if not isinstance(message, dict) or message.get("method") != "tools/call":
        return
    params = message.get("params")
    name = params.get("name") if isinstance(params, dict) else None
    spec = find(name) if isinstance(name, str) else None
    if spec is None or not spec.writes or spec.name in READ_ONLY_TOOLS:
        return
    arguments = params.get("arguments") if isinstance(params, dict) else None
    try:
        from src.db import journals
    except ImportError:
        # Стенд собран без блока `db`: журнала в базе нет, остаётся след в stderr.
        return
    journals.record_action(
        user_id=access.user_id,
        role=access.role or "",
        tenant=access.tenant,
        action=spec.name,
        target=summarize_target(arguments if isinstance(arguments, dict) else {}),
        outcome=_outcome(answer),
        ip=ip,
        credential=access.credential or None,
        door=DOOR_MCP,
    )
