"""Журнал изменяющих вызовов MCP: кто, какой инструмент, чем кончилось.

Только в stderr процесса, как и остальной журнал сервера (`server.log_message`).
Пишется ЛИЦО и ДЕЙСТВИЕ, а не содержимое: ни токена, ни аргументов вызова, ни
текста ответа (в них история проверок партнёра). Лицо — подпись `Access.actor`
(`web:<логин>`, `mcp:<арендатор>`) и, у служебного токена, его метка-отпечаток.
Читающие вызовы не пишутся: журнал нужен, чтобы по следу изменения найти
автора, а не чтобы дублировать трафик.
"""

from __future__ import annotations

import sys
from typing import Any

from .catalogue import find

OUTCOME_OK = "ok"
#: Инструмент вызван и ответил отказом или ошибкой (`isError`).
OUTCOME_FAILED = "failed"
#: Запрос отклонён до инструмента: роль, неверные параметры, неизвестное имя.
OUTCOME_REJECTED = "rejected"


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
