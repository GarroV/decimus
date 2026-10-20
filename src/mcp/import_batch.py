"""`import_add_findings`: пакетная запись подтверждённых находок (#1017).

Каждая находка идёт тем же путём, что в `import_add_finding` (`imports.add_one`):
та же проверка движком и те же отказы, своей логики здесь нет. Пакет не атомарен
намеренно: записанные записаны, отказанные возвращаются с индексом во входном
списке и причиной — человеку не пересказывать подтверждённое заново из-за одной
кривой строки. Ответ короткий, как у поштучного (#1016).
"""

from __future__ import annotations

from typing import Any

from .checklist_layout import Store
from .errors import McpError, ToolError
from .imports import _only_import, _short_view, add_one
from .tools import _require_inspection_id

#: Предел пакета: ответ и время движка растут с числом находок.
MAX_BATCH = 50

_FIELDS = {
    "text": str,
    "code": str,
    "level": str,
    "zone": str,
    "comment": str,
    "repeat": bool,
}


def _checked(item: object) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ToolError("Находка должна быть объектом с полями text, code, level, zone…")
    лишние = sorted(set(item) - set(_FIELDS))
    if лишние:
        raise ToolError(f"Неизвестные поля находки: {', '.join(лишние)}")
    for имя, тип in _FIELDS.items():
        if имя in item and not isinstance(item[имя], тип):
            raise ToolError(f"Поле {имя} находки — {тип.__name__}")
    if "text" not in item:
        raise ToolError("У находки нет text")
    return item


def import_add_findings(
    *, tenant: str, store: Store, actor: str, inspection_id: str, findings: list[Any]
) -> dict[str, object]:
    """Записать до 50 подтверждённых находок; не атомарно, отказы — с индексом и причиной."""
    del actor
    ident = _require_inspection_id(inspection_id)
    if not findings:
        raise ToolError("Список findings пуст")
    if len(findings) > MAX_BATCH:
        raise ToolError(f"В пакете не больше {MAX_BATCH} находок, передано {len(findings)}")
    _, шапка = _only_import(ident, tenant=tenant)
    added: list[dict[str, object]] = []
    refused: list[dict[str, object]] = []
    предупреждения: list[str] = []
    for index, raw in enumerate(findings):
        try:
            n, warn = add_one(tenant=tenant, store=store, ident=ident, шапка=шапка, **_checked(raw))
        except (ToolError, McpError) as отказ:
            refused.append({"index": index, "reason": str(отказ)})
            continue
        except Exception as сбой:
            # Сбой базы или движка посреди пакета: записанное остаётся, остальные
            # не пробуются — продолжать вслепую значило бы множить сбой.
            refused.append(
                {"index": index, "reason": f"not written: {type(сбой).__name__}; batch stopped"}
            )
            refused.extend(
                {"index": i, "reason": "not attempted: batch stopped"}
                for i in range(index + 1, len(findings))
            )
            break
        added.append({"index": index, "n": n})
        предупреждения.extend(f"#{n}: {w}" for w in warn)
    полный = _short_view(
        ident,
        tenant=tenant,
        note=f"{len(added)} added, {len(refused)} refused of {len(findings)}",
        warnings=предупреждения,
    )
    return {**полный, "added": added, "refused": refused}
