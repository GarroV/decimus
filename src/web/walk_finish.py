"""«Завершить проверку» из приложения (D422): тот же итог в чат, что даёт `/finish`.

`POST /tg/walk/app {op: "finish"}` (адрес и опознание — `walk_settings`). Текст
итога и кнопки не пишутся заново: зовётся `bot.routers.finish.show_summary`, та
же функция, что отвечает на команду. Отличие одно — сообщение уходит не из
процесса бота, а отсюда, прямым запросом к Bot API с тем же токеном; поэтому
«Message» здесь — заготовка с номером чата, привязанная к клиенту Bot API.

Что решено:

* **Новый запуск существующего сообщения — только по явному «да» владельца.**
  Пока `WALK_APP_FINISH` не включена, сообщение не уходит: ответ `sent: false`,
  экран просит завершить командой `/finish` и закрывается.
* **Чату итог уходит только свой**: чат — номер подписавшего initData, чужой
  назвать нельзя.
* **Очередь ожидания бота** (кадры и слова без пары, `MaterialStore`) живёт в
  памяти другого процесса, отсюда её не прочитать. Итог из приложения собирается
  с пустой очередью; кадры, присланные в чат без записи, он не назовёт. Это
  предел решения, а не недосмотр: см. `docs/13-walk-mini-app.md`.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from src.domain import get_state
from src.domain.errors import DomainError

logger = logging.getLogger(__name__)

#: Результат шага: ушёл ли итог в чат.
SENT = "sent"
NO_INSPECTION = "no_inspection"
FAILED = "failed"


def has_inspection(chat_id: int) -> bool:
    """Есть ли у чата проверка. Нечитаемое состояние — «есть»: отказывать нечем."""
    try:
        return get_state(chat_id) is not None
    except DomainError:
        logger.exception("Завершение из приложения: состояние чата %s не читается", chat_id)
        return True


async def _send_summary(token: str, chat_id: int) -> None:
    # Лениво: цепочка `bot.routers.finish` тянет отчёт и PDF, а вебу без запроса
    # завершения они не нужны.
    from aiogram import Bot
    from aiogram.types import Chat, Message

    from src.bot.lang import chat_ui_lang
    from src.bot.material import MaterialStore
    from src.bot.routers.finish import show_summary

    bot = Bot(token)
    try:
        here = Message(
            message_id=0, date=datetime.now(UTC), chat=Chat(id=chat_id, type="private")
        ).as_(bot)
        await show_summary(here, chat_id, chat_ui_lang(chat_id), store=MaterialStore())
    finally:
        await bot.session.close()


def send_summary(token: str, chat_id: int) -> str:
    """Отправить итог в чат человека. `SENT` или причина, по которой не вышло."""
    if not has_inspection(chat_id):
        return NO_INSPECTION
    try:
        asyncio.run(_send_summary(token, chat_id))
    except Exception:  # — сеть, Bot API, расчёт: любой сбой — отказ словами экрана
        logger.exception("Завершение из приложения: итог в чат %s не ушёл", chat_id)
        return FAILED
    logger.info("Завершение из приложения: итог ушёл в чат %s", chat_id)
    return SENT
