"""Кадр того же нарушения — в уже занятую запись (#443, решения D243, D247).

Нарушение уникально по паре «пункт + зона» (`docs/02-domain.md`): несколько
однотипных объектов в одной зоне — одна запись с несколькими фотографиями и
одним вычетом. Боевой случай: аудитор по одному присылал кадры соусов без
маркировки в холодильной камере, каждый со своей подписью. Первый стал
записью, остальные движок отклонил занятой парой — кадры не прикрепились, и в
конце проверки бот показал их «без записи». Фотофиксация нарушения при этом
была сделана целиком, просто пропала.

Теперь фиксация, упёршаяся в занятую пару, кладёт кадры материала в занявшую
запись — когда бы кадр ни пришёл: следом за первым или через полчаса после
других нарушений (D247). Текст записи при этом сводит дешёвая модель
(`src/recognize/merge.py`): прежний текст и новые слова — в одну фразу-факт.

Порядок важен и не случаен:

1. **Сначала кадры.** Фотофиксация — это то, что потерялось в боевом случае, и
   от модели она не зависит: сбой модели кадр не роняет.
2. **Потом текст.** Модель не ответила или ответила подозрительно — текст
   остаётся прежним, причина уходит в лог. Правило 1 фиксации в силе: новый
   текст показывается аудитору тем же сообщением, и ответом на него словами он
   правит запись, как любую другую (сообщение запоминается картой показов).

Правка ответом (`correcting`) сюда не приходит: там аудитор правит СВОЮ запись
на занятую пару, и слить её с чужой значило бы молча снять одну из двух.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence

from aiogram.types import Message

from src import domain
from src.domain.errors import DomainError
from src.recognize.config import DEFAULT_LANG
from src.recognize.errors import RecognizeError
from src.recognize.merge import merge_wording

from . import journal, refusal
from .inspection import read_inspection
from .keyboards import edit_keyboard
from .shown import remember as remember_shown
from .shown import remember_origin
from .texts import t
from .view import zone_title

logger = logging.getLogger(__name__)


async def _attach(chat_id: int, n: int, file_ids: Sequence[str]) -> int:
    """Прикрепить кадры к записи #`n`. Возвращает, сколько легло.

    Не прикрепившийся кадр не теряется: он в списке присланного и найдётся при
    завершении среди кадров без записи (T068).
    """
    attached = 0
    for file_id in file_ids:
        try:
            await asyncio.to_thread(domain.attach_photo, chat_id, n, file_id)
        except DomainError:
            logger.exception("кадр %s не прикрепился к занятой записи #%s", file_id, n)
            continue
        attached += 1
    return attached


async def _rewrite(chat_id: int, taken: domain.Finding, words: str, report_lang: str) -> str:
    """Новый текст записи — или прежний, если свести не вышло. Сбой — в лог."""
    try:
        text = await asyncio.to_thread(merge_wording, taken.text, words, lang=report_lang)
    except RecognizeError:
        logger.warning(
            "комментарий записи #%s в чате %s не сведён моделью — остался прежним",
            taken.n,
            chat_id,
            exc_info=True,
        )
        return taken.text
    if text == taken.text:
        return text
    try:
        await asyncio.to_thread(domain.edit_finding, chat_id, taken.n, text=text)
    except DomainError:
        logger.exception(
            "сведённый комментарий записи #%s в чате %s движок не принял — остался прежним",
            taken.n,
            chat_id,
        )
        return taken.text
    return text


async def into_taken(
    message: Message,
    chat_id: int,
    taken: domain.Finding,
    *,
    file_ids: Sequence[str],
    words: str,
    lang: str,
    origin: int | None,
    reason: str,
) -> Message | None:
    """Положить кадры в занятую запись, свести её текст и показать её.

    Возвращает сообщение-показ записи — или ничего, если ни один кадр не лёг:
    тогда записи ничего не прибавилось, и аудитору сказано именно это.
    """
    item = refusal.item_title(taken.code, lang, chat_id=chat_id)
    place = zone_title(taken.zone, lang, chat_id=chat_id)
    attached = await _attach(chat_id, taken.n, file_ids)
    if attached == 0:
        await message.answer(t("record.merge_failed", lang, item=item, zone=place))
        journal.note(
            chat_id, "merge_failed", n=taken.n, code=taken.code, zone=taken.zone, reason=reason
        )
        return None
    inspection = read_inspection(chat_id)
    report_lang = DEFAULT_LANG if inspection is None else inspection.report_lang
    text = await _rewrite(chat_id, taken, words, report_lang)
    after = read_inspection(chat_id)
    current = None if after is None else after.finding(taken.n)
    # Число кадров — из проверки, а не прибавлением: показанное число обязано
    # быть тем, что уедет в отчёт.
    count = len((current or taken).photos)
    sent = await message.answer(
        t("record.merged", lang, item=item, zone=place, count=count, text=text),
        reply_markup=edit_keyboard(taken.n, lang),
    )
    # Это показ записи: ответ словами на него правит её (T204), а кадр ответом
    # на своё сообщение ложится в неё же (T205).
    remember_shown(chat_id, sent, taken.n)
    remember_origin(chat_id, origin, taken.n)
    journal.note(
        chat_id,
        "merged",
        finding=journal.finding(current or taken),
        words=words,
        attached=attached,
        rewritten=text != taken.text,
        reason=reason,
    )
    return sent
