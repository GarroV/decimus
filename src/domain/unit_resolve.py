"""Одно правило имени пиццерии на бота, мини-апп, MCP, админку и загрузки (D538).

Имя пиццерии — латинское номерное имя из справочника пиццерий (`unit_profiles`):
«Tbilisi-1». «Тбилиси-1», «тбилиси 1», «Tbilisi 1» и «Тбилиси -1» — запасные написания:
по ним точка находится, но отдельной записью под ними пиццерия не живёт. Здесь чистая
логика без базы; читают и пишут `src/db/directory.py` и `src/db/unit_resolver.py`.

Две половины одного правила:

1. **Найти** — `find_unit`: введённое сводится ключом `unit_lookup_key` (регистр,
   пробелы, виды тире, кириллица и армянский латиницей, диакритика) и сверяется с именами
   и синонимами справочника. Снятая точка (`merged_into`, миграция 0078) ведёт на ту, в
   которую влита: её имя — такой же синоним, а список её не знает.
2. **Завести** — `with_reference`: нет такой точки, но справочник пиццерий строку знает —
   точка заводится под ЕГО именем и кодом Dodo, введённое остаётся синонимом.
   Справочник не знает — имя остаётся канонической латиницей `canonical_unit` (D233).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from .unit_match import Ref, city_slug, clean_ref_name, latin_text, numbered_key
from .unit_name import UnitName, canonical_unit, fold_unit_name, unit_name_skeleton

# Ранги ответа, порядок — по силе: точка со страной (из справочника сети) сильнее заведённой
# по факту проверки (иначе старый дубль продолжал бы собирать проверки мимо настоящей точки,
# D196); дальше точное написание сильнее похожего; живое имя сильнее синонима. Меньше — сильнее.
_ANCHORED = 0
_LOOSE = 1
_EXACT = 0
_FOLDED = 1
_NAME = 0
_ALIAS = 1


def unit_lookup_key(text: str) -> str:
    """Ключ поиска пиццерии: «Тбилиси -1», «тбилиси 1» и «Tbilisi-1» дают один и тот же.

    Годится поиску, а не хранению: ключ грубее `units.name_normalized`, и совпавшая им
    точка сверяется ещё и рангом (`find_unit`). Номер в ключе сохраняется — «-1» не «-2».
    """
    return unit_name_skeleton(latin_text(text))


@dataclass(frozen=True)
class DirUnit:
    """Точка справочника в том виде, который нужен поиску."""

    id: str
    name: str
    aliases: tuple[str, ...] = ()
    #: `id` точки, в которую эта влита (D538); `None` — точка живая.
    merged_into: str | None = None
    #: Загружена справочником сети (есть страна), а не заведена по первому написанию:
    #: при равенстве остальных рангов побеждает она.
    anchored: bool = False


@dataclass(frozen=True)
class Resolution:
    """Итог поиска: живая точка, либо ничего, либо «подошло несколько — не угадываю»."""

    unit: DirUnit | None
    ambiguous: bool = False


NOT_FOUND = Resolution(None)


def _live_target(unit: DirUnit, by_id: dict[str, DirUnit]) -> DirUnit | None:
    """Живая точка, на которую указывает `unit`: она сама или та, в которую влита."""
    if unit.merged_into is None:
        return unit
    target = by_id.get(unit.merged_into)
    return target if target is not None and target.merged_into is None else None


def _find_one(units: Sequence[DirUnit], typed: str) -> Resolution:
    key = unit_lookup_key(typed)
    if not key:
        return NOT_FOUND
    folded = fold_unit_name(typed)
    by_id = {u.id: u for u in units}
    best: dict[str, tuple[int, int, int]] = {}
    for unit in units:
        target = _live_target(unit, by_id)
        if target is None:
            continue
        # Имя снятой точки — такой же синоним, как записанные: своего имени у неё нет.
        name_rank = _NAME if unit.merged_into is None else _ALIAS
        for rank, spelling in ((name_rank, unit.name), *((_ALIAS, a) for a in unit.aliases)):
            if unit_lookup_key(spelling) != key:
                continue
            exact = _EXACT if fold_unit_name(spelling) == folded else _FOLDED
            score = (_ANCHORED if target.anchored else _LOOSE, exact, rank)
            if target.id not in best or score < best[target.id]:
                best[target.id] = score
    if not best:
        return NOT_FOUND
    top = min(best.values())
    winners = [uid for uid, score in best.items() if score == top]
    if len(winners) > 1:
        return Resolution(None, ambiguous=True)
    return Resolution(by_id[winners[0]])


def find_unit(units: Sequence[DirUnit], *typed: str) -> Resolution:
    """Живая точка по любому из написаний `typed` (первое давшее ответ решает)."""
    for text in typed:
        found = _find_one(units, text)
        if found.unit is not None or found.ambiguous:
            return found
    return NOT_FOUND


def find_reference(typed: str, refs: Sequence[Ref], *, country: str | None = None) -> Ref | None:
    """Строка справочника пиццерий, которую названо введённое; не нашлась или не одна — `None`.

    Сначала то же имя без регистра и диакритики, потом то же «Город-N» на другом алфавите
    (в том числе по каноническому имени словаря городов: «Белград-1» → «Belgrade-1»).
    Страна, если известна, сужает выбор; «не одна» — отказ угадывать, а не первая попавшаяся.
    """
    pool = [r for r in refs if country is None or r.country == country]
    names = {typed}
    canon = canonical_unit(typed)
    if canon is not None:
        names.add(canon.name)
    wanted = {fold_unit_name(clean_ref_name(n)) for n in names}
    found = {r.key: r for r in pool if fold_unit_name(clean_ref_name(r.name)) in wanted}
    if not found:
        keys = {numbered_key(latin_text(n)) for n in names} - {""}
        found = {r.key: r for r in pool if numbered_key(r.name) in keys}
    return next(iter(found.values())) if len(found) == 1 else None


def with_reference(unit: UnitName, typed: str, refs: Sequence[Ref]) -> UnitName:
    """Имя новой пиццерии по справочнику: его имя, код Dodo, страна; нет строки — как есть."""
    ref = find_reference(typed, refs, country=unit.country)
    if ref is None:
        ref = find_reference(unit.name, refs, country=unit.country)
    if ref is None:
        return unit
    return replace(
        unit,
        name=ref.clean_name,
        code=ref.dodo_id or unit.code,
        country=ref.country,
        city=unit.city or city_slug(ref.city),
    )
