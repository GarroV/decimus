"""Semantic search shortcuts: edition data selects codes; no class or model decisions."""

from __future__ import annotations

from collections.abc import Iterable, Set

from src.domain.models import ChecklistItem
from src.recognize.cues import load_cue_snapshot, stems

# Search vocabulary only. No codes, criteria, thresholds or class mappings live here.
TAG_QUERIES = {
    "dirty": ("грязно", "грязь", "dirty", "dirt"),
    "expired": ("просрочка", "просроченный", "expired", "expiry", "срок годности", "shelf life"),
    "segregation": ("товарное соседство", "соседство", "food segregation", "cross contamination"),
    "labels": ("маркировки", "маркировка", "labels", "label", "labelling", "labeling"),
}


def search_tags(items: Iterable[ChecklistItem], *, chat_id: int) -> list[dict[str, object]]:
    """All four tags, with current violation hits in catalogue order.

    A matching column contributes only its own codes. A phrase match may contribute
    the row only when no column in that row selects a more precise set.
    """
    catalogue = tuple(i for i in items if i.kind == "violation" and i.levels != ["D0"])
    rows, vocabulary = load_cue_snapshot(chat_id=chat_id)
    result: list[dict[str, object]] = []
    for tag, queries in TAG_QUERIES.items():
        terms = tuple(stems(query) for query in queries)

        def matches(text: Set[str], terms: tuple[set[str], ...] = terms) -> bool:
            return any(query and query <= text for query in terms)

        hits: set[str] = set()
        for row in rows:
            columns = [
                codes
                for header, codes in row.by_column
                if matches(stems(header) | vocabulary.get(header.strip().lower(), frozenset()))
            ]
            if columns:
                hits.update(code for codes in columns for code in codes)
            elif matches(stems(row.phrase)):
                hits.update(row.codes)
        # Checklist wording is a data-owned lookup too, including editions without a cue map.
        for item in catalogue:
            if matches(stems(item.question_ru)) or matches(stems(item.question_en)):
                hits.add(item.code)
        result.append({"id": tag, "codes": [item.code for item in catalogue if item.code in hits]})
    return result
