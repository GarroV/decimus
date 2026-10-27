"""Классы инструментов MCP и их аннотации в `tools/list` (#1338; образец — Swarm `annotations.ts`).

Одна карта на все инструменты каталога: новый инструмент без записи здесь не
пройдёт `tests/test_mcp_annotations.py`. Клиент показывает подтверждение по
`destructiveHint` и не просит его для `readOnlyHint` (MCP 2025-03-26).

Класс: `read` — ничего не меняет; `write` — добавляет или правит;
`destructive` — удаляет, снимает, отзывает, публикует, применяет к проду или
перекрывает прежнее без пути назад. Инструмент с `ToolSpec.confirm_effect`
обязан быть `destructive` (тест).
"""

from __future__ import annotations

from dataclasses import dataclass

READ = "read"
WRITE = "write"
DESTRUCTIVE = "destructive"


@dataclass(frozen=True)
class ToolClass:
    """Класс инструмента и его идемпотентность (повтор того же вызова ничего не меняет)."""

    kind: str
    idempotent: bool


def _read() -> ToolClass:
    return ToolClass(READ, True)


def _write(idempotent: bool) -> ToolClass:
    return ToolClass(WRITE, idempotent)


def _destructive(idempotent: bool) -> ToolClass:
    return ToolClass(DESTRUCTIVE, idempotent)


TOOL_CLASSES: dict[str, ToolClass] = {
    # Чтение проверок.
    "list_inspections": _read(),
    "unit_history": _read(),
    "network_summary": _read(),
    "get_inspection": _read(),
    "findings_by_unit": _read(),
    "inspection_letter": _read(),
    # Чтение методики и эталона.
    "checklist_source": _read(),
    "checklist_source_item": _read(),
    "checklist_versions": _read(),
    "checklist_items": _read(),
    "checklist_item": _read(),
    "scoring": _read(),
    "route": _read(),
    "photo_cues": _read(),
    "photo_cue_suggestions": _read(),
    "uncovered_phrases": _read(),
    "learned_phrases": _read(),
    "checklists": _read(),
    "checklist_meta": _read(),
    # Чтение рейтингов.
    "ratings_summary": _read(),
    "ratings_units": _read(),
    "ratings_unit_periods": _read(),
    "aggregators_status": _read(),
    # Чтение при загрузке проверки (подбор пункта сам ничего не пишет).
    "import_get_inspection": _read(),
    "import_list_drafts": _read(),
    "import_match_findings": _read(),
    "import_suggest_items": _read(),
    "import_info_fields": _read(),
    # Чтение плана исправлений.
    "list_action_plans": _read(),
    "get_action_plan": _read(),
    # Запись: добавляет или правит.
    "save_inspection_letter": _write(False),  # каждая версия письма — новая запись истории
    "add_checklist_item": _write(False),
    "edit_checklist_item": _write(True),
    "restore_checklist_item": _write(True),
    "add_zone": _write(False),
    "rename_zone": _write(True),
    "add_photo_cue": _write(False),
    "edit_photo_cue": _write(True),
    "set_photo_cue_zone": _write(True),
    "create_checklist": _write(False),
    "rename_checklist": _write(True),
    "set_checklist_bot_access": _write(True),
    "import_ratings": _write(True),  # тот же файл отвечает «duplicate»
    "request_aggregators_update": _write(True),  # повторная заявка — «уже в очереди»
    "create_unit": _write(False),
    "import_create_inspection": _write(False),
    "import_add_finding": _write(False),
    "import_add_findings": _write(False),
    "import_edit_finding": _write(True),
    "import_edit_inspection": _write(True),
    "import_add_photo": _write(False),
    "import_upload_photos": _write(False),  # готовит адрес загрузки; сами файлы идут мимо модели
    "import_set_info": _write(True),
    "move_inspection": _write(True),
    "accept_action_plan": _write(False),
    "return_action_plan": _write(False),
    "confirm_plan_row": _write(False),
    "return_plan_row": _write(False),
    "set_plan_count_from": _write(True),
    "fill_plan_row": _write(True),
    "submit_action_plan": _write(False),
    "start_plan_row": _write(False),
    "finish_plan_row": _write(False),
    # Разрушительное: удаляет, снимает, публикует, применяет к проду, меняет расчёт оценки.
    "remove_checklist_item": _destructive(True),
    "remove_zone": _destructive(True),
    "set_zone_shares": _destructive(True),
    "set_scoring": _destructive(True),
    "set_route": _destructive(True),
    "remove_photo_cue": _destructive(True),
    "retract_learned_phrase": _destructive(True),
    "repoint_learned_phrase": _destructive(True),
    "publish_checklist_version": _destructive(False),
    "set_checklist_state": _destructive(True),
    "apply_checklist": _destructive(True),
    "retract_inspection": _destructive(True),
    "import_remove_finding": _destructive(True),
    "import_remove_photo": _destructive(True),
    "import_clear_photos": _destructive(True),
    "import_discard_draft": _destructive(True),
    "import_accept_inspection": _destructive(False),  # из черновика — в документ партнёра
}


def annotations_for(name: str) -> dict[str, bool] | None:
    """Аннотации инструмента для `tools/list`; `None` — класса нет (тест этого не пропускает)."""
    cls = TOOL_CLASSES.get(name)
    if cls is None:
        return None
    return {
        "readOnlyHint": cls.kind == READ,
        "destructiveHint": cls.kind == DESTRUCTIVE,
        "idempotentHint": cls.idempotent,
        "openWorldHint": False,
    }
