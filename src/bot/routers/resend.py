"""Повторная выдача PDF без создания нового визита.

Связанная сохранённая проверка выдаётся из актуального снимка базы в охвате
аудитора. Без настройки БД или точной связи остаётся локальная сборка.
Отказ настроенной базы или связанного документа не заменяется старым состоянием.
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from pathlib import Path

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, FSInputFile, Message

from src import db
from src.db import queries, reports
from src.db.config import DATABASE_URL_VAR
from src.db.errors import DbError
from src.db.reach import reach_of
from src.domain.log_ids import log_id
from src.report import PhotoMissing, ReportError, build_pdf, current_pdf

from ..inspection import read_inspection
from ..lang import chat_ui_lang
from ..photos import download_all
from ..preliminary import remind
from ..texts import t

log = logging.getLogger(__name__)

#: Имя команды: одно место на роутер, меню и тесты.
RESEND_COMMAND = "resend"


def _linked_report(chat_id: int, *, space: str | None) -> tuple[bytes, str] | None:
    """Только точная связь локального снимка с историей, без поиска по точке."""
    if not (os.environ.get(DATABASE_URL_VAR) or "").strip():
        return None
    linked = db.find_pushed(chat_id)
    if linked is None:
        return None
    if not space:
        raise DbError("Не задано пространство аудитора для повторной выдачи PDF")
    reach = reach_of(space)
    detail = queries.get_inspection(linked.id, reach=reach, include_on_review=True)
    if detail is None:
        raise DbError("Связанная проверка недоступна для повторной выдачи PDF")
    ref = current_pdf.ensure_report(detail, reach=reach)
    return reports.fetch_report(ref), current_pdf.report_name(detail.inspection)


def build_resend_router() -> Router:
    """Роутер повторной отправки: одна команда и ничего больше."""
    router = Router(name="resend")

    @router.message(Command(RESEND_COMMAND))
    async def on_resend(message: Message, space: str | None = None) -> None:
        chat_id = message.chat.id
        lang = chat_ui_lang(chat_id)
        bot = message.bot
        inspection = read_inspection(chat_id)
        if bot is None or inspection is None:
            await message.answer(t("resend.no_inspection", lang))
            return

        await message.answer(t("resend.building", lang))
        try:
            linked = await asyncio.to_thread(_linked_report, chat_id, space=space)
        except (DbError, ReportError):
            log.exception("актуальный отчёт не выдан: чат %s", log_id(chat_id))
            await message.answer(t("resend.failed", lang))
            return
        if linked is not None:
            content, filename = linked
            await message.answer_document(
                BufferedInputFile(content, filename=filename), caption=t("resend.caption", lang)
            )
            await remind(message, chat_id, lang)
            return
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
                log.exception("повторная сборка отчёта не удалась: чат %s", log_id(chat_id))
                await message.answer(t("resend.failed", lang))
                return
            await message.answer_document(FSInputFile(pdf), caption=t("resend.caption", lang))
        # Повторная отправка — тоже предварительный отчёт, пока проверку не приняли
        # в вебе; принятой напоминание не уходит (`preliminary.remind` читает статус).
        await remind(message, chat_id, lang)

    return router
