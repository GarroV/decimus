"""Сопоставление пиццерии рейтинга без id (D323): нормализация, разбор, допуск опечаток.

Порядок — от строгого к мягкому: имя после `normalize_unit_name`; имя после
разбора бота `canonical_unit` («Белград 2» → «Belgrade-2»); близкое написание
города (`difflib`, пороги бота). Номер точки должен совпасть всегда:
«Belgrade-7» не становится «Beograd-1», сколько бы букв ни совпало.
Неоднозначность — «не сопоставлено», строка уходит в журнал.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Sequence
from dataclasses import dataclass

from src.db.units import normalize_unit_name
from src.domain.unit_name import SHORT_CUTOFF, SHORT_NAME, SIMILARITY_CUTOFF, canonical_unit

_NUMBER = re.compile(r"(\d+)\s*$")


@dataclass(frozen=True)
class KnownUnit:
    dodo_id: str
    name: str
    country: str | None


def _canon(name: str) -> str:
    found = canonical_unit(name)
    return normalize_unit_name(found.name if found else name)


def _number(key: str) -> str | None:
    found = _NUMBER.search(key)
    return str(int(found[1])) if found else None


def _only(ids: set[str]) -> str | None:
    return next(iter(ids)) if len(ids) == 1 else None


def match_unit(name: str, country: str | None, known: Sequence[KnownUnit]) -> str | None:
    key = normalize_unit_name(name)
    if not key:
        return None
    pool = [unit for unit in known if country is None or unit.country in (None, country)]
    exact = {unit.dodo_id for unit in pool if normalize_unit_name(unit.name) == key}
    if exact:
        return _only(exact)
    canon = _canon(name)
    same = {unit.dodo_id for unit in pool if _canon(unit.name) == canon}
    if same:
        return _only(same)
    number = _number(canon)
    candidates = [unit for unit in pool if _number(_canon(unit.name)) == number]
    cutoff = SHORT_CUTOFF if len(key) <= SHORT_NAME else SIMILARITY_CUTOFF
    scored = sorted(
        (
            (difflib.SequenceMatcher(None, canon, _canon(unit.name)).ratio(), unit.dodo_id)
            for unit in candidates
        ),
        reverse=True,
    )
    if not scored or scored[0][0] < cutoff:
        return None
    if len(scored) > 1 and scored[1][0] == scored[0][0]:
        return None
    return scored[0][1]
