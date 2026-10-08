"""Каталог инструментов загрузки исторических проверок (D305–D310): описания для агента.

Отдельным файлом от `catalogue.py` только по размеру: тот и так перерос
предел. Здесь — данные, а не логика: имя, текст для агента, схема аргументов
и обработчик из `src.mcp.imports`. Вид (`KIND_IMPORT`) и запись в общий
каталог ставит `catalogue.py` — одним местом, чтобы инструмент этого файла не
мог оказаться в каталоге с чужим видом и, значит, мимо права
`MCP_IMPORT_TENANTS`.

Текст описаний — для LLM-агента, который ведёт коллегу по загрузке: что
передать, что проверить до вызова и что показать человеку после.
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

_CODE = (
    "Checklist item code (e.g. CLN05), never its wording. Must exist in the draft's "
    "own checklist version; take it from checklist_items/checklist_item of that version."
)
_LEVEL = (
    "Class: D1, D2 or D3 for a violation (must be allowed for this item), D0 for an "
    "informational record (temperatures, oven settings, product photo — items whose "
    "levels are D0), or R for a recommendation (any violation item, or the code NOTE "
    "for a general note). Decide the class by the item's criteria, never by feel."
)
_ZONE = (
    "Zone code from the version's zone directory (e.g. hot_kitchen) — the PLACE where "
    "it was seen, as the original report says. A zone outside the item's usual list is "
    "accepted and flagged zone_unusual."
)
_TEXT = (
    "Finding wording exactly as the original report states the fact, in the draft's "
    "text language. Only the fact: no scale beyond what the report says, no guessed "
    "damage, no remarks to the person. Max 1000 characters."
)
_COMMENT = "Optional recommendation inside the finding, as in the original report."
_REPEAT = (
    "True if the original report marks this finding as a REPEAT of the previous "
    "inspection (its deduction is doubled). Only when the report says so."
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
            "Start importing ONE historical inspection from an old report (Bitrix, PDF, "
            "spreadsheet): creates a DRAFT with no findings, scored by the engine against "
            "the given checklist version. Imported inspections are ordinary inspections "
            "of their own checklist version once accepted — they appear in unit history "
            "and analytics like any other.\n\n"
            "Before calling: make sure the old methodology exists as a checklist version "
            "(checklists, checklist_versions; build missing old versions with the "
            "checklist tools — one version per change of the old methodology). The unit "
            "must already exist in the unit directory: imports never create units. "
            "Pass the score printed in the old report as reported_pct/reported_grade — "
            "it is used ONLY to compare against the engine's score before acceptance.\n\n"
            "Next: add each finding with import_add_finding, then compare with "
            "import_get_inspection, then import_accept_inspection."
        ),
        input_schema=_schema(
            {
                "unit": {
                    "type": "string",
                    "description": "Unit (pizzeria) name as in the unit directory.",
                },
                "date": {
                    "type": "string",
                    "description": "Date of the visit from the old report, YYYY-MM-DD. "
                    "Not in the future.",
                },
                "checklist_code": {
                    "type": "string",
                    "description": "Code of the checklist the old report was made by "
                    "(see checklists).",
                },
                "checklist_version": {
                    "type": "string",
                    "description": "Exact version id of that checklist the inspection was "
                    "scored by (see checklist_versions). Omitted — the checklist's current "
                    "version; for old reports name the old version explicitly.",
                },
                "auditor": {
                    "type": "string",
                    "description": "Auditor name as printed in the old report.",
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
                "reported_pct": {
                    "type": "number",
                    "description": "Percentage printed in the old report, 0–100. For "
                    "comparison only.",
                },
                "reported_grade": {
                    "type": "string",
                    "description": "Grade letter printed in the old report. For comparison only.",
                },
                "source_ref": {
                    "type": "string",
                    "description": "Link or name of the original document (Bitrix link, "
                    "file name), so the import can be traced back.",
                },
            },
            ["unit", "date", "checklist_code", "auditor"],
        ),
        handler=imports.import_create_inspection,
    ),
    ImportTool(
        name="import_add_finding",
        description=(
            "Add one finding from the old report to an imported draft. The engine checks "
            "it against the draft's OWN checklist version exactly as for a live audit: "
            "the item exists, the class is allowed for it, the zone exists, and one item "
            "+ zone pair is one finding (several objects of one item in one zone are ONE "
            "finding). D0 and R records do not occupy the pair. On refusal nothing is "
            "written and the engine's reason is returned. The score is recomputed by the "
            "engine in the same step.\n\n"
            "One call per finding, as the person confirms it. Never invent findings, "
            "classes or zones the report does not state — ask the person instead."
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
            ["inspection_id", "code", "level", "zone", "text"],
        ),
        handler=imports.import_add_finding,
    ),
    ImportTool(
        name="import_edit_finding",
        description=(
            "Correct one finding of an imported draft by its number n. Only the given "
            "fields change; the engine re-checks the finding against the draft's "
            "checklist version and recomputes the score. A recommendation (R) and a "
            "violation cannot be turned into each other by editing — remove and add "
            "again. Pass comment as an empty string to clear it."
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
            "n. The score is recomputed by the engine."
        ),
        input_schema=_schema({"inspection_id": _ID, "n": _N}, ["inspection_id", "n"]),
        handler=imports.import_remove_finding,
    ),
    ImportTool(
        name="import_get_inspection",
        description=(
            "Read an imported inspection (draft or accepted): header, findings with "
            "their numbers, the engine's score (pct, grade, deductions, per-zone "
            "breakdown) and the comparison with the score printed in the old report — "
            "matches_reported and pct_diff. Show the comparison to the person before "
            "accepting; a difference usually means a missing, extra or mis-levelled "
            "finding, a missed repeat mark, or the wrong checklist version."
        ),
        input_schema=_schema({"inspection_id": _ID}, ["inspection_id"]),
        handler=imports.import_get_inspection,
    ),
    ImportTool(
        name="import_list_drafts",
        description=(
            "List this space's imported drafts that are not accepted yet: unit, date, "
            "checklist version, computed and reported score, number of findings."
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
            "imported it accepts it). It becomes an ordinary inspection of its checklist "
            "version in the unit's history and analytics and can no longer be edited or "
            "discarded. Accepting an import opens NO action-plan request and sends "
            "nothing to anyone.\n\n"
            "Confirm with the person first, showing the computed vs reported score. The "
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
