"""Выбор языка бота человеком (D303, #411): `/lang` и кнопки языков.

Выбор живёт за Telegram ID (`lang_choice.py`, таблица `bot_ui_langs`) и
действует сразу — в том числе посреди начатой проверки, потому что он сильнее
её языка (`lang.pick_ui_lang`). Язык ОТЧЁТА и язык РЕЧИ он не трогает: это
отдельные поля проверки (T025), их выбирают при старте.

Своего состояния диалога у команды нет, обычного текста она не ждёт, поэтому
роутер стоит рядом со справкой и версией и на порядок разбора не влияет.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from .. import lang_choice
from ..keyboards import UI_LANG_PREFIX, ui_lang_keyboard
from ..lang import chat_ui_lang
from ..texts import UI_LANGS, t

logger = logging.getLogger(__name__)

#: Имя команды: одно место на роутер, меню и тесты.
LANG_COMMAND = "lang"


def build_lang_router() -> Router:
    """Роутер выбора языка бота: команда и нажатие кнопки языка."""
    router = Router(name="lang")

    @router.message(Command(LANG_COMMAND))
    async def on_lang_command(message: Message) -> None:
        lang = chat_ui_lang(message.chat.id)
        await message.answer(
            t("lang.ask", lang, current=t("lang.self_name", lang)),
            reply_markup=ui_lang_keyboard(),
        )

    @router.callback_query(F.data.startswith(UI_LANG_PREFIX))
    async def on_lang_chosen(callback: CallbackQuery) -> None:
        code = (callback.data or "").removeprefix(UI_LANG_PREFIX)
        message = callback.message
        if code not in UI_LANGS or not isinstance(message, Message):
            # Кнопка языка, которого в словаре уже нет, или нажатие без чата:
            # снять часики и не делать ничего — догадываться не о чем.
            await callback.answer()
            return
        try:
            lang_choice.CHOICES.choose(callback.from_user.id, code)
        except Exception:
            # Широко, как и всё вокруг выбора языка: человеку нужен ответ, а
            # разбор — в журнал целиком.
            logger.exception(
                "выбор языка %s человека %s не сохранился", code, callback.from_user.id
            )
            await callback.answer()
            await message.answer(t("lang.save_failed", chat_ui_lang(message.chat.id)))
            return
        await callback.answer()
        await message.answer(t("lang.chosen", code))

    return router
