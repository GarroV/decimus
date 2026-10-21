"""`import_review_card`: карточка находок для подтверждения кнопками (#1024).

Только чтение: ничего не пишет и оценку не считает. Инструмент принимает
находки, которые Claude подобрал по словам человека, сверяет их с версией
чек-листа черновика (код есть, класс допустим, зона есть) и отдаёт их же с
вопросом пункта на языке отчёта. Клиент с MCP Apps рисует из ответа карточку
(`review_ui.py`) и сам вызывает `import_add_findings`; клиент без них видит
обычный текстовый список. Запись — по-прежнему только `import_add_findings`.
"""

from __future__ import annotations

from typing import Any

from ..db.models import ORIGIN_LEGACY
from . import checklist as store_api
from .checklist_layout import Store, locate
from .errors import ChecklistError, ToolError
from .imports import MAX_TEXT, _only_import
from .tools import _require_inspection_id

#: Предел карточки: длиннее — человек не просмотрит; находок не больше, чем в пакете записи.
MAX_FINDINGS = 50
MAX_QUESTIONS = 10
MAX_OPTIONS = 5
#: Классы, которых пункт не перечисляет, но движок принимает (см. `import_add_finding`).
_ANY_ITEM_LEVELS = {"D0", "R"}
_VIOLATION_LEVELS = {"D1", "D2", "D3"}
_NOTE_CODE = "NOTE"
_FIELDS = ("code", "level", "zone", "text", "comment")


def _levels(row: dict[str, str]) -> set[str]:
    raw = (row.get("levels") or "").replace(",", ";")
    return {x.strip() for x in raw.split(";") if x.strip()}


def _own(row: dict[str, str], keys: tuple[str, str], lang: str) -> str:
    ru, en = keys
    first, second = (en, ru) if lang == "en" else (ru, en)
    return (row.get(first) or row.get(second) or "").strip()


class _Reference:
    """Пункты и зоны версии черновика: по ним проверяется каждая находка."""

    def __init__(
        self, items: list[dict[str, str]], zones: list[dict[str, str]], *, lang: str, strict: bool
    ) -> None:
        self.items = {r["id"].strip(): r for r in items if (r.get("id") or "").strip()}
        self.zones = {r["code"].strip(): r for r in zones if (r.get("code") or "").strip()}
        self.lang = lang
        #: current — код, класс и зона обязательны; history — только то, что названо.
        self.strict = strict

    def check(self, raw: object) -> tuple[dict[str, Any] | None, str | None]:
        """Находка → (находка для карточки, None) или (None, причина отказа)."""
        if not isinstance(raw, dict):
            return None, "finding must be an object"
        extra = sorted(set(raw) - set(_FIELDS))
        if extra:
            return None, f"unknown fields: {', '.join(extra)}"
        got: dict[str, str] = {}
        for name in _FIELDS:
            value = raw.get(name)
            if value is None:
                continue
            if not isinstance(value, str):
                return None, f"{name} must be a string"
            if value.strip():
                got[name] = value.strip()
        if not got.get("text"):
            return None, "text is empty"
        if len(got["text"]) > MAX_TEXT:
            return None, f"text is longer than {MAX_TEXT} characters"
        missing = [n for n in ("code", "level", "zone") if n not in got]
        if self.strict and missing:
            return None, f"current mode requires {', '.join(missing)}"
        code, level, zone = got.get("code"), got.get("level"), got.get("zone")
        row = self.items.get(code) if code else None
        if code and row is None and code != _NOTE_CODE:
            return None, f"no item {code} in this checklist version"
        if level and row is not None and level not in _levels(row) | _ANY_ITEM_LEVELS:
            return None, f"class {level} is not allowed for {code}"
        if level and row is None and level not in _ANY_ITEM_LEVELS | _VIOLATION_LEVELS:
            return None, f"unknown class {level}"
        if zone and zone not in self.zones:
            return None, f"no zone {zone}"
        shown: dict[str, Any] = dict(got)
        if row is not None:
            shown["question"] = _own(row, ("question_ru", "question_en"), self.lang)
        if zone:
            shown["zone_title"] = _own(self.zones[zone], ("name_ru", "name_en"), self.lang)
        return shown, None


def _reference(ident: str, *, tenant: str, store: Store) -> tuple[_Reference, str]:
    detail, шапка = _only_import(ident, tenant=tenant)
    история = шапка.origin == ORIGIN_LEGACY
    try:
        эталон = locate(store, tenant=tenant, code=None)
        if эталон is None:
            raise ToolError("Действующий эталон УК не найден в хранилище методики")
        версия = (
            store_api.current_version(эталон) if история else detail.inspection.checklist_version
        )
        items = store_api.read_items(эталон, version=версия)
        zones = store_api.read_items(эталон, version=версия, what="zones")
    except ChecklistError as отказ:
        raise ToolError(str(отказ)) from None
    lang = detail.inspection.report_lang
    return _Reference(items, zones, lang=lang, strict=not история), lang


def _summary(findings: list[dict[str, Any]], questions: list[dict[str, Any]]) -> str:
    """Тот же ответ простым списком — для клиента, который карточку не рисует."""
    lines = [
        f"{i}) [{f.get('level', '-')}] {f.get('code', '-')} - {f['text']}"
        + (f", {f['zone_title']}" if f.get("zone_title") else "")
        for i, f in enumerate(findings, 1)
    ]
    out = ["Proposed findings (nothing is written yet):", *lines]
    for q in questions:
        out.append(f"? {q['text']} -> " + " / ".join(o["label"] for o in q["options"]))
    out.append("On the person's yes: ONE import_add_findings call with the confirmed ones.")
    return "\n".join(out)


def _questions(
    raw_questions: list[Any], ref: _Reference, invalid: list[dict[str, object]]
) -> list[dict[str, Any]]:
    asked: list[dict[str, Any]] = []
    for qi, q in enumerate(raw_questions):
        text = q.get("text") if isinstance(q, dict) else None
        if not isinstance(text, str) or not text.strip():
            invalid.append({"question": qi, "reason": "question text is empty"})
            continue
        options: list[dict[str, Any]] = []
        for oi, o in enumerate(q.get("options") or []):
            label = o.get("label") if isinstance(o, dict) else None
            shown, reason = ref.check(o.get("finding") if isinstance(o, dict) else None)
            if shown is None or not isinstance(label, str) or not label.strip():
                invalid.append({"question": qi, "option": oi, "reason": reason or "label is empty"})
            elif len(options) < MAX_OPTIONS:
                options.append({"label": label.strip(), "finding": shown})
        if options:
            asked.append({"text": text.strip(), "options": options})
    return asked


def import_review_card(
    *,
    tenant: str,
    store: Store,
    actor: str,
    inspection_id: str,
    findings: list[Any],
    questions: list[Any] | None = None,
) -> dict[str, object]:
    """Проверить предложенные находки и вопросы и отдать их для карточки; ничего не писать."""
    del actor
    ident = _require_inspection_id(inspection_id)
    if len(findings) > MAX_FINDINGS:
        raise ToolError(f"В карточке не больше {MAX_FINDINGS} находок, передано {len(findings)}")
    if len(questions or []) > MAX_QUESTIONS:
        raise ToolError(f"В карточке не больше {MAX_QUESTIONS} вопросов")
    ref, lang = _reference(ident, tenant=tenant, store=store)
    ok: list[dict[str, Any]] = []
    invalid: list[dict[str, object]] = []
    for index, raw in enumerate(findings):
        shown, reason = ref.check(raw)
        if shown is None:
            invalid.append({"index": index, "reason": reason})
        else:
            ok.append(shown)
    asked = _questions(questions or [], ref, invalid)
    if not ok and not asked:
        raise ToolError(
            "Нечего показать: ни одна находка не прошла сверку с чек-листом ("
            + "; ".join(str(x["reason"]) for x in invalid)
            + "). Исправьте и вызовите снова; пишет только import_add_findings"
        )
    text = _summary(ok, asked)
    if invalid:
        text += "\nNOT shown (fix and resend): " + "; ".join(str(x["reason"]) for x in invalid)
    return {
        "summary": text,
        "inspection_id": ident,
        "lang": lang,
        "findings": ok,
        "questions": asked,
        "invalid": invalid,
    }
