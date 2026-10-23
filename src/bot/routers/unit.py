"""«Сменить пиццерию» посреди обхода (D626): если проверку завели не на ту точку.

Начинать заново значило бы потерять записанное, поэтому меняется только шапка
(`domain.set_unit`): записи, кадры и оценка остаются. Название проходит ту же
сверку, что на старте (`check_unit_name`, `match_unit`, `resolve_unit`, D392):
пиццерия должна быть в справочнике. Новую точку здесь не заводят — это шаг старта
(D233), а смена чинит опечатку, а не расширяет справочник.

Пока бот ждёт название, любая команда, кадр или голос отменяют смену и уходят дальше
своим путём (`SkipHandler`): иначе комментарий к следующему кадру стал бы названием
пиццерии. Роутер стоит сразу за стартом, до приёма материала.
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from src import domain
from src.domain.errors import DomainError, InspectionNotStarted, ValidationError
from src.domain.log_ids import log_id
from src.domain.unit_name import UNIT_NAME_LIMIT, check_unit_name

from .. import stops
from ..lang import chat_ui_lang
from ..states import UnitFlow
from ..texts import t
from ..unit_pick import UNIT_KNOWN, match_unit, resolve_unit

logger = logging.getLogger(__name__)

#: Имя команды: одно место на роутер, меню и тесты.
UNIT_COMMAND = "unit"


def build_unit_router() -> Router:
    """Роутер смены пиццерии: команда меню и ответ названием."""
    router = Router(name="unit")

    @router.message(Command(UNIT_COMMAND))
    async def on_unit_command(message: Message, state: FSMContext) -> None:
        lang = chat_ui_lang(message.chat.id)
        проверка = await asyncio.to_thread(domain.get_state, message.chat.id)
        if проверка is None:
            await stops.refuse(message, lang, step="unit.ask", key="unit.not_started")
            return
        await state.set_state(UnitFlow.waiting_unit)
        await message.answer(t("unit.ask", lang, unit=проверка.unit))

    @router.message(StateFilter(UnitFlow.waiting_unit), F.text, ~F.text.startswith("/"))
    async def on_unit_name(message: Message, state: FSMContext, space: str) -> None:
        lang = chat_ui_lang(message.chat.id)
        набрано = (message.text or "").strip()
        сверено = check_unit_name(набрано)
        if сверено.name is None:
            await stops.refuse(
                message,
                lang,
                step="unit.name",
                key=f"start.{сверено.problem}",
                limit=UNIT_NAME_LIMIT,
                typed=набрано,
            )
            return
        сверка = await asyncio.to_thread(match_unit, набрано, сверено.name.name, tenant=space)
        решение = resolve_unit(сверено.name, сверка, space)
        if решение.status != UNIT_KNOWN:
            await stops.refuse(
                message, lang, step="unit.name", key="unit.unknown", name=решение.name
            )
            return
        await _change(message, state, lang, решение.name)

    @router.message(StateFilter(UnitFlow.waiting_unit))
    async def on_other(message: Message, state: FSMContext) -> None:
        """Команда, кадр или голос вместо названия — смена отменена, сообщение идёт дальше."""
        await state.clear()
        await message.answer(t("unit.cancelled", chat_ui_lang(message.chat.id)))
        raise SkipHandler

    return router


async def _change(message: Message, state: FSMContext, lang: str, unit: str) -> None:
    try:
        прежняя = await asyncio.to_thread(domain.get_state, message.chat.id)
        новая = await asyncio.to_thread(domain.set_unit, message.chat.id, unit)
    except InspectionNotStarted:
        await state.clear()
        await stops.refuse(message, lang, step="unit.name", key="unit.not_started")
        return
    except ValidationError:
        await state.clear()
        await stops.refuse(message, lang, step="unit.name", key="unit.same", name=unit)
        return
    except DomainError:
        logger.exception("пиццерия проверки в чате %s не сменилась", log_id(message.chat.id))
        await state.clear()
        await stops.refuse(message, lang, step="unit.name", key="unit.failed")
        return
    await state.clear()
    было = прежняя.unit if прежняя is not None else ""
    повторов = sum(1 for f in новая.findings if f.repeat)
    текст = t("unit.changed", lang, old=было, new=новая.unit)
    if повторов:
        текст += t("unit.repeats_check", lang, n=повторов)
    await message.answer(текст)
