"""Разбор материала и фиксация записи (T055, T057, T067, T117, T121).

Правила, из которых собран весь этот файл.

**Ни один кадр не уходит в модель без решения человека** (D046, задача T067). На
кадр без комментария бот отвечает вопросом «Разобрать?» с кнопкой. Не нажали и
прислали комментарий — вопрос снимается, и разбор идёт по словам: слова аудитора
сильнее догадки по картинке. Это не таймер и не окно ожидания (те были в
отменённом D045), а явное действие.

**Есть комментарий — разбирается комментарий, кадр в модель не уходит** (D081,
задача T202). Два потока, а не два источника одного разбора: есть комментарий —
в модель уходит только он, кадр без комментария по-прежнему разбирается сам
собой, но только по кнопке (D046, выше). Правило живёт одним местом —
`recognize.needs_photo(note)`, — и здесь оно спрашивается, а не повторяется: две
копии одного правила разошлись бы, и увидел бы это счёт за токены, а не человек.

**Запись ПО РАЗБОРУ появляется только после подтверждения** (задача T055,
принцип 3 конституции «модель предлагает, фиксирует человек»). Кандидаты
показываются кнопками, и по ним `add_finding` зовётся из обработчика нажатия.

**Фиксация СЛОВАМИ подтверждения не ждёт** (T121, D064). Решение D064 сняло
кнопку подтверждения с текстового пути — с открытой дверью вернуть её позже,
если понадобится. Сошлась сверка со списком нарушений — запись появляется
сразу, нажимать нечего. Принцип 3 этим уточнён, а
не отменён: он в силе там, где пункт угадывает система (разбор кадра, разбор
моделью), и снят там, где зона и суть названы человеком.

Цена решения известна заранее и была названа владельцу: сопоставление слов с
пунктом промахивается, и без кнопки промах становится тихим. Отсюда два
требования, которые здесь важнее самой правки. Показ записи обязан быть **виден**
— его собирает `view.fixed_block` из вопроса пункта, слов аудитора и строки
карты. И рядом с записью обязан остаться **выход к модели**: правка кода пункта
в чате не предусмотрена, а те же слова снова поднимут тот же пункт, поэтому без
«Разобрать моделью» неверный код чинить было бы нечем.

**Зона берётся из слов аудитора** (D047), последняя названная запоминается и
подставляется догадкой (D048). Отдельного шага «выберите зону» в потоке нет —
кнопки зон появляются ровно тогда, когда зону взять неоткуда.

Порядок вызовов: **сначала сверка со списком нарушений, модель — если сверка не
ответила** (T117, D063): решение D063 отдало предпочтение сверке со списком
нарушений перед рассуждением модели. `fast_path` зовётся ДО `classify`;
сработал — запись сделана, и разбора не происходит вовсе (замер блока
`recognize`: 4.3 с на текст, 5.3 с на кадр — ждём именно рассуждение модели).
Не сработал — всё дальше как было, а причина отказа (`FastPath.reason`) остаётся
в журнале: она для замера, а не для экрана.

Замеры (`INF09`, `INF10`, `INF11`) идут этим же путём и ничем не выделены,
кроме класса `D0` в подтверждении (задача T057): блоком `info` движка бот не
пользуется, они лежат записями среди находок.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import replace
from datetime import datetime, timezone
from math import ceil

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from src import domain
from src.domain.errors import DomainError
from src.recognize.classify import album_mode, classify, needs_photo
from src.recognize.errors import ModelUnavailable, RecognizeError
from src.recognize.fastpath import NO_CUE, FastItem, fast_path
from src.recognize.manual import ManualCandidate, manual_candidates, search_items
from src.recognize.models import UNKNOWN_ZONE, Candidate
from src.recognize.transcribe import transcribe

from .. import frame_copies, journal, refusal, sealed, sidecar, view
from ..inspection import read_inspection
from ..keyboards import (
    ANALYZE_PREFIX,
    CUES_ITEM_CALLBACK,
    CUES_ZONE_CALLBACK,
    MANUAL_CALLBACK,
    MANUAL_LEVEL_PREFIX,
    MANUAL_PAGE_PREFIX,
    MANUAL_PAGE_SIZE,
    MANUAL_PICK_PREFIX,
    MODEL_CALLBACK,
    PICK_PREFIX,
    SKIP_CALLBACK,
    ZONE_FOR_ITEM_PREFIX,
    ZONE_FOR_MANUAL_PREFIX,
    ZONE_FOR_PICK_PREFIX,
    analyze_keyboard,
    candidates_keyboard,
    edit_keyboard,
    fixed_keyboard,
    levels_keyboard,
    manual_keyboard,
    zone_conflict_keyboard,
    zones_keyboard,
)
from ..lang import chat_langs, chat_speech_lang
from ..material import Comment, Material, MaterialStore, PhotoGroup
from ..pending import Offer, PendingStore, Proposal
from ..photos import fetch_bytes
from ..phrases import Learned, learn, recall
from ..shown import remember as remember_shown
from ..shown import remember_origin, tell_refusal
from ..texts import t
from ..zones import DICTIONARY, WORDS, ZoneConflict, allowed_zones, resolve_zone

logger = logging.getLogger(__name__)

#: Что делать с кадрами, которые пришли без подписи и ждут комментария.
WaitingHandler = Callable[[Message, PhotoGroup, str], Awaitable[None]]

#: Сколько кадров пачки разбирается за раз (T232, решения D091 и D093). Число
#: названо владельцем, а не выведено замером, и второе решение объясняет, почему
#: именно предел, а не порции: пачка больше пяти — исключение, а не рабочий
#: случай, и остальные кадры аудитор присылает отдельной пачкой.
#:
#: Предел стоит здесь, у РАЗБОРА, а не на приёме материала: платит пачка
#: вызовами модели (по вызову на кадр, T206), а принимать кадры бот обязан все —
#: они идут в список присланного, и отброшенный на приёме кадр исчез бы вместе с
#: ним. Прокомментированной пачки предел не касается вовсе: там один разбор на
#: все кадры, сколько бы ракурсов человек ни снял.
BATCH_LIMIT = 5


def make_waiting_handler(pending: PendingStore) -> WaitingHandler:
    """Кадр без комментария — спросить «Разобрать?» и запомнить вопрос (T067)."""

    async def ask(message: Message, group: PhotoGroup, lang: str) -> None:
        count = len(group.photo_file_ids)
        key = "material.photo_taken" if count == 1 else "material.album_taken"
        anchor = group.message_ids[0]
        sent = await message.answer(
            t(key, lang, count=count), reply_markup=analyze_keyboard(anchor, lang)
        )
        pending.offer(
            group.chat_id,
            Offer(
                anchor_id=anchor,
                file_ids=group.photo_file_ids,
                question_id=getattr(sent, "message_id", None),
            ),
        )

    return ask


async def _drop_question(message: Message, chat_id: int, offer: Offer) -> None:
    """Снять кнопку «Разобрать?»: кадр уже забрал комментарий.

    Не снять её — значит оставить аудитору кнопку, которая потратит вызов
    модели на кадр, по которому запись уже сделана. Отказ телеграма на это
    молчаливым не остаётся, но и разбор не роняет: кнопка вторична.
    """
    bot = message.bot
    if bot is None or offer.question_id is None:
        return
    try:
        await bot.edit_message_reply_markup(
            chat_id=chat_id, message_id=offer.question_id, reply_markup=None
        )
    except Exception:
        logger.warning("не удалось снять кнопку «Разобрать» в чате %s", chat_id, exc_info=True)


async def hear_voice(message: Message, file_id: str, lang: str) -> str | None:
    """Голосовое в текст. Не вышло — сказать и попросить текстом, не роняя проверку.

    Общая на весь блок, а не своя у каждого роутера: голосом аудитор и заводит
    запись, и правит её ответом (T204), и это одно и то же действие продукта.
    Вторая копия разошлась бы с первой на тексте отказа — то есть ровно там, где
    человек остаётся без подсказки, что делать дальше.
    """
    bot = message.bot
    raw = None if bot is None else await fetch_bytes(bot, file_id)
    if raw is None:
        await message.answer(t("record.voice_not_downloaded", lang))
        return None
    try:
        heard = await asyncio.to_thread(transcribe, raw)
    except RecognizeError as exc:
        await message.answer(t("record.voice_failed", lang, reason=f"{exc}."))
        return None
    await message.answer(t("record.heard", lang, note=view.shorten(heard)))
    return heard


async def _hand(
    message: Message,
    chat_id: int,
    pending: PendingStore,
    proposal: Proposal,
    text: str,
    markup: InlineKeyboardMarkup,
) -> None:
    """Показать предложение кнопками и запомнить, под каким сообщением оно живёт.

    Один помощник на все показы одного разговора — кандидаты, вопрос о зоне,
    страница ручного перечня, выбор класса. Пропусти его хоть один показ, и
    нажатие под этим сообщением искало бы предложение в карте, которой в нём
    нет: в одиночном потоке оно нашлось бы по последнему показанному, а в пачке
    (T206) получило бы отказ — то есть правило разошлось бы ровно там, где оно
    и нужно.
    """
    sent = await message.answer(text, reply_markup=markup)
    pending.propose(chat_id, proposal, at=getattr(sent, "message_id", None))


async def _show_candidates(
    message: Message,
    chat_id: int,
    proposal: Proposal,
    pending: PendingStore,
    lang: str,
    *,
    also_seen: bool = False,
) -> None:
    """Показать предложения модели, пометив уже занятые пары «пункт + зона» (T137).

    Занятый пункт приходит сюда штатно: сверка со списком нарушений упёрлась в
    отказ движка, и материал ушёл модели — на кадре бывает второе нарушение.
    Но модель предлагает и тот же пункт тоже, и непомеченным он неотличим от
    остальных: нажатие даёт второй отказ подряд по поводу, о котором бот только
    что сказал сам.
    """
    lines = view.candidate_lines(
        proposal.candidates, lang, refusal.occupied_pairs(chat_id), chat_id=chat_id
    )
    # Под правкой (T204) спрашивается другое: не «что записать», а «чем
    # поправить запись №N». Число кадров там ни при чём — кадры остались у
    # записи, и «Кадров: 0» читалось бы как потеря материала.
    #
    # У кадра из пачки (T206) вопрос тот же, но с номером кадра: сообщений в
    # отбивке столько же, сколько кадров, и без номера аудитор не соотнесёт
    # список с тем, что снимал.
    if also_seen:
        # Увиденное на кадрах сверх слов (D180) — своим заголовком: аудитор
        # этого не говорил, и выдать догадку по картинке за его слова нельзя.
        text = t("record.also_seen", lang, lines=lines)
    elif proposal.correcting is not None:
        text = t("record.candidates_correcting", lang, n=proposal.correcting, lines=lines)
    elif proposal.batch is not None:
        no, total = proposal.batch
        text = t("record.candidates_batch", lang, no=no, total=total, lines=lines)
    else:
        text = t("record.candidates", lang, count=len(proposal.file_ids), lines=lines)
    if proposal.question:
        text = t("record.question", lang, question=proposal.question) + "\n\n" + text
    await _hand(
        message,
        chat_id,
        pending,
        proposal,
        text,
        candidates_keyboard(
            len(proposal.candidates), lang, correcting=proposal.correcting is not None
        ),
    )


async def _show_manual_page(
    message: Message,
    chat_id: int,
    proposal: Proposal,
    pending: PendingStore,
    page: int,
    lang: str,
) -> None:
    """Страница ручного перечня: 70+ пунктов зоны кнопками разом не показать.

    Занятые пары «пункт + зона» помечаются здесь же (T173), но не на кнопке:
    там уже стоят код и формулировка во всю ширину ряда (T217), и пометка съела
    бы ровно то, ради чего аудитор перечень открыл. Она уходит в текст над клавиатурой — у
    ручного перечня он до сих пор нёс только номер страницы, тогда как у
    перечня модели там стоит сам список.

    Пометка нужна тут по той же причине, что и в перечне модели: занятый пункт
    попадает в перечень штатно (на кадре бывает второе нарушение), и
    непомеченным он неотличим от остальных — нажатие даёт отказ по поводу, о
    котором бот уже говорил.
    """
    pages = max(1, ceil(len(proposal.manual) / MANUAL_PAGE_SIZE))
    page = max(0, min(page, pages - 1))
    start = page * MANUAL_PAGE_SIZE
    shown = proposal.manual[start : start + MANUAL_PAGE_SIZE]
    # Служебный префикс класса с кнопки снимается (T217): те же классы продукт
    # читает колонкой методики и предлагает кнопками следующим шагом.
    titles = [
        (start + shift, item.code, view.without_level_prefix(item.title, item.levels))
        for shift, item in enumerate(shown)
    ]
    # Зона перечня — та, по которой он собран: пара, а не код. Тот же пункт в
    # другой зоне законен, и пометить его значило бы отговаривать от верного.
    taken = view.manual_taken_line(
        [item.code for item in shown],
        proposal.zone_hint,
        lang,
        refusal.occupied_pairs(message.chat.id),
    )
    header = (
        t(
            "record.manual_page_correcting",
            lang,
            n=proposal.correcting,
            page=page + 1,
            pages=pages,
        )
        if proposal.correcting is not None
        else t("record.manual_page", lang, page=page + 1, pages=pages)
    )
    await _hand(
        message,
        chat_id,
        pending,
        proposal,
        header + taken,
        manual_keyboard(titles, page, pages, lang),
    )


async def _ask_zone(
    message: Message,
    chat_id: int,
    proposal: Proposal,
    pending: PendingStore,
    prefix: str,
    lang: str,
    *,
    item_code: str | None = None,
) -> None:
    """Зону взять неоткуда — назвать её кнопкой (D047: обычно она из слов).

    `item_code` назван — кнопками идут **только зоны, допустимые методикой для
    этого пункта** (T266). Спрашивать тем, чего движок не примет, нельзя: с
    T271 пара «пункт + зона» вне методики отвергается, и кнопка кончалась бы
    отказом на ровном месте — аудитор жмёт, а запись не проходит.

    Пункт не назван — спрашиваем всеми зонами: сузить перечень нечем, а
    показать неполный значило бы отнять верный ответ.
    """
    разрешённые = allowed_zones(item_code, chat_id=chat_id)
    zones = [
        (zone.code, zone.title(lang))
        for zone in domain.list_zones(chat_id=chat_id)
        if zone.code in разрешённые
    ]
    текст = (
        t("record.ask_zone", lang)
        if item_code is None
        else t("record.ask_zone_for_item", lang, code=item_code)
    )
    await _hand(message, chat_id, pending, proposal, текст, zones_keyboard(prefix, zones))


async def _open_manual(
    message: Message, chat_id: int, proposal: Proposal, pending: PendingStore, lang: str
) -> None:
    """Ручной выбор пункта: сперва ПОИСК СЛОВОМ, листание — запасной вход (T267).

    Порядок задан замером (07.09.2026): ручной перечень — 123 пункта по 8 на
    страницу, то есть 16 страниц листания в цехе с занятыми руками. Слово
    аудитора поднимает единицы пунктов, и показывать надо их.

    **Поиску зона не нужна** (T265, T267): слово называет объект, а не место, и
    резать найденное зоной значило бы вернуть дефект #218 — пункт про печь был
    недостижим из холодного цеха даже вручную. Зона спрашивается ПОСЛЕ выбора
    пункта и спрашивается тем, что методика этому пункту даёт (T266).

    Слово ничего не подняло (или слов нет вовсе) — спрашиваем зону и показываем
    её пункты страницами. Тупика нет ни в одной ветке (#219).
    """
    _, report_lang = chat_langs(chat_id)
    if proposal.note.strip():
        try:
            найденные = await asyncio.to_thread(
                search_items, proposal.note, lang=report_lang, chat_id=chat_id
            )
        except RecognizeError as exc:
            logger.warning("поиск пункта словом не сработал в чате %s: %s", chat_id, exc)
            найденные = ()
        if найденные:
            await _show_manual_page(
                message, chat_id, replace(proposal, manual=найденные), pending, 0, lang
            )
            return
    # Памяти о прошлой записи здесь больше нет (T264): зона либо уже выведена
    # словами или словарём, либо её спрашивают кнопкой.
    zone = proposal.zone_hint
    if not zone:
        if proposal.note.strip():
            await message.answer(t("record.nothing_by_words", lang))
        await _ask_zone(message, chat_id, proposal, pending, ZONE_FOR_MANUAL_PREFIX, lang)
        return
    try:
        # Слова сюда уже не идут: они либо подняли пункты выше, либо не подняли
        # ничего, и повторять ту же выборку значило бы получить тот же пустой
        # ответ и показать пустые кнопки на последнем рубеже выбора.
        items = await asyncio.to_thread(manual_candidates, zone, lang=report_lang, chat_id=chat_id)
    except RecognizeError as exc:
        # Сырой текст исключения — в журнал, а не в чат (тот же принцип, что
        # у отказа движка, T127): в нём бывают пути на диске и ссылки на
        # внутренние документы.
        logger.warning("ручной перечень не собрался в чате %s: %s", chat_id, exc)
        await message.answer(t("record.unavailable", lang))
        return
    ready = replace(proposal, manual=items, zone_hint=zone)
    await _show_manual_page(message, chat_id, ready, pending, 0, lang)


def _model_suggestion(proposal: Proposal) -> domain.Suggestion | None:
    """Что предложила МОДЕЛЬ по этому материалу (D077, T181).

    Берётся ПЕРВЫЙ кандидат, а не тот, который аудитор нажал. Разница здесь и
    есть весь смысл задачи: запиши мы нажатую кнопку, предложенная и итоговая
    тройки совпадали бы всегда, и «модель предложила одно, аудитор поправил на
    другое» перестало бы существовать как явление. Выбор второго кандидата —
    это и есть правка, ради которой сигнал собирается.

    Пустая зона приводится к `UNKNOWN`: у модели это осмысленный ОТВЕТ — «из
    слов аудитора места не видно», — а пустая строка уехала бы в базу как
    `NULL`, то есть как «модель промолчала», рядом с названным пунктом.
    """
    top = proposal.candidates[0] if proposal.candidates else None
    if top is None:
        return None
    return domain.Suggestion(
        code=top.code,
        level=top.level,
        zone=top.zone or UNKNOWN_ZONE,
        confidence=top.confidence,
    )


async def _try_fast(
    message: Message,
    chat_id: int,
    base: Proposal,
    pending: PendingStore,
    lang: str,
    item: FastItem,
) -> bool:
    """Записать пункт, который нашла сверка со списком нарушений (T117, T121).

    Возвращает, легла ли запись. Не легла — дальше разбирает модель, как раньше.

    Сам вызов сверки стоит у вызывающего (`analyze`), а не здесь: с T231 её
    ответ читают двое — этот путь берёт найденный пункт, а правка ответом
    смотрит на ПРИЧИНУ отказа. Второй вызов ради причины стоил бы повторного
    чтения методики с диска на каждой правке.

    Язык здесь — интерфейса, а не отчёта, и это не оплошность: `item.title` —
    вопрос чек-листа, который аудитор читает у себя в чате. В запись он не
    попадает никогда (её текстом становятся слова самого аудитора), поэтому
    языку отчёта подчиняться ему незачем.

    Отказ движка (та же пара «пункт + зона» уже занята) тупиком не заканчивается:
    причину аудитор уже прочитал, а материал уходит модели — там пункт можно
    выбрать другой. Раньше эту роль играли кнопки рядом с предложением, но
    предложения больше нет, и упереться в отказ молча аудитор не должен.

    Предложение запоминается ПОСЛЕ удачной записи: оно живёт здесь только ради
    кнопки «Разобрать моделью» под ней. Не записалось — и кнопке нечего
    разбирать: материал уже у модели.
    """
    saved = await _save(
        message,
        chat_id,
        code=item.code,
        level=item.level,
        zone=item.zone,
        text=base.note,
        file_ids=base.file_ids,
        source=base.source,
        lang=lang,
        # Здесь слова аудитора СОВПАДАЮТ с текстом записи, и всё равно
        # передаются своим полем: совпадение это свойство быстрого пути, а не
        # правило. Полагаться на него значило бы читать выборку по-разному в
        # зависимости от того, каким путём легла запись.
        words=base.note,
        auto=item,
        zone_spoken=base.zone_spoken,
        zone_from_cues=base.zone_from_cues,
        zone_source=base.zone_source,
        # Быстрый путь — это и есть тот список терминов, который владелец просил
        # пополнять (D077). Промах здесь опаснее всего: подтверждения у него нет
        # (D064), и увидеть его можно только правкой записи следом. Уверенности
        # у сверки нет вовсе — строгий критерий либо сходится, либо нет, — и
        # ноль вместо неё был бы ложью: «система ни в чём не уверена» это
        # осмысленное утверждение, и по нему ставят порог отбора.
        suggested=domain.Suggestion(code=item.code, level=item.level, zone=item.zone),
        # Правка ответом (T204) идёт этой же дорогой: сверка ищет пункт по
        # словам аудитора одинаково, заводит он запись или поправляет.
        correcting=base.correcting,
        origin=base.origin,
    )
    if saved is None:
        return False
    # Предложение вешается на само сообщение с записью: под ним и стоит кнопка
    # «Разобрать моделью», а адресоваться она обязана этой записи, а не
    # последнему, что бот показал в чате.
    pending.propose(chat_id, replace(base, fast=item), at=getattr(saved, "message_id", None))
    return True


async def _try_learned(
    message: Message,
    chat_id: int,
    base: Proposal,
    pending: PendingStore,
    lang: str,
    report_lang: str,
    learned: Learned,
) -> bool:
    """Записать пункт, который подняла карта синонимов (T285, решение D119).

    Возвращает, кончилось ли дело записью или вопросом о зоне. Не кончилось —
    материал разбирается дальше как раньше, и карта в этом больше не участвует.

    Зовётся ПОСЛЕ сверки со списком нарушений и только когда та промолчала:
    прямое совпадение карту не спрашивает (D119). Дальше решение владельца
    держится на одном: сказанное однажды не переспрашивается второй раз.

    Подтверждения у этой записи нет — ровно как у записи по словам (D064), и
    по той же причине под ней стоит выход к модели: код пункта правкой не
    меняется, а те же слова поднимут тот же синоним. Показывается она своим
    блоком (`view.learned_block`): строки карты кадров здесь не было, и
    подписать накопленное ею значило бы соврать.

    Два случая кончаются отказом, и оба — не тупик, а обычный разбор дальше:
    класс у пункта не один (синоним класса не хранит, а выбирать его за
    аудитора нельзя) и названная человеком зона пункту не годится (методика
    такой пары не даёт, T271, а подменять сказанное молча система не вправе).
    """
    code = learned.code
    levels = domain.allowed_levels(code, chat_id=chat_id)
    if len(levels) != 1:
        logger.info(
            "синоним поднял пункт %s в чате %s, но класс у пункта не один — разбор идёт дальше",
            code,
            chat_id,
        )
        return False
    level = levels[0]
    # Зона у накопленного пункта берётся оттуда же, откуда всегда (T263): слова
    # аудитора, словарь объектов карты кадров, сама методика. Карта синонимов
    # зоны не хранит и хранить не будет — она отвечает на «какой пункт», а не
    # на «где».
    zone = base.zone_hint or domain.only_zone(code, chat_id=chat_id) or ""
    if not zone:
        # Взять зону неоткуда: у пункта их несколько, а места аудитор не назвал.
        # Спрашивается она кнопками ТОЛЬКО допустимых зон (T266). Это не то
        # «переспрашивание одного и того же», от которого уходит D119: пункт
        # карта уже знает, и человек называет одно место, а не выбирает из 123
        # пунктов.
        item = ManualCandidate(
            code=code,
            levels=(level,),
            title=domain.get_item(code, chat_id=chat_id).question(report_lang),
        )
        await _ask_zone(
            message,
            chat_id,
            replace(base, manual=(item,), picked=0, picked_level=level),
            pending,
            ZONE_FOR_ITEM_PREFIX,
            lang,
            item_code=code,
        )
        return True
    if zone not in allowed_zones(code, chat_id=chat_id):
        logger.info(
            "синоним поднял пункт %s, а зона «%s» ему методикой не дана — разбор идёт дальше",
            code,
            zone,
        )
        return False
    saved = await _save(
        message,
        chat_id,
        code=code,
        level=level,
        # Пусто — зону подставит сам `_save` из единственной зоны пункта и
        # скажет об этом оговоркой. Подставь её здесь — оговорка пропала бы, и
        # аудитор не увидел бы, откуда взялось место в записи (#218).
        zone=base.zone_hint,
        text=base.note,
        file_ids=base.file_ids,
        source=base.source,
        lang=lang,
        words=base.note,
        learned=learned.phrase,
        zone_spoken=base.zone_spoken,
        zone_from_cues=base.zone_from_cues,
        zone_source=base.zone_source,
        # Предложения здесь нет и быть не может: модель по этому материалу не
        # звали вовсе. Записать предложением накопленный синоним значило бы
        # утопить настоящие промахи модели в выборке управляющей компании —
        # тот же довод, что у ручного перечня (D077).
        suggested=None,
        correcting=base.correcting,
        origin=base.origin,
    )
    if saved is None:
        return False
    # Кнопка «Разобрать моделью» адресуется этой записи и требует предложения
    # (`on_model`). Пункт в нём — тот же, что лёг: модель по материалу не
    # звали, и разобрать его ею аудитор вправе ровно так же, как после сверки.
    # Строка карты пуста намеренно: её тут не было, и выдуманная соврала бы.
    pending.propose(
        chat_id,
        replace(
            base,
            fast=FastItem(
                code=code,
                level=level,
                zone=zone,
                title=domain.get_item(code, chat_id=chat_id).question(report_lang),
                cue="",
            ),
        ),
        at=getattr(saved, "message_id", None),
    )
    return True


async def _correct_zone(message: Message, chat_id: int, base: Proposal, lang: str) -> bool:
    """Ответ назвал ТОЛЬКО зону — поправить зону записи, не трогая пункт (T231, D090).

    Возвращает, поправлена ли запись. Нет — дальше всё идёт как раньше.

    Случай из решения владельца: бот отбился, что запись сохранена, аудитор
    отвечает на эту отбивку «это был другой цех» — и ждёт, что запись переедет,
    а не что у него спросят, какое нарушение записать. До задачи такой ответ
    уходил в модель: пункта в нём нет, и она возвращала либо не то, либо ничего,
    а в отсутствие ключа модели открывался ручной перечень — то есть самая
    частая правка стоила дороже всех и заканчивалась ничем.

    **Признак «в словах только зона» берётся у самого продукта, а не выдумывается
    здесь.** Сверка со списком нарушений отвечает `NO_CUE`, когда ни одна строка
    карты не произнесена целиком, — это и есть «объекта в словах нет». Любая
    другая причина отказа означает, что объект назван (строка задета, но
    непонятна колонка; строк несколько; пункт не той зоны), и тогда работает
    прежняя дорога: пункт ищется заново моделью. Иначе ответ «в горячем цехе
    течёт кран» переставил бы зону и молча потерял бы найденное нарушение.

    Пункт, класс и текст записи передаются свои же, прежние: движок меняет
    только названные поля, а показ и карты сообщений собираются там же, где у
    всех остальных путей (`_save`). Своей ветки показа у правки зоны нет
    намеренно — вторая собралась бы иначе и разошлась бы с первой на первой же
    вычитке.
    """
    n = base.correcting
    if n is None or not base.zone_spoken:
        return False
    zone = base.zone_hint
    if not zone:
        return False
    inspection = read_inspection(chat_id)
    current = None if inspection is None else inspection.finding(n)
    if current is None:
        # Запись сняли между отбивкой и ответом. Заводить по такому ответу новую
        # нечего: пункта в словах нет вовсе.
        return False
    saved = await _save(
        message,
        chat_id,
        code=current.code,
        level=current.level,
        zone=zone,
        text=current.text,
        # Кадры у записи уже есть, и второй раз тот же идентификатор движок
        # не примет.
        file_ids=(),
        source=base.source,
        lang=lang,
        correcting=n,
        # Зону аудитор назвал ЭТИМИ словами — оговорка была бы неправдой ровно
        # там, где человек только что сказал обратное.
        zone_spoken=True,
        zone_from_cues=False,
        origin=base.origin,
    )
    return saved is not None


async def analyze(
    message: Message,
    chat_id: int,
    *,
    note: str,
    file_ids: tuple[str, ...],
    source: str,
    pending: PendingStore,
    fast: bool = True,
    correcting: int | None = None,
    origin: int | None = None,
    batch: tuple[int, int] | None = None,
) -> None:
    """Сверить со списком нарушений, а если не сошлось — спросить разбор.

    Есть комментарий — разбирается комментарий, и кадр не уходит в модель
    (D081, T202). Скачивания у телеграма тогда тоже не происходит: байты,
    которые никуда не поедут, стоили бы запроса к телеграму на каждый
    прокомментированный кадр. Правило одно на продукт и живёт в `recognize`
    (`needs_photo`) — бот его не повторяет своими словами, а спрашивает.

    `fast=False` приходит с кнопки «Разобрать моделью»: второй заход обязан
    дойти до модели, иначе кнопка возвращала бы тот же быстрый ответ по кругу.

    `correcting` — номер записи, которую этот разбор ПРАВИТ (T204). Путь тот же
    самый и намеренно: аудитор поправляет запись теми же словами, какими её
    заводил, и вторая дорога для тех же слов разошлась бы с первой — сверка
    отвечала бы на правку не так, как на первичный материал.

    `origin` — сообщение аудитора, из которого этот материал собрался (T205).
    Ответом на него аудитор досылает кадр, и кадр обязан попасть в получившуюся
    запись. Пусто — материал пришёл не от слов человека (разбор кадра кнопкой),
    и досылать кадр не к чему.

    `batch` — какой это кадр пачки и сколько их всего (T206). Не пусто —
    предложение по нему живёт наравне с предложениями по соседним кадрам, а
    отбивка называет номер кадра.
    """
    lang, report_lang = chat_langs(chat_id)
    # Зона выводится ОДНИМ местом (T263): слова аудитора, затем словарь
    # объектов карты кадров, а не вывелось — спросим кнопками. Памяти о прошлой
    # записи среди источников нет (T264, #218): обратный порядок и был
    # дефектом — «в зале лужа» ложилось в горячий цех, потому что там была
    # прошлая запись, а пункт про печь уезжал в холодный цех.
    #
    # Пункт здесь ещё не выбран, поэтому `item_code` пуст: зоны кнопок сузит
    # тот, кто спрашивает, — он к тому времени пункт уже знает.
    resolved = await asyncio.to_thread(resolve_zone, note, None, chat_id=chat_id)
    base = Proposal(
        file_ids=file_ids,
        source=source,
        note=note,
        zone_hint=resolved.zone or "",
        zone_source=_source_of(resolved.source),
        cues_zone="" if resolved.conflict is None else resolved.conflict.dictionary,
        correcting=correcting,
        slot=pending.next_slot(),
        batch=batch,
        origin=origin,
    )
    # Вход разбора целиком (#367): на этих словах и этой зоне система дальше
    # принимает решение, и разбирающему случай нужно ровно это. Голос сюда
    # приходит расшифровкой — аудио не хранится (D179).
    journal.note(
        chat_id,
        "material",
        slot=base.slot,
        source=source,
        note=note,
        file_ids=list(file_ids),
        copies=[frame_copies.copy_name(f) for f in file_ids],
        zone_hint=base.zone_hint,
        zone_source=base.zone_source,
        zone_conflict=base.cues_zone,
        correcting=correcting,
        origin=origin,
        batch=list(batch) if batch else None,
        fast=fast,
    )
    if resolved.conflict is not None:
        # Названная зона разошлась со словарём объектов («холодный цех,
        # пицца-печь»). Молча не пишется ни то, ни другое: обе стороны сразу
        # правдой быть не могут, и выбирать между словом человека и данными
        # управляющей компании бот не вправе (T266, требование владельца).
        await _ask_zone_conflict(message, chat_id, base, pending, resolved.conflict, lang)
        return
    await _analyze_resolved(message, chat_id, base, pending, lang, report_lang, fast=fast)


def _frame_without_record(chat_id: int, file_ids: Sequence[str], outcome: str) -> None:
    """Кадру — причина, по которой записи по нему не появилось (T269, #219).

    Отдельно от накопителя намеренно, и это не дробление ради дробления.
    Причина у кадра известна СРАЗУ: «система ничего не нашла» — уже ответ, и
    при завершении проверки аудитор обязан его прочитать, а не просто увидеть
    кадр без объяснений. Судьба самой ФОРМУЛИРОВКИ в этот момент ещё не
    решена: после «ничего не нашлось» показывается ручной перечень, и запись
    по ней вполне может появиться. Запиши мы накопитель здесь — одна
    формулировка легла бы в него дважды (сначала «не нашлось», следом «не
    записывать»), а читается он счётом «встретилось N раз», то есть дубль
    прямо искажает ответ управляющей компании.
    """
    sidecar.remember_outcome(chat_id, file_ids, outcome)


def _lost(
    chat_id: int,
    *,
    file_ids: Sequence[str],
    note: str,
    zone: str,
    zone_source: str,
    outcome: str,
    suggested: domain.Suggestion | None = None,
) -> None:
    """Записи по этому материалу не появилось — сказать почему и не потерять (T269).

    Две разные вещи разом, и обе нужны:

    * **кадру** проставляется исход, чтобы в конце проверки по каждому кадру без
      записи была названа причина, а не только показан сам кадр (#219);
    * **формулировке** заводится строка накопителя, чтобы управляющая компания
      увидела, чего не хватило в карте кадров (#228). Пустая формулировка в
      накопитель не идёт: копится именно она, а кадр без слов покрывать
      словарём нечего — он уже назван своим исходом выше.

    Зовётся там, где судьба формулировки решена окончательно: аудитор нажал
    «не записывать» или движок отказал парой, которой методика не даёт. Там,
    где впереди ещё есть путь к записи, ставится только исход кадра
    (`_frame_without_record`).

    Молчание на этом месте и было дефектом: аудитор сказал о находке, система
    не нашла пункт, аудитор пошёл дальше — и не осталось ни записи, ни следа.
    """
    _frame_without_record(chat_id, file_ids, outcome)
    сказанное = note.strip()
    if not сказанное:
        return
    inspection = read_inspection(chat_id)
    domain.record_uncovered(
        chat_id,
        domain.UncoveredEntry(
            note=сказанное,
            suggested_code="" if suggested is None else suggested.code,
            suggested_level="" if suggested is None else suggested.level,
            suggested_zone="" if suggested is None else suggested.zone,
            zone=zone,
            zone_source=zone_source,
            outcome=(
                domain.OUTCOME_REFUSED
                if outcome == sidecar.OUTCOME_REFUSED
                else domain.OUTCOME_ABANDONED
            ),
            checklist_version="" if inspection is None else inspection.checklist_version,
            at=datetime.now(timezone.utc).isoformat(),
        ),
    )


def _source_of(resolved: str) -> str:
    """Ответ `resolve_zone` — словарём накопителя (`domain.ZONE_SOURCES`).

    Словари разные, потому что разное и называют: `resolve_zone` отвечает, чем
    зона выведена ИЛИ что её надо спросить, а накопитель хранит, чем она в
    итоге получена. «Спросить» исходом не бывает: к моменту записи её либо
    назвали кнопкой, либо записи нет.
    """
    if resolved == WORDS:
        return domain.ZONE_SOURCE_WORDS
    if resolved == DICTIONARY:
        return domain.ZONE_SOURCE_DICTIONARY
    return ""


async def _ask_zone_conflict(
    message: Message,
    chat_id: int,
    base: Proposal,
    pending: PendingStore,
    conflict: ZoneConflict,
    lang: str,
) -> None:
    """Назвать расхождение зоны до фиксации и дать выбор (T266).

    Выбор ровно тот, который назвал владелец: зона объекта или другой пункт.
    Третьей кнопки «оставить мою зону» нет намеренно — методика этому пункту
    такой зоны не даёт, и движок пару не примет (T271): кнопка предлагала бы
    то, что кончится отказом.
    """
    названия = {zone.code: zone.title(lang) for zone in domain.list_zones(chat_id=chat_id)}
    dictionary = названия.get(conflict.dictionary, conflict.dictionary)
    await _hand(
        message,
        chat_id,
        pending,
        base,
        t(
            "record.zone_conflict",
            lang,
            spoken=названия.get(conflict.spoken, conflict.spoken),
            object=conflict.phrase,
            dictionary=dictionary,
        ),
        zone_conflict_keyboard(lang, dictionary),
    )


async def _analyze_resolved(
    message: Message,
    chat_id: int,
    base: Proposal,
    pending: PendingStore,
    lang: str,
    report_lang: str,
    *,
    fast: bool,
) -> None:
    """Разбор материала, у которого зона уже выведена (или её решили спросить).

    Отдельной функцией, потому что сюда возвращаются ДВА входа: обычный разбор
    и кнопка «зона объекта» под расхождением (T266). Второй дорогой был бы
    второй разбор, и он разошёлся бы с первым на первой же правке.
    """
    note = base.note
    # Пачка с комментарием разбирается моделью всегда (D180): быстрый путь
    # записал бы по словам, и кадры никто бы не посмотрел — ровно тот случай,
    # ради которого правило заведено.
    album = base.correcting is None and album_mode(note, len(base.file_ids))

    if fast and note and not album:
        found = await asyncio.to_thread(
            fast_path,
            base.note,
            base.zone_hint or None,
            zone_fixed=base.zone_from_cues,
            lang=lang,
            chat_id=chat_id,
        )
        journal.note(
            chat_id,
            "fast_path",
            slot=base.slot,
            code=None if found.item is None else found.item.code,
            reason=found.reason,
        )
        if found.item is not None:
            if await _try_fast(message, chat_id, base, pending, lang, found.item):
                return
        else:
            # `reason` — для замера (`tools/fastpath_measure.py`) и разбора,
            # поэтому он идёт в журнал, а не в чат: аудитору он ничего не
            # объясняет, а объяснять отказ, за которым просто следует обычный
            # разбор, нечем. Читает его отсюда только правка зоны (T231).
            logger.info("быстрый путь не сработал в чате %s: %s", chat_id, found.reason)
            if found.reason == NO_CUE and await _correct_zone(message, chat_id, base, lang):
                return
            # Прямого совпадения с методикой не нашлось — спрашиваем карту
            # синонимов (T285, решение D119). Порядок тут и есть всё решение:
            # выученное работает ПОСЛЕ методики и ДО модели, то есть не
            # подменяет собой сверку и не платит запросом к модели за то, что
            # система уже знает. Ключ карты — язык РЕЧИ аудитора, а не
            # интерфейса и не отчёта.
            #
            # Отказ базы сюда не долетает и долететь не может (`bot.phrases`):
            # невыученное слово — не повод остановить обход точки.
            запомненное = await asyncio.to_thread(_recall_words, chat_id, note=note)
            if запомненное is not None and await _try_learned(
                message, chat_id, base, pending, lang, report_lang, запомненное
            ):
                return

    bot = message.bot
    photo = (
        await fetch_bytes(bot, base.file_ids[0])
        if not album and needs_photo(note) and bot is not None and base.file_ids
        else None
    )
    # Пачка с комментарием (D180): модель смотрит все кадры вместе со словами.
    # Не скачавшийся кадр не останавливает разбор — уходят те, что есть.
    photos: tuple[bytes, ...] = ()
    if album and bot is not None:
        fetched = await asyncio.gather(*(fetch_bytes(bot, f) for f in base.file_ids))
        photos = tuple(raw for raw in fetched if raw is not None)

    if base.batch is None:
        # У пачки (T206) «Разбираю…» на каждый кадр — это N одинаковых строк
        # между отбивками, то есть шум ровно там, где аудитор читает список.
        # Сколько кадров разбирается, сказано один раз, до цикла.
        await message.answer(t("record.thinking", lang))
    try:
        suggestion = await asyncio.to_thread(
            classify,
            note,
            photo,
            base.zone_hint or None,
            lang=report_lang,
            chat_id=chat_id,
            photos=photos,
        )
    except ModelUnavailable as exc:
        journal.note(chat_id, "model_failed", slot=base.slot, kind="unavailable", error=str(exc))
        # Модель недоступна — проверка не встаёт: тот же перечень пунктов
        # показывается кнопками, выбирает человек (контракт `recognize`).
        # Сырой текст исключения — в журнал, а не в чат: в нём бывают пути на
        # диске и ссылки на внутренние документы, аудитору они ни к чему.
        logger.warning("модель недоступна в чате %s: %s", chat_id, exc)
        await message.answer(t("record.degraded", lang))
        await _open_manual(message, chat_id, base, pending, lang)
        return
    except RecognizeError as exc:
        journal.note(chat_id, "model_failed", slot=base.slot, kind="error", error=str(exc))
        logger.warning("разбор недоступен в чате %s: %s", chat_id, exc)
        await message.answer(t("record.unavailable", lang))
        return

    # Что ушло в модель и что вернулось (#367). Без этой строки промах модели
    # разбирается по скриншотам: предложения живут в памяти процесса, а
    # запись, которую аудитор удалил, уносит с собой и их.
    journal.note(
        chat_id,
        "model",
        slot=base.slot,
        shortlist=list(suggestion.shortlist),
        used_photo=suggestion.used_photo,
        photo_copy=frame_copies.copy_name(base.file_ids[0]) if photo is not None else None,
        album_frames=len(photos),
        candidates=journal.candidates(suggestion.candidates),
        also_seen=journal.candidates(suggestion.also_seen),
        question=suggestion.question,
        needs_human=suggestion.needs_human,
        degraded=suggestion.degraded,
        usage=suggestion.usage,
    )
    if not suggestion.candidates:
        if suggestion.question:
            await message.answer(t("record.question", lang, question=suggestion.question))
        await message.answer(t("record.nothing_found", lang))
        # Причина кадра известна уже здесь (T269, #219): до этой задачи кадр,
        # по которому система не нашла ничего, доживал до завершения проверки
        # без единого слова о том, почему он остался без записи. Формулировка
        # в накопитель отсюда НЕ уходит — ручной перечень открывается следом,
        # и запись по ней ещё может появиться.
        await asyncio.to_thread(
            _frame_without_record, chat_id, base.file_ids, sidecar.OUTCOME_NOTHING_FOUND
        )
        await _open_manual(message, chat_id, base, pending, lang)
        await _offer_also_seen(message, chat_id, base, suggestion.also_seen, pending, lang)
        return

    proposal = replace(base, candidates=suggestion.candidates, question=suggestion.question)
    await _show_candidates(message, chat_id, proposal, pending, lang)
    await _offer_also_seen(message, chat_id, base, suggestion.also_seen, pending, lang)


async def _offer_also_seen(
    message: Message,
    chat_id: int,
    base: Proposal,
    also_seen: Sequence[Candidate],
    pending: PendingStore,
    lang: str,
) -> None:
    """Предложить увиденное на кадрах пачки сверх слов аудитора (D180).

    Только предложение: запись появится, если аудитор нажмёт кнопку, — как и
    у любого кандидата. Своё предложение и свой слот, потому что это другой
    выбор, чем по словам: нажатие под одним сообщением не должно гасить другое.
    Источник — кадр, а не слова: этого аудитор не говорил.
    """
    if not also_seen:
        return
    extra = replace(
        base,
        source=domain.SOURCE_PHOTO,
        candidates=tuple(also_seen),
        question="",
        slot=pending.next_slot(),
    )
    await _show_candidates(message, chat_id, extra, pending, lang, also_seen=True)


async def _analyze_frames(
    message: Message,
    chat_id: int,
    file_ids: tuple[str, ...],
    pending: PendingStore,
    lang: str,
) -> None:
    """Разобрать кадры, по которым аудитор нажал «Разобрать?» (D046, T206).

    Один кадр — один разбор, как было. **Пачка кадров разбирается по кадру**, и
    отбивка приходит списком отдельными сообщениями, по сообщению на кадр
    (решение D081). Ответ на любое из них правит именно ту запись, к которой
    оно относится, — механизм для этого уже есть (`routers/correct.py`), и
    работает он потому, что каждая запись показана своим сообщением.

    Пачка — это кадры БЕЗ комментария. Кадры с комментарием остаются одним
    материалом и одной записью, как требует и спека (`docs/06-mvp-bot.md`,
    шаг 3), и D081: сказал человек об этих кадрах одно — значит, нарушение одно,
    сколько бы ракурсов он ни снял. Разводит эти два случая наличие слов, а не
    число кадров, и разводится это здесь: сюда приходят ровно те кадры, о
    которых аудитор не сказал ничего.

    До задачи пачка давала ОДНУ запись на все кадры, и модель при этом видела
    только первый кадр (`analyze` берёт `file_ids[0]`): второй и третий уезжали
    в отчёт прикреплёнными к чужому пункту, никем не разобранные. Теперь каждый
    разбирается сам, и это N вызовов модели вместо одного — цена названа в
    `docs/06-mvp-bot.md`, шаг 3, и человек платит её осознанно: он видит, сколько
    кадров разбирается, до того как разбор начнётся.
    """
    if len(file_ids) <= 1:
        await analyze(
            message,
            chat_id,
            note="",
            file_ids=file_ids,
            source=domain.SOURCE_PHOTO,
            pending=pending,
        )
        return
    sent = len(file_ids)
    taken = file_ids[:BATCH_LIMIT]
    total = len(taken)
    if sent > total:
        # Про лишние кадры бот ГОВОРИТ (D093): молча отброшенные, они выглядели
        # бы записанными — аудитор ушёл бы с точки, считая фотофиксацию
        # сделанной. Сами кадры при этом не пропадают: они уже в заметках (T068)
        # и вернутся списком при завершении проверки.
        await message.answer(
            t("record.batch_over_limit", lang, count=sent, limit=BATCH_LIMIT, rest=sent - total)
        )
    else:
        await message.answer(t("record.batch", lang, count=total))
    for no, file_id in enumerate(taken, start=1):
        await analyze(
            message,
            chat_id,
            note="",
            # Кадр уходит в модель и в запись ровно один — свой. Оставь мы всю
            # пачку, каждая запись забрала бы себе все кадры, и в отчёте один и
            # тот же снимок стоял бы под всеми нарушениями сразу.
            file_ids=(file_id,),
            source=domain.SOURCE_PHOTO,
            pending=pending,
            batch=(no, total),
        )


def _recall_words(chat_id: int, *, note: str) -> Learned | None:
    """Спросить карту синонимов о сказанном (T285, решение D119).

    Отдельной функцией и в потоке — по той же причине, что и пополнение ниже:
    язык речи читается из состояния проверки, карта из базы, и оба чтения
    блокирующие.
    """
    return recall(note, lang=chat_speech_lang(chat_id), chat_id=chat_id)


def _remember_words(chat_id: int, *, code: str, words: str) -> None:
    """Сложить сказанное синонимом пункта (T285, решение D119).

    Отдельной функцией, потому что зовётся из потока: язык речи читается из
    состояния проверки, а карта — из базы, и оба чтения блокирующие.

    Ни один отказ отсюда наружу не выходит (`bot.phrases`): запись аудитора к
    этому времени уже сделана и показана, и «не сохранено» из-за невыученного
    слова было бы неправдой о его работе.
    """
    learn(words, item_code=code, lang=chat_speech_lang(chat_id), chat_id=chat_id)


def _via(*, auto: FastItem | None, learned: str, suggested: domain.Suggestion | None) -> str:
    """Чем запись поставлена — для журнала разбора (#367)."""
    if auto is not None:
        return "fast_path"
    if learned:
        return "learned"
    return "suggestion" if suggested is not None else "manual"


async def _save(
    message: Message,
    chat_id: int,
    *,
    code: str,
    level: str,
    zone: str,
    text: str,
    file_ids: Sequence[str],
    source: str,
    lang: str,
    words: str = "",
    auto: FastItem | None = None,
    learned: str = "",
    zone_spoken: bool = False,
    zone_from_cues: bool = False,
    zone_source: str = "",
    suggested: domain.Suggestion | None = None,
    correcting: int | None = None,
    origin: int | None = None,
) -> Message | None:
    """Зафиксировать запись и показать её (T055, T121), а с T204 — и поправить.

    Возвращает сообщение, которым запись показана, — или ничего, если записать
    не вышло. Отказ движка — не редкость и не ошибка бота: тот же пункт в той же
    зоне аудитор снимает дважды за обход. Поэтому предложение после отказа не
    выбрасывается, и человек выбирает другого кандидата, а не пересылает кадр.

    Само сообщение нужно вызывающему, а не только признак удачи: под ним живут
    и карта правки ответом (T204), и кнопка «Разобрать моделью», которую надо
    привязать именно к этой записи (T206).

    `auto` не пуст, когда запись легла по словам сама, без подтверждения (T121,
    D064). Тогда и показ другой: не одна строка, а блок с вопросом пункта,
    словами аудитора и строкой карты, и под ним — выход к модели рядом с
    правками. Подтверждённая запись такого блока не получает: её пункт аудитор
    уже прочитал на кнопке, а таблица после каждого кадра запрещена
    (`docs/06-mvp-bot.md`, шаг 5).

    Комментарий аудитора в запись не пишется намеренно: поле `comment` движок
    печатает в отчёте партнёру, а сказанное вслух на точке для партнёра не
    предназначено. В отчёт идёт формулировка, собранная по правилам фиксации.

    `words` — те самые сказанные слова, и хранятся они ОТДЕЛЬНО от текста записи
    (T183). До этой задачи они не доживали нигде: `pending` держит их в памяти
    процесса, а в запись они не попадали по причине абзацем выше — и разобрать,
    почему система промахнулась, было не по чему. Словами считается весь
    материал аудитора об этом кадре, каким он пришёл: подпись, отдельное
    сообщение и расшифровка голоса приходят сюда одной строкой (`Proposal.note`),
    и разделять их нечем — для разбора промаха важно то, на чём система приняла
    решение. Пусто — аудитор не сказал ничего (разбор голого кадра).

    `learned` — формулировка, которой этот пункт уже называли, когда запись
    поставила карта синонимов (T285, D119). Не пусто — значит, подтверждения не
    было и строки карты кадров тоже не было: показ у такой записи свой
    (`view.learned_block`), а кнопки те же, что у записи по словам, — выход к
    модели под ней обязателен. Не пусто ещё и означает «в карту уже ложилось»:
    второй строки сработавший синоним не заводит.

    `suggested` — что система предложила ДО нажатия (D077, T181). Передаётся
    здесь и только здесь: это единственный момент, когда предложение и запись
    существуют одновременно. Предложения живут в `pending`, то есть в памяти
    процесса, и после перезапуска взять их будет неоткуда — сигнал о промахе
    терялся бы целиком, как терялся до этой задачи. Пусто — предложения не было
    (ручной перечень); домен запишет это как «система не предлагала ничего», и
    в базе такая запись не выглядит попаданием модели.

    `zone_source` — чем зона получена (`domain.ZONE_SOURCES`), и нужен он
    ровно одному читателю: строке накопителя, которая заводится, когда движок
    отказал (T269). Два признака рядом (`zone_spoken`, `zone_from_cues`)
    отвечают на другой вопрос — какую оговорку показать аудитору, — и кнопку
    от слов не различают вовсе. Пусто — зону дал не человек и не словарь
    (ответ модели, зона самого пункта), и накопитель это так и запишет.

    `correcting` — номер записи, которую надо ПОПРАВИТЬ вместо того, чтобы
    заводить новую (T204, D081). Аудитор ответил на сообщение бота словами
    «система поняла не так», и вторая запись о том же нарушении — ровно то,
    чего он этим ответом избегает: в отчёт партнёру уехали бы обе.

    `origin` — сообщение аудитора, из которого запись выросла (T205). Ответом
    на него он досылает кадр, и кадр попадает в эту же запись.

    Ни слова аудитора, ни предложение системы правка не переписывает, и это не
    упущение: `domain.edit_finding` их полей не знает вовсе. Сигнал о промахе
    (T183, T181) держится на разнице между тем, что система предложила сначала,
    и тем, чем запись стала в итоге, — перезапиши мы предложение правкой, промах
    перестал бы существовать ровно в том случае, ради которого сигнал и собирают.
    """
    zone_from_item = False
    if not zone_spoken:
        # Зону аудитор не называл. У пункта она бывает известна из самой
        # методики: 59 пунктов из 136 живут ровно в одной зоне, и пункт про печь
        # среди них. Тогда это ответ, а не догадка, — и он сильнее словаря
        # объектов: словарь пишет управляющая компания от руки, а зоны пункта
        # движок этой же методики и проверяет.
        #
        # Стоит ДО запрета сдачи и до вызова движка намеренно: зона входит в
        # пару «пункт + зона», по которой движок проверяет занятость, и
        # подменять её после проверки значило бы проверить не то, что пишем.
        своя = domain.only_zone(code, chat_id=chat_id)
        if своя is not None and своя != zone:
            zone = своя
            # Два разных ответа на «откуда зона» — два разных текста: «из
            # карты кадров» про зону из пункта было бы неправдой, а неправда в
            # оговорке хуже её отсутствия (#218).
            zone_from_cues = False
            zone_from_item = True
    if sealed.is_sealed(chat_id):
        # Последний рубеж запрета (T201, D080): сюда приходят и нажатия под
        # старыми предложениями, показанными ДО сдачи отчёта. Проверка стоит у
        # самой записи, а не только на входах, потому что вход у неё не один.
        await sealed.refuse(message, lang)
        return None
    # Движок вызывается подпроцессом, и это 27 мс на вызов. В цикле событий
    # такой вызов останавливает бота ЦЕЛИКОМ — он не обслуживает ни других
    # аудиторов, ни таймеры альбомов (замер T101: подтверждение записи стоило
    # 47 мс, и очередь росла линейно — двадцать аудиторов, секунда последнему).
    try:
        if correcting is not None:
            finding = await asyncio.to_thread(
                domain.edit_finding,
                chat_id,
                correcting,
                code=code,
                level=level,
                zone=zone,
                text=text,
            )
        else:
            finding = await asyncio.to_thread(
                domain.add_finding,
                chat_id,
                code,
                level,
                zone,
                text,
                source=source,
                words=words,
                suggested=suggested,
            )
    except DomainError as exc:
        # Отказ движка разбирается, а не пересказывается (T127): пункт и зона
        # называются по-человечески, а занятая пара «пункт + зона» — частый
        # случай — приводит к кнопкам той записи, которая её заняла. У правки
        # разбор свой: он знает номер правимой записи и потому не отправит
        # аудитора к кнопкам той самой записи, которую тот и правит.
        told = (
            refusal.not_changed(chat_id, correcting, code=code, zone=zone, lang=lang, exc=exc)
            if correcting is not None
            else refusal.not_recorded(chat_id, code=code, zone=zone, lang=lang, exc=exc)
        )
        # Отказ, назвавший запись, — её показ: ответ словами на него правит её,
        # а не заводит новую из чужого ждущего кадра (T227).
        await tell_refusal(message, chat_id, told, lang)
        journal.note(
            chat_id,
            "refused",
            code=code,
            level=level,
            zone=zone,
            correcting=correcting,
            reason=str(exc),
        )
        if correcting is None and told.clash is None:
            # Записи по этой формулировке не появилось, и пара не занята —
            # значит движок отверг саму пару «пункт + зона» (T271). Это ровно
            # тот сигнал, ради которого заведён накопитель (T269, #228).
            #
            # Занятая пара сюда не идёт намеренно: там запись о том же
            # нарушении уже есть, формулировка покрыта картой, и строка
            # накопителя утопила бы настоящие пробелы в частом случае — тот же
            # пункт в той же зоне аудитор снимает дважды за обход. Правка (
            # `correcting`) не идёт по той же причине: правимая запись жива.
            await asyncio.to_thread(
                _lost,
                chat_id,
                file_ids=file_ids,
                note=words,
                zone=zone,
                zone_source=zone_source,
                outcome=sidecar.OUTCOME_REFUSED,
                suggested=suggested,
            )
        return None
    for file_id in file_ids:
        try:
            await asyncio.to_thread(domain.attach_photo, chat_id, finding.n, file_id)
        except DomainError:
            # Запись уже есть, и терять её из-за одного кадра нельзя. Молчанием
            # это не станет: не прикрепившийся кадр остаётся в заметках без
            # записи и попадёт в список кадров без записи при завершении (T068).
            logger.exception("кадр %s не прикрепился к записи #%s", file_id, finding.n)
    # Зона записи здесь НЕ запоминается (T264, #218). Раньше запоминалась и
    # подставлялась следующему кадру первой догадкой (D048) — и это был весь
    # механизм промаха, ради которого задача заведена: пункт про печь уезжал в
    # холодный цех, потому что там была прошлая запись. Источников зоны теперь
    # три, и прошлой записи среди них нет (`bot.zones.resolve_zone`).
    # `get_state` — чтение файла, 0.1 мс: в поток не выносится, обёртка стоила
    # бы дороже самой операции. Оценка здесь больше не считается вовсе (T162,
    # D072): процент по ходу обхода не показывается, а считать его ради
    # выброшенного числа значило бы платить подпроцессом (26 мс) за каждую
    # запись впустую.
    saved = read_inspection(chat_id)
    current = None if saved is None else saved.finding(finding.n)
    shown = current or finding
    journal.note(
        chat_id,
        "corrected" if correcting is not None else "recorded",
        via=_via(auto=auto, learned=learned, suggested=suggested),
        finding=journal.finding(shown),
        words=words,
        zone_source=zone_source,
        zone_from_item=zone_from_item,
        origin=origin,
    )
    if correcting is not None:
        # Правка ответом (T204): показ собран из тех же частей, но заголовком
        # говорит, что записи не прибавилось. Кнопки — те же, что были под
        # записью: правка не отменяет ни зоны, ни класса, ни удаления, а после
        # сверки оставляет и выход к модели.
        sent = await message.answer(
            view.corrected_block(
                shown,
                lang,
                chat_id=chat_id,
                title=refusal.item_title(shown.code, lang, chat_id=chat_id),
                cue="" if auto is None else auto.cue,
                zone_from_cues=zone_from_cues,
                zone_from_item=zone_from_item,
            ),
            # Запись без подтверждения — и поправленная тем же путём — обязана
            # держать выход к модели: код пункта правка в чате не меняет.
            reply_markup=(edit_keyboard if auto is None and not learned else fixed_keyboard)(
                finding.n, lang
            ),
        )
    elif auto is not None:
        sent = await message.answer(
            view.fixed_block(
                shown,
                lang,
                title=auto.title,
                cue=auto.cue,
                chat_id=chat_id,
                zone_from_cues=zone_from_cues,
                zone_from_item=zone_from_item,
            ),
            reply_markup=fixed_keyboard(finding.n, lang),
        )
    elif learned:
        # Пункт подняла карта синонимов (T285): строки карты кадров здесь не
        # было, и показывать её нечем — блок свой, а кнопки те же, что у записи
        # по словам.
        sent = await message.answer(
            view.learned_block(
                shown,
                lang,
                title=refusal.item_title(shown.code, lang, chat_id=chat_id),
                chat_id=chat_id,
                zone_from_cues=zone_from_cues,
                zone_from_item=zone_from_item,
            ),
            reply_markup=fixed_keyboard(finding.n, lang),
        )
    else:
        # Подтверждённая запись показывается не строкой, а блоком (T135): к
        # строке добавлены вопрос пункта словами и то, что уйдёт в отчёт
        # партнёру. Код в строке глазами не проверяется, а формулировка —
        # проверяется, и прочитать её надо ДО того, как документ уедет.
        sent = await message.answer(
            view.confirmed_block(
                shown,
                lang,
                chat_id=chat_id,
                title=refusal.item_title(shown.code, lang, chat_id=chat_id),
                zone_from_cues=zone_from_cues,
                zone_from_item=zone_from_item,
            ),
            reply_markup=edit_keyboard(finding.n, lang),
        )
    # Этим сообщением аудитор и правит запись — ответом на него (T204). Карта
    # ведётся здесь, а не в роутере правки: показ записи собирается в этом
    # месте, и любой другой был бы вторым списком мест, который однажды отстал
    # бы от первого на один показ.
    remember_shown(chat_id, sent, finding.n)
    # А ответом на СВОЁ сообщение аудитор досылает в эту запись кадр (T205). Обе
    # карты ведутся рядом по той же причине: запись показана здесь, и разнеси их
    # по разным местам — одна отстала бы от другой на один путь фиксации.
    remember_origin(chat_id, origin, finding.n)
    if correcting is None and auto is None and not learned:
        # Совпадение было НЕПРЯМЫМ: сверка со списком нарушений пункт не нашла,
        # а человек его назвал — кнопкой кандидата или в ручном перечне. С D119
        # сказанное складывается синонимом пункта и работает при следующем
        # поиске; прямое совпадение (`auto`) и сработавший синоним (`learned`)
        # второй строки не заводят.
        #
        # Правка (`correcting`) сюда не идёт намеренно: строку карты не
        # переписывает никто (прав UPDATE у роли приложения нет, T284), и
        # накопить по правке значило бы либо ничего не изменить, либо завести
        # синоним рядом с уже неверным. Снятие неверной строки управляющей
        # компанией заведено отдельной задачей (#255).
        #
        # Стоит ПОСЛЕ показа записи: поход в базу — это десятки миллисекунд, и
        # платить ими за задержку ответа аудитору на точке незачем. Запись уже
        # сделана и уже показана, а память — дело следующего разбора.
        await asyncio.to_thread(_remember_words, chat_id, code=code, words=words)
    return sent


def build_record_router(*, store: MaterialStore, pending: PendingStore) -> Router:
    """Роутер разбора: вопрос «Разобрать?», предложения кнопками, фиксация."""
    router = Router(name="record")

    def chat_of(callback: CallbackQuery) -> tuple[Message, int, str] | None:
        """Сообщение, чат и язык интерфейса — или ничего, если нажатие пришло не оттуда."""
        message = callback.message
        if not isinstance(message, Message):
            return None
        chat_id = message.chat.id
        lang, _ = chat_langs(chat_id)
        return message, chat_id, lang

    async def stale(message: Message, lang: str) -> None:
        await message.answer(t("record.stale", lang))

    @router.callback_query(F.data.startswith(ANALYZE_PREFIX))
    async def on_analyze(callback: CallbackQuery) -> None:
        await callback.answer()
        here = chat_of(callback)
        if here is None:
            return
        message, chat_id, lang = here
        anchor = (callback.data or "").removeprefix(ANALYZE_PREFIX)
        if not anchor.isdigit():
            return
        offer = pending.take_offer(chat_id, int(anchor))
        if offer is None:
            await message.answer(t("record.analyze_gone", lang))
            return
        # Снять группу с очереди ожидания: иначе следующий комментарий сядет на
        # кадр, по которому разбор уже идёт.
        store.queue(chat_id).resolve_reply(offer.anchor_id, Comment(text=""))
        await _drop_question(message, chat_id, offer)
        await _analyze_frames(message, chat_id, offer.file_ids, pending, lang)

    @router.callback_query(F.data == MODEL_CALLBACK)
    async def on_model(callback: CallbackQuery) -> None:
        """«Разобрать моделью»: сверка по словам ответила не то или не на всё.

        После T121 стоит под уже сделанной записью и остаётся единственным
        способом починить неверный ПУНКТ: правка в чате меняет зону, класс и
        формулировку, но не код, а те же слова снова поднимут тот же пункт.

        Сама запись при этом не трогается. Разбор её не удаляет и не правит: он
        предлагает кандидатов, и что делать с прежней записью, решает аудитор
        кнопкой «Удалить». Удалять её здесь молча было бы хуже — отказ модели
        оставил бы аудитора и без записи, и без разбора.

        Материал тот же — те же слова и тот же кадр, — но сверка со списком в
        этот раз пропускается: иначе кнопка возвращала бы ту же запись по кругу.
        """
        await callback.answer()
        here = chat_of(callback)
        if here is None:
            return
        message, chat_id, lang = here
        proposal = pending.proposal(chat_id, at=message.message_id)
        if proposal is None or proposal.fast is None:
            await stale(message, lang)
            return
        await analyze(
            message,
            chat_id,
            note=proposal.note,
            file_ids=proposal.file_ids,
            source=proposal.source,
            pending=pending,
            fast=False,
            # Исток записи переезжает вместе с материалом (T205): аудитор
            # сказал те же слова, и кадр к тому, что из них получится, он
            # дошлёт ответом на них же. Потеряй мы его здесь — досылка молча
            # перестала бы работать ровно у тех записей, которые переразобраны
            # моделью, то есть у самых спорных.
            origin=proposal.origin,
        )

    @router.callback_query(F.data.startswith(PICK_PREFIX))
    async def on_pick(callback: CallbackQuery) -> None:
        await callback.answer()
        here = chat_of(callback)
        if here is None:
            return
        message, chat_id, lang = here
        raw = (callback.data or "").removeprefix(PICK_PREFIX)
        proposal = pending.proposal(chat_id, at=message.message_id)
        if proposal is None or not raw.isdigit() or int(raw) >= len(proposal.candidates):
            await stale(message, lang)
            return
        index = int(raw)
        candidate = proposal.candidates[index]
        неизвестна = not candidate.zone or candidate.zone == UNKNOWN_ZONE
        # Зона модели вне списка методики — это тот же случай, что и её
        # отсутствие: записать такую пару с T271 нельзя вовсе, движок её
        # отвергает. Спросить до фиксации лучше, чем отказать после: аудитор на
        # точке видит кнопки допустимых зон, а не сообщение о неудаче.
        чужая = not неизвестна and candidate.zone not in allowed_zones(
            candidate.code, chat_id=chat_id
        )
        if неизвестна or чужая:
            await _ask_zone(
                message,
                chat_id,
                replace(proposal, picked=index),
                pending,
                ZONE_FOR_PICK_PREFIX,
                lang,
                item_code=candidate.code,
            )
            return
        if await _save(
            message,
            chat_id,
            code=candidate.code,
            level=candidate.level,
            zone=candidate.zone,
            text=candidate.wording,
            file_ids=proposal.file_ids,
            source=proposal.source,
            lang=lang,
            # Текстом записи стала формулировка МОДЕЛИ, а слова аудитора — те,
            # что он сказал об этом кадре (T183). Разница между ними и есть то,
            # по чему потом разбирают промах.
            words=proposal.note,
            # Зона — догадка ровно тогда, когда её никто не называл, а модель
            # вернула ту самую, которую ей подсказали из памяти (T156). Своя
            # зона модели памятью не является: это её ответ, а не прошлая
            # запись, и оговорка о нём соврала бы.
            zone_spoken=proposal.zone_spoken,
            # Зона из словаря — только если модель вернула ЕЁ ЖЕ. Своя зона
            # модели словарём не является: это её ответ, и оговорка о карте
            # кадров соврала бы.
            zone_from_cues=(proposal.zone_from_cues and candidate.zone == proposal.zone_hint),
            # Зона записи — ответ МОДЕЛИ, и источником из трёх он становится
            # только тогда, когда совпал с выведенным до неё. Разошлись —
            # накопитель честно скажет «не вывелась»: подписать ответ модели
            # словами аудитора значило бы соврать там, где сигнал и собирают.
            zone_source=(proposal.zone_source if candidate.zone == proposal.zone_hint else ""),
            suggested=_model_suggestion(proposal),
            # Нажатие под правкой означает «поправить на этот пункт», а не
            # «завести ещё один»: адресат назван ответом аудитора и с тех пор
            # не меняется, сколько бы кадров он ни прислал между показом
            # кандидатов и кнопкой.
            correcting=proposal.correcting,
            origin=proposal.origin,
        ):
            pending.take_proposal(chat_id, at=message.message_id)

    @router.callback_query(F.data.startswith(ZONE_FOR_PICK_PREFIX))
    async def on_zone_for_pick(callback: CallbackQuery) -> None:
        await callback.answer()
        here = chat_of(callback)
        if here is None:
            return
        message, chat_id, lang = here
        zone = (callback.data or "").removeprefix(ZONE_FOR_PICK_PREFIX)
        proposal = pending.proposal(chat_id, at=message.message_id)
        if proposal is None or proposal.picked is None:
            await stale(message, lang)
            return
        candidate = proposal.candidates[proposal.picked]
        if await _save(
            message,
            chat_id,
            code=candidate.code,
            level=candidate.level,
            zone=zone,
            text=candidate.wording,
            file_ids=proposal.file_ids,
            source=proposal.source,
            lang=lang,
            words=proposal.note,
            # Зону назвал человек кнопкой: оговорка о том, откуда она взялась,
            # была бы неправдой, а зона пункта не имеет права её перебить.
            zone_spoken=True,
            zone_source=domain.ZONE_SOURCE_BUTTONS,
            # В предложении остаётся ответ модели — `UNKNOWN`. Подставить сюда
            # выбранную зону значило бы спрятать её отказ и превратить промах
            # в попадание.
            suggested=_model_suggestion(proposal),
            correcting=proposal.correcting,
            origin=proposal.origin,
        ):
            pending.take_proposal(chat_id, at=message.message_id)

    @router.callback_query(F.data.startswith(ZONE_FOR_MANUAL_PREFIX))
    async def on_zone_for_manual(callback: CallbackQuery) -> None:
        await callback.answer()
        here = chat_of(callback)
        if here is None:
            return
        message, chat_id, lang = here
        zone = (callback.data or "").removeprefix(ZONE_FOR_MANUAL_PREFIX)
        proposal = pending.proposal(chat_id, at=message.message_id)
        if proposal is None:
            await stale(message, lang)
            return
        # Зона НЕ запоминается для следующего кадра (T264, #218): память о
        # прошлой записи снята как источник — именно ею пункт про печь и уехал
        # в холодный цех, пока аудитор об этом не знал.
        await _open_manual(
            message,
            chat_id,
            replace(proposal, zone_hint=zone, zone_source=domain.ZONE_SOURCE_BUTTONS),
            pending,
            lang,
        )

    @router.callback_query(F.data == MANUAL_CALLBACK)
    async def on_manual(callback: CallbackQuery) -> None:
        await callback.answer()
        here = chat_of(callback)
        if here is None:
            return
        message, chat_id, lang = here
        proposal = pending.proposal(chat_id, at=message.message_id)
        if proposal is None:
            await stale(message, lang)
            return
        await _open_manual(message, chat_id, proposal, pending, lang)

    @router.callback_query(F.data.startswith(MANUAL_PAGE_PREFIX))
    async def on_manual_page(callback: CallbackQuery) -> None:
        await callback.answer()
        here = chat_of(callback)
        if here is None:
            return
        message, chat_id, lang = here
        raw = (callback.data or "").removeprefix(MANUAL_PAGE_PREFIX)
        proposal = pending.proposal(chat_id, at=message.message_id)
        if proposal is None or not raw.isdigit():
            await stale(message, lang)
            return
        await _show_manual_page(message, chat_id, proposal, pending, int(raw), lang)

    async def _save_manual(
        message: Message, chat_id: int, proposal: Proposal, index: int, level: str, lang: str
    ) -> None:
        """Фиксация ручного выбора.

        Формулировкой становится комментарий аудитора, если он был: это его
        собственные слова, а лучшего источника без модели нет. Слов не было —
        запись ложится БЕЗ формулировки (T287, решение D128), и это не потеря
        данных: связь с методикой держится кодом пункта, а коды не переводятся
        и не правятся.

        Раньше на это место подставлялся вопрос пункта целиком. Вопросы
        методики сформулированы как утверждение нормы («… делается согласно
        стандарту» — дословно не приводим, методика заказчика в публичный
        репозиторий не цитируется), поэтому партнёр читал подтверждение нормы
        ровно там, где зафиксировано отклонение, — и читал как слова
        аудитора. Правила фиксации требуют обратного: в поле
        формулировки идёт факт и ничего кроме факта
        (`docs/03-recording-rules.md`).

        Своей ссылки на пункт бот не пишет намеренно. Как назвать запись без
        слов, решает место печати: отчёт строки записи не печатает, письмо
        зовёт пункт пунктом (`пункт стандарта «…»`, блок `engine-fix`, T248).
        Собери бот ту же ссылку сам — в продукте оказалось бы два выражения
        одного, и они разъехались бы на первой же правке.

        Аудитор об этом не в неведении: пункт назван в подтверждении словами, а
        кнопка «Формулировка» под ним (T056) стоит там же, где стояла.
        """
        item = proposal.manual[index]
        if not proposal.zone_hint:
            # Пункт выбран, а зона не выведена: поиск словом зоны не требует
            # (T267), и спросить её надо здесь — кнопками ТОЛЬКО из зон,
            # допустимых методикой для этого пункта (T266). Раньше зона
            # спрашивалась ДО перечня и всеми зонами разом, и нажатие на чужую
            # кончалось отказом движка у аудитора на точке.
            await _ask_zone(
                message,
                chat_id,
                replace(proposal, picked=index, picked_level=level),
                pending,
                ZONE_FOR_ITEM_PREFIX,
                lang,
                item_code=item.code,
            )
            return
        if await _save(
            message,
            chat_id,
            code=item.code,
            level=level,
            zone=proposal.zone_hint,
            text=proposal.note.strip(),
            file_ids=proposal.file_ids,
            source=proposal.source,
            lang=lang,
            # Модель тут промолчала, и слова аудитора становятся ценнее, а не
            # наоборот: по ним видно, чего в списке слов не хватило.
            words=proposal.note,
            # Человек выбрал в перечне пункт, а не зону: откуда зона взялась,
            # сказать всё равно надо (T156). Назвал её сам — кнопкой или
            # словами — `zone_spoken` уже стоит.
            zone_spoken=proposal.zone_spoken,
            zone_from_cues=proposal.zone_from_cues,
            zone_source=proposal.zone_source,
            # Предложения здесь нет и быть не может: ручной перечень
            # показывается ровно тогда, когда модель не ответила ничего —
            # недоступна или вернула пустой список. Записать предложением
            # выбранный человеком пункт значило бы утопить настоящие промахи в
            # выборке для управляющей компании: ручных записей на порядок
            # больше, и все они выглядели бы попаданием модели (D077).
            suggested=None,
            correcting=proposal.correcting,
            origin=proposal.origin,
        ):
            pending.take_proposal(chat_id, at=message.message_id)

    @router.callback_query(F.data.startswith(ZONE_FOR_ITEM_PREFIX))
    async def on_zone_for_item(callback: CallbackQuery) -> None:
        """Зона, названная кнопкой для уже выбранного пункта (T266)."""
        await callback.answer()
        here = chat_of(callback)
        if here is None:
            return
        message, chat_id, lang = here
        zone = (callback.data or "").removeprefix(ZONE_FOR_ITEM_PREFIX)
        proposal = pending.proposal(chat_id, at=message.message_id)
        if proposal is None or proposal.picked is None or not proposal.picked_level:
            await stale(message, lang)
            return
        await _save_manual(
            message,
            chat_id,
            # Зону назвал человек кнопкой: `zone_spoken` стоит по той же
            # причине, что и на пути кандидата модели.
            replace(proposal, zone_hint=zone, zone_source=domain.ZONE_SOURCE_BUTTONS),
            proposal.picked,
            proposal.picked_level,
            lang,
        )

    @router.callback_query(F.data == CUES_ZONE_CALLBACK)
    async def on_cues_zone(callback: CallbackQuery) -> None:
        """«Зона объекта» под расхождением: разбор продолжается с зоной словаря."""
        await callback.answer()
        here = chat_of(callback)
        if here is None:
            return
        message, chat_id, lang = here
        proposal = pending.proposal(chat_id, at=message.message_id)
        if proposal is None or not proposal.cues_zone:
            await stale(message, lang)
            return
        _, report_lang = chat_langs(chat_id)
        await _analyze_resolved(
            message,
            chat_id,
            replace(
                proposal,
                zone_hint=proposal.cues_zone,
                # Зону назвал не аудитор, а карта кадров: `zone_spoken` здесь
                # был бы неправдой ровно там, где человек сказал другое.
                zone_source=domain.ZONE_SOURCE_DICTIONARY,
                cues_zone="",
            ),
            pending,
            lang,
            report_lang,
            fast=True,
        )

    @router.callback_query(F.data == CUES_ITEM_CALLBACK)
    async def on_cues_item(callback: CallbackQuery) -> None:
        """«Другой пункт» под расхождением: поиск пункта словом (T267)."""
        await callback.answer()
        here = chat_of(callback)
        if here is None:
            return
        message, chat_id, lang = here
        proposal = pending.proposal(chat_id, at=message.message_id)
        if proposal is None:
            await stale(message, lang)
            return
        # Зона остаётся НАЗВАННОЙ аудитором: он выбрал «другой пункт», то есть
        # подтвердил своё место и отказался от объекта, а не наоборот.
        await _open_manual(message, chat_id, replace(proposal, cues_zone=""), pending, lang)

    @router.callback_query(F.data.startswith(MANUAL_PICK_PREFIX))
    async def on_manual_pick(callback: CallbackQuery) -> None:
        await callback.answer()
        here = chat_of(callback)
        if here is None:
            return
        message, chat_id, lang = here
        raw = (callback.data or "").removeprefix(MANUAL_PICK_PREFIX)
        proposal = pending.proposal(chat_id, at=message.message_id)
        if proposal is None or not raw.isdigit() or int(raw) >= len(proposal.manual):
            await stale(message, lang)
            return
        item = proposal.manual[int(raw)]
        if len(item.levels) == 1:
            await _save_manual(message, chat_id, proposal, int(raw), item.levels[0], lang)
            return
        await _hand(
            message,
            chat_id,
            pending,
            proposal,
            t("record.ask_level", lang, code=item.code),
            levels_keyboard(f"{MANUAL_LEVEL_PREFIX}{raw}:", item.levels),
        )

    @router.callback_query(F.data.startswith(MANUAL_LEVEL_PREFIX))
    async def on_manual_level(callback: CallbackQuery) -> None:
        await callback.answer()
        here = chat_of(callback)
        if here is None:
            return
        message, chat_id, lang = here
        raw, _, level = (callback.data or "").removeprefix(MANUAL_LEVEL_PREFIX).partition(":")
        proposal = pending.proposal(chat_id, at=message.message_id)
        if proposal is None or not raw.isdigit() or int(raw) >= len(proposal.manual):
            await stale(message, lang)
            return
        await _save_manual(message, chat_id, proposal, int(raw), level, lang)

    @router.callback_query(F.data == SKIP_CALLBACK)
    async def on_skip(callback: CallbackQuery) -> None:
        await callback.answer()
        here = chat_of(callback)
        if here is None:
            return
        message, chat_id, lang = here
        proposal = pending.take_proposal(chat_id, at=message.message_id)
        journal.note(chat_id, "skipped", slot=None if proposal is None else proposal.slot)
        if proposal is not None:
            # «Не записывать» — законный выбор аудитора, но не повод потерять
            # формулировку: в конце проверки у кадра будет названа причина, а
            # управляющая компания увидит, чего не хватило карте (T269, #219).
            await asyncio.to_thread(
                _lost,
                chat_id,
                file_ids=proposal.file_ids,
                note=proposal.note,
                zone=proposal.zone_hint,
                zone_source=proposal.zone_source,
                outcome=sidecar.OUTCOME_ABANDONED,
            )
        await message.answer(t("record.skipped", lang))

    return router


#: Что делать с кадром, присланным ответом на своё же сообщение (T205).
FrameHandler = Callable[[Message, int, int, str, str], Awaitable[None]]


def make_frame_handler() -> FrameHandler:
    """Кадр ответом на СВОИ слова — в ту самую запись (задача T205, решение D081).

    Аудитор наговорил голосовое, бот собрал по нему запись, а кадр к ней
    прислал следом — ответом на своё же голосовое. Кадр обязан попасть в ту же
    запись, а не завести новую очередь ожидания с вопросом «Разобрать?»: одно
    нарушение, о котором человек сказал один раз, в отчёте партнёру должно
    остаться одной строкой.

    Разбора здесь нет и быть не должно. Пункт уже найден по словам аудитора,
    кадр их не уточняет и не оспаривает — он их ПОДТВЕРЖДАЕТ, а фотофиксация
    обязательна всегда (D078). Отправить кадр в модель значило бы заплатить за
    вопрос, на который человек уже ответил.

    Чем этот путь отличается от правки ответом (`routers/correct.py`): там
    аудитор отвечает на сообщение БОТА и приносит слова — система ищет пункт
    заново. Здесь он отвечает на СВОЁ сообщение и приносит кадр — пункт не
    трогается вовсе. Две карты в заметках именно поэтому разные (`sidecar`).
    """

    async def attach(message: Message, chat_id: int, n: int, file_id: str, lang: str) -> None:
        inspection = read_inspection(chat_id)
        if inspection is None:
            await message.answer(t("material.no_inspection", lang))
            return
        if sealed.is_sealed(chat_id):
            # Сданная проверка не правится ничем (T201, D080), и кадр в её
            # запись — тоже правка: он уезжает в отчёт партнёру.
            await sealed.refuse(message, lang)
            return
        if inspection.finding(n) is None:
            # Запись сняли, а сообщение о ней осталось в переписке навсегда.
            # Завести по такому ответу новую запись нельзя: кадр без слов
            # человека — это не находка, а вопрос «Разобрать?», на который
            # аудитор в этот момент не отвечал.
            await message.answer(t("edit.gone", lang, n=n))
            return
        # Кадр запоминается ДО прикрепления и независимо от его исхода: список
        # присланного нужен целиком (T068), и не прикрепившийся кадр обязан
        # найтись при завершении, а не исчезнуть.
        sidecar.remember_frames(
            chat_id, [sidecar.SeenFrame(message_id=message.message_id, file_id=file_id)]
        )
        frame_copies.received(message.bot, chat_id, [(message.message_id, file_id)])
        try:
            await asyncio.to_thread(domain.attach_photo, chat_id, n, file_id)
        except DomainError:
            logger.exception("кадр %s не прикрепился к записи #%s ответом", file_id, n)
            await message.answer(t("record.frame_failed", lang, n=n))
            return
        after = read_inspection(chat_id)
        finding = None if after is None else after.finding(n)
        # Число кадров читается ИЗ ПРОВЕРКИ, а не считается прибавлением: если
        # движок кадр не принял, а исключения не бросил, показанное число было
        # бы выдумкой ровно там, где аудитор проверяет фотофиксацию.
        count = 0 if finding is None else len(finding.photos)
        await message.answer(t("record.frame_attached", lang, n=n, count=count))

    return attach


def make_material_handler(
    pending: PendingStore,
) -> Callable[[Message, Material, str], Awaitable[None]]:
    """Готовый материал — разобрать по словам аудитора (T055).

    Первым делом снимается вопрос «Разобрать?», если он висел на этих кадрах:
    комментарий сильнее догадки по картинке (D046), и предлагать разбор кадра,
    по которому уже идёт разбор по словам, нельзя.

    Сообщение, которым материал собрался, запоминается как исток записи (T205):
    именно ответом на него — на своё же голосовое, на свою же подпись — аудитор
    досылает к записи кадр. Берётся оно здесь, а не глубже: дальше по дороге
    `message` бывает уже сообщением БОТА (нажатие кнопки), и «сообщение
    аудитора» превратилось бы в неправду молча.
    """

    async def handle(message: Message, material: Material, lang: str) -> None:
        chat_id = material.chat_id
        offer = pending.take_offer_for(chat_id, material.photo_file_ids)
        if offer is not None:
            await _drop_question(message, chat_id, offer)

        note = (material.comment.text or "").strip()
        if material.comment.voice_file_id is not None:
            heard = await hear_voice(message, material.comment.voice_file_id, lang)
            if heard is None:
                return
            note = heard.strip()

        await analyze(
            message,
            chat_id,
            note=note,
            file_ids=material.photo_file_ids,
            source=domain.SOURCE_COMMENT,
            pending=pending,
            origin=message.message_id,
        )

    return handle
