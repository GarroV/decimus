"""Автоперевод производного представления отчёта; исходный снимок не меняется.

Ручной режим не вызывает модель. В AUTO перевод сохраняется рядом со снимком
сдачи, используется PDF и письмом и переносится в общий кэш документов после
архивирования. Отказ отдельного поля сохраняет исходный текст и предупреждение.
"""

from __future__ import annotations

import logging

from src import domain
from src.db import translate_modes
from src.db.errors import DbError
from src.domain.config import Settings
from src.domain.log_ids import log_id
from src.domain.state import settings_for
from src.report import snapshot_text

from .usage import chat_usage

logger = logging.getLogger(__name__)


def mode_of(chat_id: int) -> str:
    """Режим перевода человека. Не выбирал или база молчит — по кнопке (D394)."""
    try:
        mode = translate_modes.chosen_translate_mode(chat_id)
    except DbError:
        logger.warning("Режим перевода чата %s не прочитался", log_id(chat_id), exc_info=True)
        return translate_modes.DEFAULT_MODE
    return mode if mode in translate_modes.MODES else translate_modes.DEFAULT_MODE


def translate_comments(
    chat_id: int, inspection: domain.Inspection, *, source_settings: Settings | None = None
) -> int:
    """Prepare display translations in AUTO, returning the number of failed fields."""
    if inspection.report_lang == inspection.speech_lang or mode_of(chat_id) != translate_modes.AUTO:
        snapshot_text.disable(chat_id, source_settings or settings_for(chat_id))
        return 0
    with chat_usage(chat_id):
        return snapshot_text.prepare(chat_id, source_settings or settings_for(chat_id))
