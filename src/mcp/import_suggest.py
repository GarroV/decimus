"""`import_suggest_items`: подбор пункта по словам ОДНОЙ находки (#1015, #1033).

Идёт тем же конвейером, что и `import_match_findings` и бот (`import_match`): слова
места → быстрый путь → модель по полному перечню → класс по критериям. Отдельного
подбора здесь нет — два разных подбора давали разные ответы на одну фразу. Ответ — один
кандидат, готовый к записи.

Модель недоступна — откат на карту слов (`import_draft.word_map_suggest`) с явным
`fallback: "word_map"`: до пяти кандидатов без класса, как раньше. Только чтение.
"""

from __future__ import annotations

from ..domain.model_usage import usage_scope
from .checklist_layout import Store
from .import_draft import check_zone, levels_of, load_draft, word_map_suggest
from .import_match import FALLBACK_WORD_MAP, match_texts
from .imports import MAX_TEXT, _required


def import_suggest_items(
    *,
    tenant: str,
    store: Store,
    actor: str,
    inspection_id: str,
    text: str,
    zone: str | None = None,
) -> dict[str, object]:
    """Один кандидат-пункт по словам находки; при недоступной модели — карта слов."""
    del actor
    draft = load_draft(tenant=tenant, store=store, inspection_id=inspection_id)
    слова = _required(text, field="text", limit=MAX_TEXT)
    зона = check_zone(draft, zone)
    with usage_scope(tenant=tenant, inspection_ref=draft.ident):
        строка = match_texts(draft, [(слова, зона)])[0]
    результат: dict[str, object] = {
        "inspection_id": draft.ident,
        "mode": "history" if draft.history else "current",
        "checklist_version": draft.version,
    }
    if draft.history:
        результат["history_note"] = (
            "history mode: item codes are optional, give one only if the old report names it"
        )
    if строка.get("fallback") == FALLBACK_WORD_MAP:
        кандидаты, угадана, однозначно = word_map_suggest(draft, слова, зона)
        результат.update(
            candidates=кандидаты,
            single=однозначно,
            fallback=FALLBACK_WORD_MAP,
            fallback_reason=строка["fallback_reason"],
            **угадана,
        )
        результат["note"] = (
            "the model was not used, these are word-map hints only: show 1-3 options or "
            "ask the person; do not guess an item"
        )
        return результат
    if строка.get("no_item"):
        результат.update(candidates=[], single=False, no_item=True, reason=строка["reason"])
        return результат
    код = str(строка["code"])
    уровни = levels_of(draft.offered[код]) if код in draft.offered else []
    результат["candidates"] = [
        {
            "code": код,
            "item_label": строка["item_label"],
            "item_title": строка["item_title"],
            "levels": уровни,
            "single_level": len(уровни) == 1,
            "level": строка["level"],
            "zone": строка["zone"],
            "source": строка["via"],
            **{k: строка[k] for k in ("need_fact", "doubt") if k in строка},
        }
    ]
    # Однозначно — когда подбору нечего спросить и не в чем усомниться.
    результат["single"] = not ("need_fact" in строка or "doubt" in строка)
    return результат
