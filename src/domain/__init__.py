"""Блок `domain` — единственная точка доступа к предметной области.

Контракт — `docs/furca/blocks/domain.md`. Через него ходят остальные блоки:
чек-лист, зоны, состояние проверки, оценка. Никто, кроме этого блока, не
открывает `inspection.json` и не запускает движок — импорт `engine` из `bot`,
`recognize` и `report` роняет прогон (контракт `engine-not-imported` в
`lint-imports`).

Оценка не считается здесь ни в каком виде: `score()` разбирает вывод
`audit.py score`, ставки вычетов живут в `data/scoring.json`.
"""

from __future__ import annotations

from .checklist import (
    allowed_levels,
    checklist_version,
    get_item,
    list_items,
    list_zones,
    only_zone,
)
from .config import check_environment
from .findings import add_finding, attach_photo, detach_photo, drop_finding, edit_finding
from .handover import handed_over
from .info import set_info
from .kinds import INSPECTION_KINDS, kind_title
from .models import (
    ADVICE_LEVEL,
    NON_DEDUCTING,
    NOTE_CODE,
    SOURCE_COMMENT,
    SOURCE_PHOTO,
    SOURCES,
    ChecklistItem,
    Finding,
    Inspection,
    Score,
    Suggestion,
    Zone,
    ZoneScore,
)
from .scoring import score
from .state import (
    drop_inspection,
    get_state,
    settings_for,
    start_inspection,
    sync_checklist_version,
)
from .uncovered import (
    OUTCOME_ABANDONED,
    OUTCOME_RECORDED,
    OUTCOME_REFUSED,
    OUTCOMES,
    ZONE_SOURCE_BUTTONS,
    ZONE_SOURCE_DICTIONARY,
    ZONE_SOURCE_WORDS,
    ZONE_SOURCES,
    UncoveredEntry,
    archive_uncovered,
    read_uncovered,
    record_uncovered,
)
from .uploads import is_upload_ref, save_upload, upload_file

__all__ = [
    "ADVICE_LEVEL",
    "INSPECTION_KINDS",
    "NON_DEDUCTING",
    "NOTE_CODE",
    "OUTCOMES",
    "OUTCOME_ABANDONED",
    "OUTCOME_RECORDED",
    "OUTCOME_REFUSED",
    "SOURCES",
    "SOURCE_COMMENT",
    "SOURCE_PHOTO",
    "ZONE_SOURCES",
    "ZONE_SOURCE_BUTTONS",
    "ZONE_SOURCE_DICTIONARY",
    "ZONE_SOURCE_WORDS",
    "ChecklistItem",
    "Finding",
    "Inspection",
    "Score",
    "Suggestion",
    "UncoveredEntry",
    "Zone",
    "ZoneScore",
    "add_finding",
    "allowed_levels",
    "archive_uncovered",
    "attach_photo",
    "check_environment",
    "checklist_version",
    "detach_photo",
    "drop_finding",
    "drop_inspection",
    "edit_finding",
    "get_item",
    "get_state",
    "handed_over",
    "is_upload_ref",
    "kind_title",
    "list_items",
    "list_zones",
    "only_zone",
    "read_uncovered",
    "record_uncovered",
    "save_upload",
    "score",
    "set_info",
    "settings_for",
    "start_inspection",
    "sync_checklist_version",
    "upload_file",
]
