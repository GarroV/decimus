"""Информационная часть загруженной проверки: `import_info_fields`, `import_set_info`.

Семь полей (`INF01`, `INF03`–`INF08`: сильные стороны, да/нет, даты) бот
спрашивает в конце обхода, и партнёру они печатаются в PDF. Проверка, занесённая
через Claude (mode=current), их получить не могла — отчёт выходил с пустыми
полями. Здесь два инструмента: прочитать, какие поля есть у чек-листа и что уже
записано, и записать ответы.

Значение проверяется по виду поля ТЕМ ЖЕ разбором, что у бота: дата — `parse_date`
(«до 15 сентября» → `15.09.2026`, не дата — отказ), да/нет — «Да»/«Нет» на языке
отчёта. Пишутся они в ту же таблицу, откуда PDF и письмо читают `detail.info`
(`src/db/imports.set_info`), так что сборка отчёта при приёмке подхватывает их
без своей правки. Историческая проверка (mode=history) информационной части не
имеет: её отчёт собирал старый инструмент.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..db import imports as db
from ..db.models import ORIGIN_LEGACY
from ..domain.dates import parse_date
from ..domain.info_fields import FIELDS, KIND_DATE, KIND_YES_NO, InfoField, yes_no_value
from ..report.info_titles import titles
from .checklist_layout import Store
from .errors import ToolError
from .imports import _db, _only_import, _papers
from .tools import _require_inspection_id

#: Предел ответа одного поля: свободный текст в отчёте — абзац, не документ.
MAX_ANSWER = 2000


def _draft(inspection_id: str, *, tenant: str) -> tuple[str, Any]:
    """Черновик режима current своего пространства — иначе отказ словами."""
    ident = _require_inspection_id(inspection_id)
    detail, шапка = _only_import(ident, tenant=tenant)
    if шапка.origin == ORIGIN_LEGACY:
        raise ToolError(
            f"Проверка {ident} — историческая (mode=history): информационной части у неё нет"
        )
    if not detail.inspection.on_review:
        raise ToolError(f"Проверка {ident} уже подтверждена — информационные поля не правятся")
    return ident, detail


def _fields_of(detail: Any) -> tuple[tuple[InfoField, str], ...]:
    """Поля, которые есть в методике этого черновика, с вопросом на языке отчёта."""
    подписи, _ = titles(
        detail.inspection.checklist_version, lang=detail.inspection.report_lang, papers=_papers()
    )
    return tuple((f, подписи[f.code]) for f in FIELDS if f.code in подписи)


def import_info_fields(
    *, tenant: str, store: Store, actor: str, inspection_id: str
) -> dict[str, object]:
    """Какие информационные поля у черновика, их вид, вопрос и текущее значение."""
    del store, actor
    ident, detail = _draft(inspection_id, tenant=tenant)
    записано = {row.code: row.text for row in detail.info}
    поля = [
        {"code": f.code, "kind": f.kind, "question": вопрос, "value": записано.get(f.code)}
        for f, вопрос in _fields_of(detail)
    ]
    return {
        "id": ident,
        "report_lang": detail.inspection.report_lang,
        "fields": поля,
        "missing": [p["code"] for p in поля if p["value"] is None],
        "note": "Ask the person the missing questions in one message, then call import_set_info",
    }


def _checked(f: InfoField, raw: object, *, lang: str) -> str:
    """Значение по виду поля — или отказ с примером формата."""
    if f.kind == KIND_YES_NO:
        value = yes_no_value(raw, lang)
        if value is None:
            raise ToolError(f"{f.code}: ответ да/нет — «yes» или «no», получено «{raw}»")
        return value
    if not isinstance(raw, str) or not raw.strip():
        raise ToolError(f"{f.code}: ответ пуст — пропущенное поле просто не передаётся")
    text = raw.strip()
    if len(text) > MAX_ANSWER:
        raise ToolError(f"{f.code}: ответ длиннее {MAX_ANSWER} знаков")
    if f.kind == KIND_DATE:
        stamp = parse_date(text)
        if stamp is None:
            raise ToolError(
                f"{f.code}: «{text}» не дата. Нужна дата вида 15.09.2026 или «15 сентября» "
                f"(у INF05 можно с временем)"
            )
        return stamp
    return text


def import_set_info(
    *, tenant: str, store: Store, actor: str, inspection_id: str, values: Mapping[str, object]
) -> dict[str, object]:
    """Записать ответы {код: значение}; всё или ничего, оценку не трогает."""
    del store, actor
    ident, detail = _draft(inspection_id, tenant=tenant)
    if not isinstance(values, Mapping) or not values:
        raise ToolError("values — объект {код поля: ответ}, хотя бы одно поле")
    известные = {f.code: f for f, _ in _fields_of(detail)}
    lang = detail.inspection.report_lang
    принято: dict[str, str] = {}
    for код, raw in values.items():
        key = str(код).strip().upper()
        if key not in известные:
            raise ToolError(
                f"Поля {код} у чек-листа этого черновика нет. Есть: {', '.join(известные)}"
            )
        принято[key] = _checked(известные[key], raw, lang=lang)
    # Порядок записи — порядок разделов отчёта: пишем в порядке методики.
    очередь = [(c, принято[c]) for c in известные if c in принято]
    with _db():
        db.set_info(ident, очередь, tenant=tenant)
    return {"id": ident, "saved": dict(очередь), "note": "info fields saved"}
