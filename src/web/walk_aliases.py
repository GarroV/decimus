"""Выученные формулировки пунктов для поиска пункта в мини-аппе обхода.

Карта синонимов (`src/db/synonyms.py`) учится на сохранённых нарушениях:
«как аудитор это назвал» → пункт. Поиск пункта вручную ищет и по ним, поэтому
экран получает по каждому пункту его ДЕЙСТВУЮЩИЕ формулировки на языке речи
проверки. Снятые управляющей компанией (T292) не отдаются: карта не врёт
поиску о том, что сняла. Пределы заданы кодом: у пункта не больше
`MAX_PER_ITEM` формулировок (свежие первыми), каждая обрезана до `MAX_LENGTH`.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from src.db import synonyms
from src.db.errors import DbError
from src.domain.models import Inspection
from src.domain.tenants import canonical_tenant

logger = logging.getLogger(__name__)

MAX_PER_ITEM = 20
MAX_LENGTH = 120


def item_aliases(inspection: Inspection, codes: Iterable[str]) -> dict[str, list[str]]:
    """`{код пункта: [формулировки]}` для пунктов из `codes`; сбой карты — пусто.

    Карта нужна поиску как довесок: недоступная база не должна ронять экран
    обхода, поэтому сбой пишется в журнал и поиск идёт по самим пунктам.
    """
    wanted = set(codes)
    try:
        rows = synonyms.list_phrases(
            lang=inspection.speech_lang, tenant=canonical_tenant(inspection.tenant)
        )
    except DbError:
        logger.warning("Обход: карта формулировок недоступна, поиск без словаря", exc_info=True)
        return {}
    out: dict[str, list[str]] = {}
    for alias in sorted(rows, key=lambda a: a.created_at, reverse=True):
        # Страховка: снятые карта и так не отдаёт, но поиск не должен зависеть
        # от умолчания чужой функции.
        if alias.retracted_at is not None or alias.item_code not in wanted:
            continue
        phrases = out.setdefault(alias.item_code, [])
        if len(phrases) < MAX_PER_ITEM:
            phrases.append(alias.phrase[:MAX_LENGTH])
    return out
