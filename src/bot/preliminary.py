"""Напоминание под отчётом: он предварительный, проверку надо принять в вебе (27.10.2026).

Уходит последним сообщением после отчёта, письма и слива в историю
(`routers.finish.deliver`), и при повторной отправке отчёта (`routers.resend`).
Только если проверка уже лежит в истории и ждёт приёмки: принятой напоминать
нечего, а не слитой — некуда вести. Состояние читается в момент отправки
(`db.find_pushed`), а не берётся из того, что было при сдаче.

Адресат один — чат, из которого проверка проведена: проверка в модели одна на
чат и одного аудитора (`inspection.auditor`), соавторов нет.

Ссылка строится от публичного адреса веба: `ADMIN_PUBLIC_URL`, а если его в
окружении бота нет — от адреса мини-аппа `BOT_WALK_URL` (тот же хост,
`docs/08-deploy.md`). Адреса нет — сообщение без ссылки, а не отказ. Сбой
напоминания ничего не роняет: отчёт к этому моменту у аудитора.
"""

from __future__ import annotations

import asyncio
import logging
import os
from urllib.parse import urlsplit

from aiogram.types import Message

from src import db
from src.domain.log_ids import log_id
from src.domain.public_urls import ADMIN_PUBLIC_URL_VAR, parse_public_url

from .config import WALK_URL_VAR
from .texts import t

logger = logging.getLogger(__name__)

#: Путь карточки проверки в вебе (`src/web/sections.py`, раздел «Проверки»).
_CARD_PATH = "/inspections"


def web_base() -> str | None:
    """Публичный адрес веба без хвостовой «/»; `None` — стенд его не называет."""
    try:
        base = parse_public_url(
            os.environ.get(ADMIN_PUBLIC_URL_VAR) or "", var=ADMIN_PUBLIC_URL_VAR
        )
    except ValueError:
        logger.warning("%s не разобран — ссылка берётся от %s", ADMIN_PUBLIC_URL_VAR, WALK_URL_VAR)
        base = None
    if base:
        return base
    walk = urlsplit((os.environ.get(WALK_URL_VAR) or "").strip())
    if walk.scheme == "https" and walk.netloc:
        return f"https://{walk.netloc}"
    return None


def card_url(inspection_id: str) -> str | None:
    """Абсолютная ссылка на карточку проверки; `None` — адрес веба неизвестен."""
    base = web_base()
    return None if base is None else f"{base}{_CARD_PATH}/{inspection_id}"


async def remind(message: Message, chat_id: int, lang: str) -> bool:
    """Напомнить, что отчёт предварительный. `True` — сообщение ушло.

    Не бросает: нет базы, сбой чтения, сбой отправки — в журнал и `False`.
    """
    try:
        pushed = await asyncio.to_thread(db.find_pushed, chat_id)
    except db.ConfigError:
        return False
    except db.DbError:
        logger.exception("статус проверки чата %s не прочитан — напоминания нет", log_id(chat_id))
        return False
    if pushed is None or not pushed.awaiting_acceptance:
        return False
    url = card_url(pushed.id)
    text = t("finish.preliminary", lang, url=url) if url else t("finish.preliminary_nolink", lang)
    try:
        await message.answer(text)
    except Exception:  # — Bot API: отчёт уже у аудитора, напоминание не стоит сдачи
        logger.exception("напоминание в чат %s не ушло", log_id(chat_id))
        return False
    return True
