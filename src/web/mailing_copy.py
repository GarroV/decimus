"""Список копий УК для «Копии» черновика письма (D608, #1130): одна дверь на все виды.

Письмо по проверке (`letter_draft.py`) и письмо предписания (`prescriptions.py`) берут
копию отсюда. Только подстановка в черновик, который человек сам отправляет.

Список не прочитался — черновик без копии, со строкой в журнал: человек видит «Копию» в
черновике и допишет сама, а письмо из-за второстепенного списка не теряется.
"""

from __future__ import annotations

import logging

from src.db import mailing_cc
from src.db.errors import DbError

logger = logging.getLogger(__name__)


def cc_for(kind: str) -> tuple[str, ...]:
    """Адреса копии вида рассылки или пусто, если список не прочитался."""
    try:
        return mailing_cc.read(kind)
    except DbError:
        logger.warning("Список копий вида %s не прочитался", kind, exc_info=True)
        return ()
