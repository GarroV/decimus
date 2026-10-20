"""Пункт чек-листа для аудитора в чате: «Порядок 13», а не `CLN13` (20.10.2026).

Правило метки одно на все поверхности — `domain.item_label`; здесь только то,
откуда бот берёт тексты: методика ТОЙ проверки, по изданию которой её начали
(T169), на языке интерфейса чата. Действующая методика не годится: после
переиздания посреди выезда она называет процесс иначе или не знает пункта.

Методика не читается — метка честно остаётся кодом, а причина идёт в журнал:
записать нарушение аудитору важнее, чем красиво назвать пункт.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

from src import domain
from src.domain import item_label
from src.domain.errors import DomainError

logger = logging.getLogger(__name__)


def chat_texts(chat_id: int) -> Mapping[str, item_label.ItemTexts]:
    """Тексты пунктов издания проверки этого чата; не прочиталось — пусто, причина в журнал.

    Один вызов на сообщение: списки записей (`view.record_lines`) читают методику
    один раз, а не на каждую строку.
    """
    try:
        return item_label.from_items(domain.list_items(chat_id=chat_id))
    except (DomainError, OSError):
        logger.warning("методика чата %s не прочитана для меток пунктов", chat_id, exc_info=True)
        return {}


def shown(
    code: str, lang: str, *, chat_id: int, texts: Mapping[str, item_label.ItemTexts] | None = None
) -> str:
    """Метка пункта для чата. `texts` — уже прочитанные тексты, когда пунктов в сообщении много."""
    return item_label.label(code, chat_texts(chat_id) if texts is None else texts, lang)
