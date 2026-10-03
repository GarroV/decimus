"""Правка записи ОТВЕТОМ на сообщение бота (задача T204, решение D081).

Решение D081: правку вносят ответом на сообщение бота — новый комментарий
приходит как реплай на отбивку записи, и по нему заново ищется нужный пункт
чеклиста, а не создаётся отдельный путь правки. Дословная формулировка
владельца целиком лежит в `docs/furca/decisions.md`, D081.

Три правила, из которых собран этот модуль.

**Адресует ответ КОНКРЕТНУЮ запись.** Телеграм присылает сообщение, на которое
отвечают, и по его номеру находится запись — карта ведётся в заметках бота
(`sidecar.record_of`). «Последняя запись» адресатом быть не может: на точке
между разбором и ответом проходят минуты, и за это время аудитор успевает
прислать ещё кадр.

**Ответ не короткий — сначала решается, правит ли он текст той же записи** (#454,
D294, D295).
«Не ранч, а терияки» — это правка формулировки, а не новое нарушение. Дешёвая
модель получает запись целиком (пункт, класс, зону, текст) и слова аудитора
(`src/recognize/revise.py`) и отвечает одним из двух. Правка текста меняет
только формулировку той же записи — общей дверью правок (`apply_edit`); пункт,
класс и зона не трогаются. Другое нарушение идёт дальше, в разбор. Модель
отказала — запись не меняется, и бот говорит об этом словами: уйди такой ответ
в разбор, вместо правки молча завелась бы другая запись.

**Другое нарушение — пункт ищется заново, тем же путём.** Сверка со списком
нарушений, а если она не сошлась — модель, а если и модель молчит — ручной
перечень. Своей дороги для выбора пункта нет намеренно: одни и те же слова
обязаны давать один и тот же ответ, а две дороги разошлись бы молча.

**Ответ не на запись работает как раньше.** Аудитор отвечает и на свои кадры
(связывание комментария, T053), и на служебные сообщения бота. Такой ответ
уходит дальше по роутерам нетронутым — `SkipHandler`, тем же приёмом, что и
брошенный вопрос о новой формулировке (`routers/edit.py`).

**Короткий ответ, который о пункте не говорит, в разбор не идёт** (D254, D255):
«класс D2» меняет класс, «не повтор» снимает пометку повтора, «повтор» ставит
её, а «да»/«нет» ответом на вопрос «считать повтором?» отвечают на вопрос. Эти
ответы узнаются целиком (`reply_words`); фраза, где есть что-то ещё, идёт к
модели правки (выше). Кнопки «Класс», «Формулировка», «Повтор ×2» из-под записи
сняты (D254), и правка словами — их замена.

Кадр в этом разборе не участвует: у ответа его нет, а у записи он уже есть.
Прикреплять к правке нечего, и модель смотрит на слова человека — как и велит
D081.
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.types import Message

from src import domain
from src.recognize.errors import RecognizeError
from src.recognize.revise import Revision, revise_finding

from .. import refusal, reply_words, sealed, sidecar
from ..inspection import read_inspection
from ..lang import chat_ui_lang
from ..pending import PendingStore
from ..shown import remember as remember_shown
from ..shown import remember_origin
from ..texts import t
from ..view import zone_title
from .edit import answer_repeat, apply_edit, set_repeat
from .record import analyze, hear_voice

logger = logging.getLogger(__name__)


def _addressed(message: Message) -> int | None:
    """Запись, о которой говорит ответ аудитора, — или ничего.

    Ничего — обычный исход: ответ на кадр, на вопрос «Разобрать?», на итог. В
    заметках карта только тех сообщений, которыми бот показывал записи.
    """
    replied = message.reply_to_message
    if replied is None:
        return None
    return sidecar.record_of(message.chat.id, replied.message_id)


def _asked(message: Message) -> sidecar.RepeatAsk | None:
    """Вопрос о повторе, на который отвечает аудитор, — или ничего (D255)."""
    replied = message.reply_to_message
    if replied is None:
        return None
    return sidecar.repeat_ask_of(message.chat.id, replied.message_id)


async def _short_answer(
    message: Message,
    chat_id: int,
    n: int,
    ask: sidecar.RepeatAsk | None,
    note: str,
    lang: str,
) -> bool:
    """Ответ, который правит запись без разбора (D254, D255). Возврат — обработан ли.

    Ответ на вопрос о повторе разбором не бывает никогда: «да» или «нет», а
    иначе бот переспрашивает. Отправь его в разбор — «в прошлый раз было
    иначе» завело бы пункт заново вместо ответа на вопрос.
    """
    if ask is not None:
        answer = reply_words.yes_no(note)
        if answer is None:
            await message.answer(t("record.repeat_unclear", lang, n=n))
        else:
            await answer_repeat(message, chat_id, n, ask.code, lang, yes=answer)
        return True
    mark = reply_words.repeat_mark(note)
    if mark is not None:
        await set_repeat(message, chat_id, n, lang, repeat=mark)
        return True
    level = reply_words.spoken_level(note)
    if level is not None:
        # Класс, которого пункт не допускает, отвергнет движок, и отказ уйдёт
        # аудитору как есть (`apply_edit`).
        await apply_edit(message, chat_id, n, lang, level=level)
        return True
    return False


async def _revision(
    chat_id: int, finding: domain.Finding, note: str, report_lang: str
) -> Revision | None:
    """Что слова аудитора делают с записью — или ничего, если модель отказала.

    Пункт и зона уходят модели словами на языке отчёта: формулировка, которую
    она вернёт, ляжет в отчёт, и язык у неё тот же (как у сведения, `merged`).
    """
    try:
        return await asyncio.to_thread(
            revise_finding,
            item_code=finding.code,
            item_text=refusal.item_title(finding.code, report_lang, chat_id=chat_id),
            level=finding.level,
            zone=f"{finding.zone} ({zone_title(finding.zone, report_lang, chat_id=chat_id)})",
            wording=finding.text,
            words=note,
            lang=report_lang,
        )
    except RecognizeError:
        logger.warning(
            "правка записи #%s в чате %s ответом не разобрана моделью — запись прежняя",
            finding.n,
            chat_id,
            exc_info=True,
        )
        return None


async def _revise(
    message: Message,
    chat_id: int,
    finding: domain.Finding,
    note: str,
    *,
    lang: str,
    report_lang: str,
) -> bool:
    """Правка текста той же записи (D294). Возврат — обработан ли ответ.

    Не обработан ровно один исход — «другое нарушение»: его разбирает прежний
    путь. Отказ модели обработан: запись прежняя, аудитору сказано, а в разбор
    ответ не идёт (D295).
    """
    n = finding.n
    revision = await _revision(chat_id, finding, note, report_lang)
    if revision is None:
        await message.answer(t("correct.revise_failed", lang, n=n))
        return True
    if revision.kind == "other":
        return False
    await apply_edit(message, chat_id, n, lang, text=revision.text)
    inspection = read_inspection(chat_id)
    after = None if inspection is None else inspection.finding(n)
    if after is None or after.text != revision.text:
        # Отказ движка `apply_edit` уже сказал аудитору сам.
        return True
    sent = await message.answer(t("correct.revised", lang, n=n, text=revision.text))
    # Ответом на подтверждение правят ту же запись (T204), а кадр ответом на
    # свои слова ложится в неё же (T205) — как у правки через разбор.
    remember_shown(chat_id, sent, n)
    remember_origin(chat_id, message.message_id, n)
    return True


def build_correct_router(*, pending: PendingStore) -> Router:
    """Роутер правки ответом. Стоит ДО приёма материала — иначе ответ уедет
    комментарием к ждущему кадру, и вместо правки появится вторая запись."""
    router = Router(name="correct")

    @router.message(F.reply_to_message, F.voice | (F.text & ~F.text.startswith("/")))
    async def on_reply(message: Message) -> None:
        chat_id = message.chat.id
        ask = _asked(message)
        n = ask.n if ask is not None else _addressed(message)
        if n is None:
            # Не про запись — пусть работает прежнее связывание комментария.
            raise SkipHandler
        lang = chat_ui_lang(chat_id)
        inspection = read_inspection(chat_id)
        if inspection is None:
            await message.answer(t("material.no_inspection", lang))
            return
        if sealed.is_sealed(chat_id):
            # Запрет T201 действует и здесь: правка ответом — та же правка
            # отчёта, только другой дверью.
            await sealed.refuse(message, lang)
            return
        if inspection.finding(n) is None:
            # Сообщения о снятых записях остаются в переписке навсегда, и
            # отвечают на них по ошибке. Завести по такому ответу новую запись
            # было бы худшим исходом: аудитор просил поправить, а получил бы
            # вторую строку в отчёте партнёру.
            await message.answer(t("edit.gone", lang, n=n))
            return

        note = (message.text or "").strip()
        if message.voice is not None:
            heard = await hear_voice(message, message.voice.file_id, lang)
            if heard is None:
                return
            note = heard.strip()
        if not note:
            await message.answer(t("correct.empty", lang, n=n))
            return
        if await _short_answer(message, chat_id, n, ask, note, lang):
            return
        finding = inspection.finding(n)
        if finding is not None and await _revise(
            message, chat_id, finding, note, lang=lang, report_lang=inspection.report_lang
        ):
            return

        await analyze(
            message,
            chat_id,
            note=note,
            # Кадры записи сюда не передаются намеренно: они уже прикреплены к
            # ней, и второй раз `attach_photo` получил бы тот же идентификатор.
            file_ids=(),
            source=domain.SOURCE_COMMENT,
            pending=pending,
            correcting=n,
            # Ответ аудитора становится истоком поправленной записи (T205):
            # кадр к ней он досылает ответом на свои же слова, и слова эти —
            # последние сказанные о записи, а не те, с которых она началась.
            origin=message.message_id,
        )

    return router
