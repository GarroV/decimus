"""Учёт расхода модели в боте (D537): чья проверка стоит за вызовом.

Кто спрашивает (учётка, Telegram ID, пространство), ставит мидлварь доступа на весь
апдейт (`access.py`). Проверку — личность `run_id` чата — достраивает этот модуль в тех
местах, где зовётся модель и известен `chat_id`: бот не держит проверку в базе до
сдачи, и `run_id` — единственное, чем её можно назвать.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from src.domain import run_id
from src.domain.model_usage import current_scope, usage_scope

logger = logging.getLogger(__name__)


@contextmanager
def chat_usage(chat_id: int) -> Iterator[None]:
    """Вызовы модели внутри блока учитываются за проверкой этого чата.

    Уже названная проверка (веб знает номер в базе) не перетирается. Нечитаемое
    состояние чата — вызов идёт без проверки: учёт не вправе его остановить.
    """
    if current_scope().inspection_ref is not None:
        yield
        return
    try:
        ref = run_id(chat_id) or None
    except Exception:
        logger.warning("расход модели: проверка чата не определена", exc_info=True)
        ref = None
    with usage_scope(inspection_ref=ref):
        yield
