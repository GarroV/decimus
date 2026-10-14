"""Мини-апп обхода: «Ещё не смотрели» — пункты зоны, по которым записи пока нет (#837, D492).

Аудитор в горячем цехе не помнит весь чек-лист. Экран сам показывает, какие
пункты методики относятся к этой зоне и ещё не записаны, — подсказка, а не
требование: ничего не блокирует завершение, бот молчит.

Чистые функции: пункты и записи приходят аргументами, состояние не читается.
Замеры (`D0` — печь, холодильники: сведения без баллов) не смешиваются с
нарушениями — это отдельный список для приглушённой строки.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from src.domain.models import ChecklistItem, Finding

#: Информационная запись — замер, а не нарушение (docs/02-domain.md).
INFO_LEVEL = "D0"

#: Классы в начале формулировки — «(D1, D2) …»: в подсказке они лишние.
_LEVEL_PREFIX = re.compile(r"^\(\s*D\d(?:\s*,\s*D\d)*\s*\)\s*")


def _short(item: ChecklistItem, lang: str) -> dict[str, Any]:
    return {
        "code": item.code,
        "q": _LEVEL_PREFIX.sub("", item.question(lang)).strip(),
        "levels": list(item.levels),
    }


def unseen_in_zone(
    zone: str, items: Iterable[ChecklistItem], findings: Iterable[Finding], *, lang: str
) -> dict[str, list[dict[str, Any]]]:
    """Что в зоне ещё не записано: `unseen` — нарушения, `unseen_info` — замеры.

    Пункт «увиден», если в ЭТОЙ зоне уже есть запись с его кодом: тот же пункт в
    другой зоне означает другое место, его здесь ещё не смотрели. Нарушения —
    пункты, чьи зоны включают эту (пустой список и `*` — любая); замер попадает
    сюда, только если зона названа у него явно, иначе любой термометр шумел бы
    в каждой зоне. Служебные пункты (`aggregate`, `info`) не предлагаются
    (правило фиксации 8).
    """
    seen = {f.code for f in findings if f.zone == zone}
    unseen: list[dict[str, Any]] = []
    info: list[dict[str, Any]] = []
    for item in items:
        if item.kind != "violation" or item.code in seen:
            continue
        if item.levels == [INFO_LEVEL]:
            if zone in item.zones:
                info.append(_short(item, lang))
        elif item.applies_to(zone):
            unseen.append(_short(item, lang))
    return {"unseen": unseen, "unseen_info": info}
