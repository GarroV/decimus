"""One criteria extractor, with a consistent active-inspection edition snapshot."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from .checklist import get_item
from .errors import InspectionNotStarted, ValidationError
from .handover import guard_writable, holding_notes
from .state import assert_checklist_version, get_state, settings_for


class CriteriaUnavailable(ValidationError):
    """There is no criterion to support a model severity decision."""


@dataclass(frozen=True)
class ItemCriteria:
    code: str
    levels: tuple[str, ...]
    criteria: str
    criteria_hash: str
    run_id: str
    checklist_version: str
    lang: str


def criteria_section(directory: Path, code: str) -> str:
    """Read the complete section by code; absent sections remain explicitly empty."""
    path = directory / "criteria.md"
    if not path.is_file():
        return ""
    content = path.read_text(encoding="utf-8")
    found = re.search(rf"(?:^|\n)## {re.escape(code)}\n(.*?)(?=\n## |\Z)", content, re.S)
    return found.group(1).strip() if found else ""


def item_criteria(chat_id: int, code: str) -> ItemCriteria:
    """Read code, allowed levels and criterion from the same pinned active edition."""
    with holding_notes(chat_id):
        guard_writable(chat_id)
        state = get_state(chat_id)
        if state is None:
            raise InspectionNotStarted("Проверка не начата")
        if not state.checklist_version:
            raise CriteriaUnavailable("Издание активной проверки не зафиксировано")
        settings = settings_for(chat_id)
        assert_checklist_version(chat_id, settings)
        item = get_item(code, chat_id=chat_id)
        if item.kind != "violation" or not item.levels:
            raise ValidationError("Выбранный пункт не классифицируется как нарушение")
        criteria = criteria_section(settings.data_dir, item.code)
        if not criteria:
            raise CriteriaUnavailable("Критерии выбранного пункта отсутствуют")
        return ItemCriteria(
            code=item.code,
            levels=tuple(item.levels),
            criteria=criteria,
            criteria_hash=hashlib.sha256(criteria.encode()).hexdigest(),
            run_id=state.run_id,
            checklist_version=state.checklist_version,
            lang=state.ui_lang,
        )
