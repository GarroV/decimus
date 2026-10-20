"""Общее для подбора пункта по находке (#1015, #1033): издание черновика и карта слов.

`load_draft` читает то, по чему идёт черновик: издание (у `current` — версия
черновика, у `history` — действующая, версии хранилища у исторической нет, D332),
пункты, зоны, карту слов и каталог версии. `word_map_suggest` — подбор по карте
слов: откат, когда модель недоступна (`import_match`), и подсказка зоны.

Служебные пункты (не `violation`, `MGM22`/`MGM23`) не предлагаются — правило 8
`docs/03-recording-rules.md`. Карта ничего не нашла — ответ так и говорит и
пуст: случайные пункты вместо него подсунуть значило бы выдать догадку за
подбор (правило 12). Оценку здесь никто не считает.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from ..db.models import ORIGIN_LEGACY
from ..domain.models import Zone
from ..recognize.cues import Cue, load_cues, match_cues, match_zones
from ..recognize.shortlist import MANUAL_ONLY
from ..recognize.zone_words import zone_from_words
from . import checklist as store_api
from .checklist_layout import Store, locate
from .errors import ChecklistError, ToolError
from .imports import _only_import
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


def levels_of(row: dict[str, str]) -> list[str]:
    """Допустимые классы пункта из колонки `levels` («D1;D2»)."""
    return [x.strip() for x in (row.get("levels") or "").replace(",", ";").split(";") if x.strip()]


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
    levels = levels_of(row)
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


@dataclass(frozen=True)
class Draft:
    """Издание, по которому идёт черновик, прочитанное из хранилища методики."""

    ident: str
    history: bool
    version: str
    lang: str
    store: Store
    rows: list[dict[str, str]]
    zones: list[Zone]
    cues: tuple[Cue, ...]
    data_dir: Path

    @property
    def zone_codes(self) -> set[str]:
        return {z.code for z in self.zones}

    @property
    def offered(self) -> dict[str, dict[str, str]]:
        return {r["id"].strip(): r for r in self.rows if _offered(r)}


def draft_from_store(
    store: Store,
    *,
    tenant: str,
    version: str | None,
    lang: str,
    ident: str = "",
    history: bool = False,
) -> Draft:
    """Издание из хранилища методики. `version=None` — действующая. Не нашлось — отказ словами."""
    try:
        эталон = locate(store, tenant=tenant, code=None)
        if эталон is None:
            raise ToolError("Действующий эталон УК не найден в хранилище методики")
        версия = version or store_api.current_version(эталон)
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
        cues_path = store_api.cues_file(эталон, version=версия)
        карта = load_cues(cues_path, chat_id=None)
    except ChecklistError as отказ:
        raise ToolError(str(отказ)) from None
    return Draft(
        ident=ident,
        history=history,
        version=версия,
        lang=lang,
        store=эталон,
        rows=строки,
        zones=справочник,
        cues=карта,
        data_dir=cues_path.parent,
    )


def load_draft(*, tenant: str, store: Store, inspection_id: str) -> Draft:
    """Издание, по которому идёт черновик: у `current` — его версия, у `history` — действующая."""
    ident = _require_inspection_id(inspection_id)
    detail, шапка = _only_import(ident, tenant=tenant)
    история = шапка.origin == ORIGIN_LEGACY
    return draft_from_store(
        store,
        tenant=tenant,
        version=None if история else detail.inspection.checklist_version,
        lang=detail.inspection.report_lang,
        ident=ident,
        history=история,
    )


def check_zone(draft: Draft, zone: str | None) -> str | None:
    """Названная зона должна быть в справочнике издания; иначе отказ со списком."""
    зона = (zone or "").strip() or None
    if зона is not None and зона not in draft.zone_codes:
        raise ToolError(f"Нет зоны «{зона}». Доступны: {', '.join(sorted(draft.zone_codes))}")
    return зона


def word_map_suggest(
    draft: Draft, text: str, zone: str | None
) -> tuple[list[dict[str, object]], dict[str, object], bool]:
    """Подбор по карте слов: (кандидаты, зона-догадка, однозначно ли). Без модели."""
    годные = draft.offered
    найденные = [(c, "cue_map") for c in dict.fromkeys(match_cues(text, draft.cues)) if c in годные]
    if len(найденные) < MIN_CANDIDATES and zone is not None:
        взятые = {c for c, _ in найденные}
        найденные += [
            (c, "zone") for c, r in годные.items() if c not in взятые and _in_zone(r, zone)
        ]
    выбор = найденные[:MAX_CANDIDATES]
    угадана = (
        _zone_guess(text, draft.cues, draft.zone_codes, draft.zones, годные, выбор)
        if zone is None
        else {}
    )
    кандидаты = [
        _candidate(годные[c], store=draft.store, version=draft.version, lang=draft.lang, source=src)
        for c, src in выбор
    ]
    # Однозначно — ровно одна подсказка карты (критерий быстрого пути бота
    # `recognize.fastpath` привязан к изданию чата и здесь не берётся).
    однозначно = sum(src == "cue_map" for _, src in выбор) == 1
    return кандидаты, угадана, однозначно
