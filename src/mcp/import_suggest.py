"""`import_suggest_items`: подбор пунктов чек-листа по словам находки (#1015).

Раньше агент подбирал пункт сам: листал `checklist_items` и вываливал человеку
длинный список. Здесь подбор делает карта слов методики (`data/photo-cues.md`) —
тот же `recognize.cues`, что у бота: свой матчинг не пишется.

Только чтение. Издание берётся то, по которому идёт черновик: у `current` — его
версия, у `history` — действующая (версии хранилища у исторической нет, D332).
Служебные пункты (не `violation`, `MGM22`/`MGM23`) не предлагаются — правило 8
`docs/03-recording-rules.md`. Карта ничего не нашла — ответ так и говорит и
пуст: случайные пункты вместо него подсунуть значило бы выдать догадку за
подбор (правило 12). Оценку здесь никто не считает.
"""

from __future__ import annotations

import logging

from ..db.models import ORIGIN_LEGACY
from ..domain.models import Zone
from ..recognize.cues import Cue, load_cues, match_cues, match_zones
from ..recognize.shortlist import MANUAL_ONLY
from ..recognize.zone_words import zone_from_words
from . import checklist as store_api
from .checklist_layout import Store, locate
from .errors import ChecklistError, ToolError
from .imports import MAX_TEXT, _only_import, _required
from .tools import _require_inspection_id

logger = logging.getLogger(__name__)

#: Сколько кандидатов отдаётся агенту: больше — и он снова вываливает список.
MAX_CANDIDATES = 5
#: Если карта нашла меньше — добирается зоной.
MIN_CANDIDATES = 3
#: Критерии пункта длинные; здесь краткая выдержка, полные — `checklist_item`.
MAX_CRITERIA_CHARS = 500


def _offered(row: dict[str, str]) -> bool:
    code = row.get("id", "").strip()
    return (
        bool(code) and (row.get("kind") or "violation") == "violation" and code not in MANUAL_ONLY
    )


def _in_zone(row: dict[str, str], zone: str) -> bool:
    zones = [z.strip() for z in (row.get("zones") or "").split(",") if z.strip()]
    return not zones or zones == ["*"] or zone in zones


def _brief(criteria: str) -> str:
    text = criteria.strip()
    if len(text) <= MAX_CRITERIA_CHARS:
        return text
    return text[:MAX_CRITERIA_CHARS].rstrip() + "… (full text: checklist_item)"


def _question(row: dict[str, str], lang: str) -> str:
    own, other = ("question_en", "question_ru") if lang == "en" else ("question_ru", "question_en")
    return (row.get(own) or row.get(other) or "").strip()


def _candidate(
    row: dict[str, str], *, store: Store, version: str, lang: str, source: str
) -> dict[str, object]:
    code = row["id"].strip()
    levels = [
        x.strip() for x in (row.get("levels") or "").replace(",", ";").split(";") if x.strip()
    ]
    return {
        "code": code,
        "question": _question(row, lang),
        "levels": levels,
        "single_level": len(levels) == 1,
        "criteria": _brief(store_api.read_item(store, code=code, version=version)["criteria"]),
        "source": source,
    }


def _zone_guess(
    text: str,
    cues: tuple[Cue, ...],
    zones: set[str],
    справочник: list[Zone],
    items: dict[str, dict[str, str]],
    chosen: list[tuple[str, str]],
) -> dict[str, object]:
    """Зона, когда она вывелась без вопроса: источники по порядку `binding.md`.

    1. слова места («на линии», «в зале») — `recognize.zone_words`, как у бота;
    2. зона объекта из карты слов (`match_zones`) — одна зона, иначе не вывелась;
    3. единственная зона пункта по методике, если пункт один.
    Названы две зоны разом — не угадывается, а перечисляется в `zone_options`.
    """
    try:
        названа = zone_from_words(text, chat_id=None, zones=справочник)
    except Exception:  # методика зон не читается — подбор пунктов от этого не падает
        logger.warning("зона по словам не выведена: методика зон не прочиталась", exc_info=True)
        названа = None
    if названа in zones:
        return {"zone_guess": названа, "zone_source": "words"}
    карта = [z for z in match_zones(text, cues) if z in zones]
    if len(карта) == 1:
        return {"zone_guess": карта[0], "zone_source": "cue_map"}
    if len(карта) > 1:
        return {"zone_options": карта}
    if len(chosen) == 1:
        пункт = [
            z.strip() for z in (items[chosen[0][0]].get("zones") or "").split(",") if z.strip()
        ]
        if len(пункт) == 1 and пункт[0] != "*" and пункт[0] in zones:
            return {"zone_guess": пункт[0], "zone_source": "item"}
    return {}


def import_suggest_items(
    *,
    tenant: str,
    store: Store,
    actor: str,
    inspection_id: str,
    text: str,
    zone: str | None = None,
) -> dict[str, object]:
    """До пяти кандидатов-пунктов по словам находки: карта слов, затем зона."""
    del actor
    ident = _require_inspection_id(inspection_id)
    detail, шапка = _only_import(ident, tenant=tenant)
    слова = _required(text, field="text", limit=MAX_TEXT)
    история = шапка.origin == ORIGIN_LEGACY
    try:
        эталон = locate(store, tenant=tenant, code=None)
        if эталон is None:
            raise ToolError("Действующий эталон УК не найден в хранилище методики")
        версия = (
            store_api.current_version(эталон) if история else detail.inspection.checklist_version
        )
        строки = store_api.read_items(эталон, version=версия)
        справочник = [
            Zone(
                code=r["code"].strip(),
                title_ru=r.get("name_ru") or "",
                title_en=r.get("name_en") or "",
                share_pct=0.0,
            )
            for r in store_api.read_items(эталон, version=версия, what="zones")
            if (r.get("code") or "").strip()
        ]
        зоны = {z.code for z in справочник}
        карта = load_cues(store_api.cues_file(эталон, version=версия), chat_id=None)
    except ChecklistError as отказ:
        raise ToolError(str(отказ)) from None
    зона = (zone or "").strip() or None
    if зона is not None and зона not in зоны:
        raise ToolError(f"Нет зоны «{зона}». Доступны: {', '.join(sorted(зоны))}")
    lang = detail.inspection.report_lang
    годные = {r["id"].strip(): r for r in строки if _offered(r)}

    найденные = [(c, "cue_map") for c in dict.fromkeys(match_cues(слова, карта)) if c in годные]
    if len(найденные) < MIN_CANDIDATES and зона is not None:
        взятые = {c for c, _ in найденные}
        найденные += [
            (c, "zone") for c, r in годные.items() if c not in взятые and _in_zone(r, зона)
        ]
    выбор = найденные[:MAX_CANDIDATES]
    угадана = _zone_guess(слова, карта, зоны, справочник, годные, выбор) if зона is None else {}
    результат: dict[str, object] = {
        "inspection_id": ident,
        "mode": "history" if история else "current",
        "checklist_version": версия,
        "candidates": [
            _candidate(годные[c], store=эталон, version=версия, lang=lang, source=src)
            for c, src in выбор
        ],
        # Однозначно — ровно одна подсказка карты (критерий быстрого пути бота
        # `recognize.fastpath` привязан к изданию чата и здесь не берётся). Тогда
        # агент кладёт находку в сводку «Записываю: …» без вопроса о выборе.
        "single": sum(src == "cue_map" for _, src in выбор) == 1,
        **угадана,
    }
    if not any(src == "cue_map" for _, src in выбор):
        результат["note"] = (
            "the word map found no candidates for this wording"
            + (" (candidates below are only the zone's items)" if выбор else "")
            + ": search with checklist_items (filter by process) or ask the person; "
            "do not guess an item"
        )
    if история:
        результат["history_note"] = (
            "history mode: item codes are optional, give one only if the old report names it"
        )
    return результат
