"""Каталог инструментов загрузки проверок задним числом (D305–D310, D332–D335): описания для агента.

Отдельным файлом от `catalogue.py` только по размеру: тот и так перерос
предел. Здесь — данные, а не логика: имя, текст для агента, схема аргументов
и обработчик из `src.mcp.imports`. Вид (`KIND_IMPORT`) и запись в общий
каталог ставит `catalogue.py` — одним местом, чтобы инструмент этого файла не
мог оказаться в каталоге с чужим видом и, значит, мимо права
`MCP_IMPORT_TENANTS`.

Текст описаний — для LLM-агента, который ведёт коллегу по загрузке: что
передать, что проверить до вызова и что показать человеку после. Главное в нём
— два режима (D334): агент обязан однозначно понять, когда `history` (старый
отчёт, оценку переносить как есть и НЕ подгонять), а когда `current`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from . import imports

_ID: dict[str, object] = {
    "type": "string",
    "description": (
        "Identifier (UUID) of the imported draft, as returned by "
        "import_create_inspection or import_list_drafts."
    ),
}

_N: dict[str, object] = {
    "type": "integer",
    "description": "Number n of the finding inside this draft, as shown in its findings list.",
}

_CONFIRM_UNIT: dict[str, object] = {
    "type": "string",
    "description": (
        "Unit (pizzeria) name exactly as recorded on the draft. Confirmation, not a "
        "filter: read it from import_get_inspection and confirm with the person; on "
        "mismatch nothing happens and the answer says what the draft actually is."
    ),
}

_CONFIRM_DATE: dict[str, object] = {
    "type": "string",
    "description": (
        "Inspection date exactly as recorded on the draft, YYYY-MM-DD. Confirmation, "
        "not a filter: on mismatch nothing happens."
    ),
}

#: Общее вступление: два режима. Повторяется в описании создания черновика —
#: агент читает описания по одному, и выбор режима обязан быть виден там, где
#: он делается.
_MODES = (
    "TWO MODES — chosen when the draft is created and never changed:\n"
    "• mode=history — an OLD report made under the PREVIOUS methodology (Qvalon PDF "
    "with 'Score 95.29, Status, Issues', old checklists of 253/217/150 questions, "
    "Bitrix, spreadsheets, free text). The score is transferred EXACTLY as printed in "
    "the report and is never recomputed: do NOT adjust findings to make any number "
    "match, do NOT convert the old score to the current scale. Findings are a "
    "description of the report: wording is required; item code, class (D1/D2/D3) and "
    "zone only if the report states them.\n"
    "• mode=current — a RECENT inspection made under TODAY's checklist (e.g. two weeks "
    "ago), entered after the fact. Only the current version of the reference checklist "
    "is allowed; the engine checks every finding and computes the score exactly as for "
    "a live audit.\n"
    "If unsure which mode applies — ask the person; never guess."
)

_CODE = (
    "Checklist item code (e.g. CLN05), never its wording. current: required, must exist "
    "in the current checklist version (checklist_items). history: optional — give it "
    "only if the old report names the item; an unknown code is kept and returned as a "
    "warning, not refused. Pass an empty string on edit to clear it."
)
_LEVEL = (
    "current: required — D1, D2 or D3 for a violation (must be allowed for this item), "
    "D0 for an informational record, or R for a recommendation (code NOTE for a general "
    "note); decide by the item's criteria, never by feel. history: optional — D1, D2 or "
    "D3 only if the old report states the class; omitted means 'no class' (old "
    "checklists had none). Pass an empty string on edit to clear it."
)
_ZONE = (
    "Zone code (e.g. hot_kitchen) — the PLACE where it was seen, as the report says. "
    "current: required, from the version's zone directory; outside the item's usual "
    "list it is accepted and flagged zone_unusual. history: optional — only if the "
    "report names the place. Pass an empty string on edit to clear it."
)
_TEXT = (
    "Finding wording exactly as the report states the fact, in the draft's text "
    "language. Only the fact: no scale beyond what the report says, no guessed "
    "damage, no remarks to the person. Max 1000 characters. Required in both modes."
)
_COMMENT = "Optional recommendation inside the finding, as in the original report."
_REPEAT = (
    "True if the report marks this finding as a REPEAT of the previous inspection. "
    "Only when the report says so. current: its deduction is doubled. history: stored "
    "as a mark only, the score does not change."
)


@dataclass(frozen=True)
class ImportTool:
    """Одна запись каталога загрузки — без вида: его ставит `catalogue.py`."""

    name: str
    description: str
    input_schema: dict[str, object]
    handler: Callable[..., dict[str, object]]


def _schema(properties: dict[str, object], required: list[str]) -> dict[str, object]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


IMPORT_TOOLS: tuple[ImportTool, ...] = (
    ImportTool(
        name="import_create_inspection",
        description=(
            "Start entering ONE inspection after the fact: creates a DRAFT with no "
            "findings. Accepted drafts appear in the unit's history and analytics next to "
            "live audits.\n\n" + _MODES + "\n\n"
            "mode=history requires unit, date and reported_pct (the score printed in the "
            "old report, e.g. 'Score 95.29' → 95.29 — it BECOMES the inspection's score). "
            "Optional: reported_grade (only if the report prints a letter), "
            "reported_status (the report's status words as printed: 'Passed', "
            "'Not passed', 'Issues (D2)', 'Critical (D3)'…), legacy_method (which old "
            "methodology: 'Qvalon 133', 'old checklist 253'…), auditor, source_ref. Do not "
            "pass checklist_code/checklist_version in this mode.\n"
            "mode=current requires unit, date and auditor. The draft is bound to the "
            "current version of the reference checklist automatically; naming another "
            "checklist or an older version is refused. reported_pct/reported_grade are "
            "optional and used only to compare with the engine's score.\n\n"
            "The unit must already exist in the unit directory: imports never create "
            "units. Next: add each finding with import_add_finding, review with "
            "import_get_inspection, then import_accept_inspection."
        ),
        input_schema=_schema(
            {
                "mode": {
                    "type": "string",
                    "enum": ["history", "current"],
                    "description": "history — old report under the previous methodology, "
                    "score as printed, never recomputed; current — recent inspection "
                    "under today's checklist, scored by the engine. Fixed for the draft.",
                },
                "unit": {
                    "type": "string",
                    "description": "Unit (pizzeria) name as in the unit directory.",
                },
                "date": {
                    "type": "string",
                    "description": "Date of the visit from the report, YYYY-MM-DD. "
                    "Not in the future.",
                },
                "reported_pct": {
                    "type": "number",
                    "description": "Score printed in the report, 0–100. history: REQUIRED "
                    "and it is the inspection's score as is. current: optional, only "
                    "compared with the engine's score.",
                },
                "reported_grade": {
                    "type": "string",
                    "description": "Grade letter printed in the report, if any. history: "
                    "kept as the inspection's letter (omit when the report has none). "
                    "current: comparison only.",
                },
                "reported_status": {
                    "type": "string",
                    "description": "history only: the old report's status words as "
                    "printed (e.g. Passed, Not passed, Good, Issues (D2), Critical (D3)). "
                    "Max 60 characters.",
                },
                "legacy_method": {
                    "type": "string",
                    "description": "history only: label of the old methodology the "
                    "inspection was made by (e.g. 'Qvalon 133', 'old checklist 253'). "
                    "Max 100 characters.",
                },
                "auditor": {
                    "type": "string",
                    "description": "Auditor name as printed in the report. Required in "
                    "current, optional in history.",
                },
                "checklist_code": {
                    "type": "string",
                    "description": "current only, optional: the reference checklist code "
                    "(anything else is refused). Do not pass in history.",
                },
                "checklist_version": {
                    "type": "string",
                    "description": "current only, optional: must equal the current "
                    "version (checklist_versions); an older one is refused. Do not pass "
                    "in history.",
                },
                "kind": {
                    "type": "string",
                    "description": "planned (default), repeat or unscheduled.",
                },
                "report_lang": {
                    "type": "string",
                    "description": "Language of the report: ru (default) or en.",
                },
                "text_lang": {
                    "type": "string",
                    "description": "Language the finding wordings are written in, two "
                    "letters (default: report_lang).",
                },
                "source_ref": {
                    "type": "string",
                    "description": "Link or name of the original document (Bitrix link, "
                    "file name), so the import can be traced back.",
                },
            },
            ["mode", "unit", "date"],
        ),
        handler=imports.import_create_inspection,
    ),
    ImportTool(
        name="import_add_finding",
        description=(
            "Add one finding from the report to an imported draft. Behaviour depends on "
            "the draft's mode (see import_get_inspection → mode).\n"
            "current: code, level, zone and text are required; the engine checks the "
            "finding against the current checklist version exactly as for a live audit "
            "(item exists, class allowed, zone exists, one item + zone pair is one "
            "finding; D0 and R do not occupy the pair) and recomputes the score. On "
            "refusal nothing is written and the engine's reason is returned.\n"
            "history: text is required; code, level (D1/D2/D3) and zone only if the old "
            "report states them — omitted ones are stored as 'not given' ('no class' for "
            "level). The score does NOT change: it stays as in the old report. Unknown "
            "codes/zones come back as warnings — show them to the person.\n\n"
            "One call per finding, as the person confirms it. Never invent findings, "
            "codes, classes or zones the report does not state — ask the person instead."
        ),
        input_schema=_schema(
            {
                "inspection_id": _ID,
                "code": {"type": "string", "description": _CODE},
                "level": {"type": "string", "description": _LEVEL},
                "zone": {"type": "string", "description": _ZONE},
                "text": {"type": "string", "description": _TEXT},
                "comment": {"type": "string", "description": _COMMENT},
                "repeat": {"type": "boolean", "description": _REPEAT},
            },
            ["inspection_id", "text"],
        ),
        handler=imports.import_add_finding,
    ),
    ImportTool(
        name="import_edit_finding",
        description=(
            "Correct one finding of an imported draft by its number n. Only the given "
            "fields change. current: the engine re-checks the finding against the "
            "current checklist version and recomputes the score; a recommendation (R) and "
            "a violation cannot be turned into each other by editing — remove and add "
            "again. history: nothing is recomputed; pass an empty string for code, level "
            "or zone to mark it 'not given'. Pass comment as an empty string to clear it."
        ),
        input_schema=_schema(
            {
                "inspection_id": _ID,
                "n": _N,
                "code": {"type": "string", "description": _CODE},
                "level": {"type": "string", "description": _LEVEL},
                "zone": {"type": "string", "description": _ZONE},
                "text": {"type": "string", "description": _TEXT},
                "comment": {"type": "string", "description": _COMMENT},
                "repeat": {"type": "boolean", "description": _REPEAT},
            },
            ["inspection_id", "n"],
        ),
        handler=imports.import_edit_finding,
    ),
    ImportTool(
        name="import_remove_finding",
        description=(
            "Remove one finding (with its photos) from an imported draft by its number "
            "n. current: the score is recomputed by the engine. history: the score stays "
            "as in the old report."
        ),
        input_schema=_schema({"inspection_id": _ID, "n": _N}, ["inspection_id", "n"]),
        handler=imports.import_remove_finding,
    ),
    ImportTool(
        name="import_get_inspection",
        description=(
            "Read an imported inspection (draft or accepted): its mode, header and "
            "findings with their numbers.\n"
            "mode=history: the score (pct, grade) is the old report's, as is, with the "
            "report's status and the old methodology label; there are no deductions or "
            "per-zone breakdown and nothing to compare — check with the person that pct, "
            "letter and status match the report exactly.\n"
            "mode=current: the engine's score (pct, grade, deductions, per-zone "
            "breakdown) and, if the report's score was given, the comparison "
            "(matches_reported, pct_diff). A difference usually means a missing, extra or "
            "mis-levelled finding or a missed repeat mark — show it to the person before "
            "accepting."
        ),
        input_schema=_schema({"inspection_id": _ID}, ["inspection_id"]),
        handler=imports.import_get_inspection,
    ),
    ImportTool(
        name="import_list_drafts",
        description=(
            "List this space's imported drafts that are not accepted yet: mode "
            "(history/current), unit, date, checklist version (legacy:<label> for "
            "history), score and reported score, number of findings."
        ),
        input_schema=_schema({}, []),
        handler=imports.import_list_drafts,
    ),
    ImportTool(
        name="import_add_photo",
        description=(
            "Attach a photo from the old report to one finding of an imported draft. "
            "Optional: a finding without a photo is fine for imports. The image is "
            "passed as base64 (JPEG, PNG or WebP, at most 700 KB after decoding — the "
            "request body is capped at 1 MB; downscale larger images first). The same "
            "image is not attached twice to one finding."
        ),
        input_schema=_schema(
            {
                "inspection_id": _ID,
                "n": _N,
                "image_base64": {
                    "type": "string",
                    "description": "Image bytes, base64-encoded (no data: prefix).",
                },
                "mime": {
                    "type": "string",
                    "description": "image/jpeg, image/png or image/webp.",
                },
            },
            ["inspection_id", "n", "image_base64", "mime"],
        ),
        handler=imports.import_add_photo,
    ),
    ImportTool(
        name="import_accept_inspection",
        description=(
            "Accept an imported draft after the person has checked it (the person who "
            "imported it accepts it). It enters the unit's history and analytics next to "
            "live audits and can no longer be edited or discarded. Accepting opens NO "
            "action-plan request, there is no partner letter for imported inspections, "
            "and nothing is sent to anyone.\n\n"
            "Confirm with the person first: history — the score, letter and status exactly "
            "as in the old report; current — the engine's score vs the reported one. The "
            "call must name the unit and the date as recorded; on mismatch nothing is "
            "accepted."
        ),
        input_schema=_schema(
            {
                "inspection_id": _ID,
                "confirm_unit": _CONFIRM_UNIT,
                "confirm_date": _CONFIRM_DATE,
            },
            ["inspection_id", "confirm_unit", "confirm_date"],
        ),
        handler=imports.import_accept_inspection,
    ),
    ImportTool(
        name="import_discard_draft",
        description=(
            "Delete an imported DRAFT entirely, with its findings and photos — e.g. it "
            "was started for the wrong unit or date. Never touches inspections from live "
            "audits and never an accepted one (an accepted wrong one is retracted "
            "instead). Must name the unit and the date as recorded; on mismatch nothing "
            "is deleted."
        ),
        input_schema=_schema(
            {
                "inspection_id": _ID,
                "confirm_unit": _CONFIRM_UNIT,
                "confirm_date": _CONFIRM_DATE,
            },
            ["inspection_id", "confirm_unit", "confirm_date"],
        ),
        handler=imports.import_discard_draft,
    ),
)
