"""Повторная отправка отчёта по уже завершённой проверке (#261, D122).

**Временная функция: обкатка формата.** Владелец просил возможность получить
отчёт по проведённой проверке ещё раз, чтобы посмотреть новую подачу на живых
данных — и сказал, что потом её уберём. Поэтому она намеренно сделана сбоку от
боевого пути, а не встроена в `finish.deliver`: убрать её должно быть одним
удалением файла и трёх строк регистрации.

**Отчёт пересобирается, оценка — нет.** Проверка считается по изданию
методики, при котором её начали (`edition.pin`), поэтому пересборка даёт те же
проценты и ту же букву: меняется подача, не результат. Это и есть причина, по
которой функция безопасна, а правка записанной проверки — запрещена.

**В историю ничего не пишется.** `deliver` после отдачи документа сливает
проверку в базу; здесь этого нет и быть не должно: проверка уже записана, и
второй слив сделал бы из одного визита два.

Кадры берутся по идентификаторам телеграма, как и при первой сборке. Пропажа
кадра здесь не повод отказать: документ собирается с отметкой о недостающем
снимке, потому что цель — посмотреть формат, а не выдать партнёру документ.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import FSInputFile, Message

from src.report import PhotoMissing, ReportError, build_pdf

from ..inspection import read_inspection
from ..lang import chat_ui_lang
from ..photos import download_all
from ..texts import t

log = logging.getLogger(__name__)

#: Имя команды: одно место на роутер, меню и тесты.
RESEND_COMMAND = "resend"


def build_resend_router() -> Router:
    """Роутер повторной отправки: одна команда и ничего больше."""
    router = Router(name="resend")

    @router.message(Command(RESEND_COMMAND))
    async def on_resend(message: Message) -> None:
        chat_id = message.chat.id
        lang = chat_ui_lang(chat_id)
        bot = message.bot
        inspection = read_inspection(chat_id)
        if bot is None or inspection is None:
            await message.answer(t("resend.no_inspection", lang))
            return

        await message.answer(t("resend.building", lang))
        refs = [ref for finding in inspection.findings for ref in finding.photos]
        refs += [ref for field in inspection.info.values() for ref in field.photos]
        with tempfile.TemporaryDirectory(prefix="bot-resend-") as tmp:
            found = await download_all(bot, refs, Path(tmp))
            try:
                pdf = await asyncio.to_thread(
                    build_pdf,
                    chat_id,
                    fetch_photo=found.get,
                    allow_missing_photos=True,
                )
            except (PhotoMissing, ReportError):
                # Причина уходит в журнал целиком, аудитору — что пересборка не
                # вышла: молчать нельзя, он ждёт документ.
                log.exception("повторная сборка отчёта не удалась: чат %s", chat_id)
                await message.answer(t("resend.failed", lang))
                return
            await message.answer_document(FSInputFile(pdf), caption=t("resend.caption", lang))

    return router
