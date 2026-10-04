"""Начало проверки и продолжение незавершённой (T050, T051, T052, T063).

Мастер спрашивает ровно три вещи: название пиццерии текстом (решение D051 —
справочника точек в MVP нет), вид проверки и язык отчёта. Остальное бот знает
сам: проверяющего берёт по Telegram ID, дату ставит сегодняшнюю (решение D032,
задача T063). Ни одного шага, который аудитор заполняет руками впустую.

Незавершённая проверка не затирается молча (задача T052): движок `init`
переписывает состояние целиком и без вопросов, поэтому спросить обязан бот —
показать, чья проверка и от какого числа, и дать выбрать.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict

from aiogram import F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from src import domain
from src.db.directory import upsert_unit
from src.db.errors import DbError
from src.domain.bot_checklists import BotChecklist, available
from src.domain.config import check_environment
from src.domain.errors import DomainError
from src.domain.geo import COUNTRIES
from src.domain.unit_name import UnitName, canonical_unit

from .. import sealed, sidecar, stops
from ..auditor import auditor_name, auditor_name_was_shortened
from ..config import BotSettings
from ..inspection import read_inspection
from ..keyboards import (
    CHECKLIST_PREFIX,
    KIND_PREFIX,
    KIND_TITLES,
    LANG_LABELS,
    LANG_PREFIX,
    NEW_INSPECTION_CALLBACK,
    RESUME_CONTINUE_CALLBACK,
    RESUME_NEW_CALLBACK,
    SEALED_DROP_CALLBACK,
    UNIT_NEW_PREFIX,
    UNIT_NEW_YES,
    checklist_keyboard,
    kind_keyboard,
    kind_title,
    lang_keyboard,
    new_inspection_keyboard,
    resume_keyboard,
    sealed_keyboard,
    unit_new_keyboard,
)
from ..lang import chat_ui_lang, person_ui_lang
from ..material import MaterialStore
from ..pending import PendingStore
from ..states import StartFlow
from ..texts import t, ui_lang_or_default, with_photo_rule
from ..unit_pick import match_unit, may_add_units

logger = logging.getLogger(__name__)

#: Сколько знаков в названии точки бот принимает.
#:
#: Число замерено, а не выбрано на вкус. Имя файла отчёта движок собирает как
#: «Аудит <точка> - <аудитор> - <дата>.pdf»; кириллица в UTF-8 — два байта на
#: знак, а предел имени файла на ext4 (площадка продукта, D053) — 255 байт.
#: С аудитором в 40 знаков на название остаётся около шестидесяти. Проверено
#: фактическим прогоном: на 300 знаках сборка отчёта падает с «File name too
#: long», и узнаёт об этом аудитор в конце проверки, когда переснимать поздно.
UNIT_NAME_LIMIT = 60

#: Тот же предел, но БАЙТАМИ (T128, переоткрытая часть, issue #103): в знаках
#: он не ловит тяжёлые символы — 60 эмодзи это те же 60 знаков (в предел выше
#: укладываются), но уже 240 байт, то есть одно название съедает больше, чем
#: весь бюджет имени файла. Число — часть общего бюджета: постоянная часть
#: формулы имени файла (слово, два разделителя, дата, «.pdf») занимает 31 байт
#: (замерено, см. комментарий у `AUDITOR_NAME_BYTE_LIMIT` в `../auditor.py`),
#: остаётся 224 байта на название точки и имя аудитора вместе. Точке — 120
#: байт (ровно 60 кириллических знаков — старым живым названиям запрет не
#: мешает, старое поведение не меняется), аудитору — 100.
UNIT_NAME_BYTE_LIMIT = 120


async def _offer_resume(message: Message, inspection: domain.Inspection, lang: str) -> None:
    """Показать оставшуюся в чате проверку и дать выбор, какой у неё есть.

    Развилок две, и разница между ними не косметическая (T153, T201). Проверке
    в работе правда, что она незавершённая и что новая её сотрёт. Проверке, по
    которой отчёт уже собран и отдан, — неправда и то и другое.

    У сданной проверки выбор другой и меньше: дописать в неё нельзя вовсе
    (решение владельца D080, `src/bot/sealed.py`), поэтому кнопки «Продолжить»
    здесь нет. Остаются двери, названные владельцем: начать новую или убрать
    сданную из чата. До T201 бот сам предлагал «Продолжить её — можно дописать
    и собрать отчёт заново» — из-за этого тот же обход и вставал в историю
    точки второй строкой.

    Признака «завершена» у движка нет, и бот его не выдумывает: он опирается на
    то, что сделал сам, — отдал ли он по этой проверке отчёт (`sidecar`).
    """
    сдана = sealed.is_sealed(message.chat.id)
    await message.answer(
        t(
            "start.resume_handed_over" if сдана else "start.resume_found",
            lang,
            unit=inspection.unit,
            date=inspection.date,
            auditor=inspection.auditor or "—",
            findings=len(inspection.findings),
        ),
        reply_markup=sealed_keyboard(lang) if сдана else resume_keyboard(lang),
    )


async def _unit_chosen(message: Message, state: FSMContext, lang: str, unit: str) -> None:
    """Пиццерия определена — дальше вид проверки."""
    await state.update_data(unit=unit, unit_new=None, unit_typed=None)
    await state.set_state(StartFlow.waiting_kind)
    await message.answer(t("start.ask_kind", lang), reply_markup=kind_keyboard(lang))


def _where(имя: UnitName, lang: str) -> str:
    """Страна точки словом для вопроса «Новая пиццерия?»; незнакомая — пусто."""
    if имя.country is None:
        return ""
    names = COUNTRIES.get(имя.country, {})
    return f" ({names.get(lang) or names.get('en') or имя.country})"


async def _ask_unit(message: Message, state: FSMContext, lang: str) -> None:
    await state.set_state(StartFlow.waiting_unit)
    await message.answer(t("start.ask_unit", lang))


def _open_checklists(space: str) -> list[BotChecklist] | None:
    """Открытые в боте чек-листы пространства аудитора — или `None`, если их не прочитать."""
    try:
        return available(check_environment(), tenant=space)
    except (DomainError, OSError, ValueError):
        logger.exception("список чек-листов для бота не прочитался")
        return None


async def _ask_checklist(message: Message, state: FSMContext, lang: str, space: str) -> None:
    """Первый шаг мастера (волна 3): по какому чек-листу проверка.

    Открыт один — не спрашиваем, как до волны 3. Несколько — кнопки с
    названиями на языке интерфейса. Ни одного — прямо говорим, что начать не
    по чему и кто это чинит, и мастер дальше не идёт.
    """
    открыты = _open_checklists(space)
    if открыты is None:
        await state.clear()
        await stops.refuse(message, lang, step="start.checklist", key="start.failed")
        return
    if not открыты:
        await state.clear()
        await stops.refuse(message, lang, step="start.checklist", key="start.no_checklists")
        return
    if len(открыты) == 1:
        await state.update_data(checklist=открыты[0].code)
        await _ask_unit(message, state, lang)
        return
    await state.set_state(StartFlow.waiting_checklist)
    await message.answer(
        t("start.ask_checklist", lang),
        reply_markup=checklist_keyboard([(c.code, c.name(lang)) for c in открыты]),
    )


def build_start_router(
    settings: BotSettings,
    pending: PendingStore | None = None,
    store: MaterialStore | None = None,
) -> Router:
    """Роутер мастера начала проверки.

    `settings` нужен ради карты имён (T063). `pending` — чтобы кнопки прошлой
    проверки не выстрелили в новую: предложение, показанное пять минут назад,
    зафиксировало бы запись уже в другой пиццерии. `store` — ровно по той же
    причине и о том же (T249, issue #202): очередь ожидания живёт в памяти
    процесса, и кадр новой проверки забирал придержанные слова старой.

    Оба необязательны: юнит-тесты мастера собирают роутер в одиночку, и
    требовать от них хранилища, которых мастер не наполняет, значило бы
    заставить их знать про разбор материала.
    """
    router = Router(name="start")

    @router.message(Command("start"))
    async def on_start(message: Message, state: FSMContext) -> None:
        """`/start` обязан работать всегда — это единственный выход из тупика.

        Испорченное состояние роняло здесь всё: аудитор не мог ни продолжить
        проверку, ни начать новую, и бот на любое его сообщение отвечал
        молчанием (T126). Поэтому нечитаемое состояние тут не отказ, а
        отдельный ответ: сказать, что файл повреждён, и дать начать заново.
        Молчаливой перезаписи при этом нет — новую заводит человек кнопкой.
        """
        lang = chat_ui_lang(message.chat.id)
        await state.clear()
        try:
            inspection = read_inspection(message.chat.id)
        except DomainError:
            logger.exception("состояние чата %s не читается", message.chat.id)
            await stops.refuse(
                message,
                lang,
                step="start",
                key="start.state_broken",
                reply_markup=new_inspection_keyboard(lang),
            )
            return
        if inspection is not None:
            await _offer_resume(message, inspection, lang)
            return
        await message.answer(t("start.greeting", lang), reply_markup=new_inspection_keyboard(lang))

    @router.callback_query(F.data == NEW_INSPECTION_CALLBACK)
    async def on_new(callback: CallbackQuery, state: FSMContext, space: str) -> None:
        await callback.answer()
        message = callback.message
        if not isinstance(message, Message):
            return
        lang = chat_ui_lang(message.chat.id)
        try:
            inspection = read_inspection(message.chat.id)
        except DomainError:
            # Про повреждение аудитор уже прочитал на `/start` и нажал «Новая»
            # осознанно. Второй раз пугать его нечем, а тупик здесь означал бы,
            # что выхода нет и после нажатия единственной предложенной кнопки.
            logger.exception("состояние чата %s не читается", message.chat.id)
            await _ask_checklist(message, state, lang, space)
            return
        if inspection is not None:
            await _offer_resume(message, inspection, lang)
            return
        await _ask_checklist(message, state, lang, space)

    @router.callback_query(F.data == RESUME_CONTINUE_CALLBACK)
    async def on_resume_continue(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        message = callback.message
        if not isinstance(message, Message):
            return
        await state.clear()
        lang = chat_ui_lang(message.chat.id)
        inspection = read_inspection(message.chat.id)
        if inspection is None:
            await stops.refuse(message, lang, step="start.resume", key="start.resume_gone")
            return
        if sealed.is_sealed(message.chat.id):
            # Кнопка из вчерашней переписки живёт вечно, а сдать проверку
            # аудитор мог уже после того, как её увидел (T201).
            await sealed.refuse(message, lang)
            return
        # Правило фотофиксации повторяется и здесь (T160, D078): к прерванной
        # проверке аудитор возвращается через день и другой сессией, и первого
        # сообщения — того, где правило прозвучало заранее, — он мог не читать.
        await message.answer(
            with_photo_rule(
                t(
                    "start.resumed",
                    lang,
                    unit=inspection.unit,
                    date=inspection.date,
                    findings=len(inspection.findings),
                ),
                lang,
            )
        )

    @router.callback_query(F.data == RESUME_NEW_CALLBACK)
    async def on_resume_new(callback: CallbackQuery, state: FSMContext, space: str) -> None:
        """«Начать новую» — только вход в мастер.

        Старая проверка на диске остаётся до последнего шага: аудитор ещё может
        бросить мастер на полпути, и потерять из-за этого зафиксированное было бы
        ровно тем молчаливым затиранием, от которого защищает задача T052.
        """
        await callback.answer()
        message = callback.message
        if not isinstance(message, Message):
            return
        await _ask_checklist(message, state, chat_ui_lang(message.chat.id), space)

    @router.callback_query(F.data == SEALED_DROP_CALLBACK)
    async def on_sealed_drop(callback: CallbackQuery, state: FSMContext) -> None:
        """«Убрать из чата»: сданная проверка мешает начать следующую (T201, D080).

        Убирается копия в чате — и только она. Отданный отчёт и строка проверки
        в истории точки остаются: запечатанное не правится и не удаляется, а
        доступа к истории у бота и нет. Сказать об этом обязан прямо: молчание
        здесь читается как «удалено всё».

        Проверка перед удалением — та же, что и на всех остальных входах: не
        сданную проверку эта кнопка удалить не может, даже если аудитор дошёл до
        неё по старой переписке. Потерять незавершённый обход одним нажатием —
        ровно то молчаливое затирание, от которого защищает T052.
        """
        await callback.answer()
        message = callback.message
        if not isinstance(message, Message):
            return
        chat_id = message.chat.id
        lang = chat_ui_lang(chat_id)
        await state.clear()
        if not sealed.is_sealed(chat_id):
            await stops.refuse(message, lang, step="start.drop", key="sealed.drop_gone")
            return
        try:
            убрана = await asyncio.to_thread(domain.drop_inspection, chat_id)
        except DomainError:
            logger.exception("проверка чата %s не убралась", chat_id)
            await stops.refuse(message, lang, step="start.drop", key="start.failed")
            return
        if not убрана:
            await stops.refuse(message, lang, step="start.drop", key="sealed.drop_gone")
            return
        # Заметки уходят вместе с проверкой: список кадров, последняя зона и
        # карта сообщений относятся к ней, а не к чату.
        sidecar.reset(chat_id)
        if pending is not None:
            pending.forget(chat_id)
        if store is not None:
            # Проверки в чате больше нет вовсе — ждать её кадрам и словам не
            # для чего (T249).
            store.forget(chat_id)
        await message.answer(t("sealed.dropped", lang), reply_markup=new_inspection_keyboard(lang))

    @router.message(StateFilter(StartFlow.waiting_unit), F.text, ~F.text.startswith("/"))
    async def on_unit(message: Message, state: FSMContext, space: str) -> None:
        lang = chat_ui_lang(message.chat.id)
        unit = (message.text or "").strip()
        if not unit:
            await stops.refuse(message, lang, step="start.unit", key="start.unit_empty")
            return
        if len(unit) > UNIT_NAME_LIMIT:
            # Отказ здесь, а не отказом сборки отчёта в конце проверки: там
            # аудитор уже уехал с точки, и переименовать пиццерию ему нечем.
            await stops.refuse(
                message, lang, step="start.unit", key="start.unit_too_long", limit=UNIT_NAME_LIMIT
            )
            return
        if len(unit.encode("utf-8")) > UNIT_NAME_BYTE_LIMIT:
            # Предел в знаках это не ловит: 60 эмодзи проходят его же знаками,
            # а по байтам уже почти весь бюджет имени файла разом (T128).
            await stops.refuse(message, lang, step="start.unit", key="start.unit_too_long_bytes")
            return
        # Имя точки — город по-английски и номер, как бы его ни написали (D233).
        имя = canonical_unit(unit)
        if имя is None:
            await stops.refuse(
                message, lang, step="start.unit", key="start.unit_need_number", typed=unit
            )
            return
        if len(имя.name) > UNIT_NAME_LIMIT:
            # Латиница бывает длиннее написанного («Щ» → «shch»): предел имени
            # файла отчёта сверяется с тем, что ляжет в шапку, а не с вводом.
            await stops.refuse(
                message, lang, step="start.unit", key="start.unit_too_long", limit=UNIT_NAME_LIMIT
            )
            return
        сверка = await asyncio.to_thread(match_unit, имя.name, tenant=space)
        if сверка.name is not None or not сверка.checked:
            # Совпало со справочником — или справочник недоступен, и тогда не
            # повод держать аудитора на точке: имя уже каноническое.
            await _unit_chosen(message, state, lang, сверка.name or имя.name)
            return
        if not may_add_units(space):
            await stops.refuse(
                message, lang, step="start.unit", key="start.unit_new_partner", name=имя.name
            )
            return
        await state.update_data(unit_new=asdict(имя), unit_typed=unit)
        await message.answer(
            t("start.unit_new_ask", lang, name=имя.name, where=_where(имя, lang)),
            reply_markup=unit_new_keyboard(lang),
        )

    @router.callback_query(StateFilter(StartFlow.waiting_unit), F.data.startswith(UNIT_NEW_PREFIX))
    async def on_unit_new(callback: CallbackQuery, state: FSMContext, space: str) -> None:
        """«Новая пиццерия?» — да заводит её в справочник страны, нет — ввести заново (D233)."""
        await callback.answer()
        message = callback.message
        if not isinstance(message, Message):
            return
        lang = chat_ui_lang(message.chat.id)
        данные = await state.get_data()
        сырое = данные.get("unit_new")
        if not isinstance(сырое, dict):
            # Кнопка из старого сообщения: к какой точке она относилась, уже не узнать.
            await stops.refuse(message, lang, step="start.unit_new", key="start.unit_pick_gone")
            return
        if (callback.data or "").removeprefix(UNIT_NEW_PREFIX) != UNIT_NEW_YES:
            await state.update_data(unit_new=None, unit_typed=None)
            await _ask_unit(message, state, lang)
            return
        if not may_add_units(space):
            await stops.refuse(
                message,
                lang,
                step="start.unit_new",
                key="start.unit_new_partner",
                name=сырое["name"],
            )
            return
        имя = UnitName(**сырое)
        написано = str(данные.get("unit_typed") or "")
        синонимы = (написано,) if написано and написано != имя.name else ()
        try:
            await asyncio.to_thread(
                upsert_unit,
                имя.name,
                aliases=синонимы,
                country=имя.country,
                city=имя.city,
                tenant=space,
            )
        except DbError as exc:
            # Точка всё равно заведётся по имени при сливе проверки; страну и
            # город тогда допишет администратор. Держать аудитора незачем.
            logger.warning("новая пиццерия %s не записана в справочник: %s", имя.name, exc)
        else:
            await message.answer(
                t("start.unit_added", lang, name=имя.name, where=_where(имя, lang))
            )
        await _unit_chosen(message, state, lang, имя.name)

    @router.message(StateFilter(StartFlow.waiting_unit), F.text, F.text.startswith("/"))
    async def on_unit_command(message: Message) -> None:
        """Команда вместо названия точки (T250, issue #203).

        Роутер `start` стоит в диспетчере первым, и до этой задачи команда,
        набранная или выбранная в меню на шаге названия, до своего обработчика
        не доходила — она становилась названием пиццерии и уезжала в шапку
        отчёта и в имя файла. Поводов попасть сюда прибавилось с пунктом
        «Установка MCP» (T209): это разовая настройка, её нажимают в
        произвольный момент, в том числе не дочитав вопрос мастера.

        Команда выполняется, а мастер остаётся ждать название. Порядок роутеров
        при этом не трогается — он в этом блоке несущий, — потому что сообщение
        пропускается дальше отсюда (`SkipHandler`). Тем же приёмом и по той же
        причине живёт вопрос о новой формулировке (`routers/edit.py`).

        `/start` сюда не попадает: он зарегистрирован в этом же роутере выше и
        обязан работать всегда — это единственный выход из тупика.

        Строка в чат — не вежливость. Своего ответа у незнакомой команды нет
        вовсе, а у знакомой он придёт следом и вытеснит вопрос мастера с
        экрана: аудитор прочитает ответ команды и решит, что название принято.
        """
        await stops.refuse(
            message, chat_ui_lang(message.chat.id), step="start.unit", key="start.unit_command"
        )
        raise SkipHandler

    @router.message(StateFilter(StartFlow.waiting_unit), ~F.text)
    async def on_unit_not_text(message: Message) -> None:
        """Кадр или голос вместо названия: сказать, чего ждём, а не молчать.

        Фильтр `~F.text` обязателен, и это не украшение подписи (T250):
        `SkipHandler` продолжает поиск с ОСТАВШИХСЯ обработчиков того же
        роутера, а не со следующего. Будь этот перехватчиком всего подряд, он
        поймал бы пропущенную команду здесь же — и она никуда бы не уехала, а
        аудитор получил бы «жду название» вместо ответа команды.
        """
        await stops.refuse(
            message, chat_ui_lang(message.chat.id), step="start.unit", key="start.unit_expected"
        )

    @router.callback_query(
        StateFilter(StartFlow.waiting_checklist), F.data.startswith(CHECKLIST_PREFIX)
    )
    async def on_checklist(callback: CallbackQuery, state: FSMContext, space: str) -> None:
        await callback.answer()
        message = callback.message
        if not isinstance(message, Message):
            return
        lang = chat_ui_lang(message.chat.id)
        code = (callback.data or "").removeprefix(CHECKLIST_PREFIX)
        открыты = _open_checklists(space) or []
        if code not in {c.code for c in открыты}:
            # Методист закрыл чек-лист, пока аудитор смотрел на кнопки: не
            # подменяем соседним молча, а показываем свежий список.
            await stops.refuse(message, lang, step="start.checklist", key="start.checklist_gone")
            await _ask_checklist(message, state, lang, space)
            return
        await state.update_data(checklist=code)
        await _ask_unit(message, state, lang)

    @router.callback_query(StateFilter(StartFlow.waiting_kind), F.data.startswith(KIND_PREFIX))
    async def on_kind(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        message = callback.message
        if not isinstance(message, Message):
            return
        code = (callback.data or "").removeprefix(KIND_PREFIX)
        if code not in KIND_TITLES:
            return
        await state.update_data(kind=code)
        await state.set_state(StartFlow.waiting_lang)
        await message.answer(
            t("start.ask_lang", chat_ui_lang(message.chat.id)), reply_markup=lang_keyboard()
        )

    @router.callback_query(StateFilter(StartFlow.waiting_lang), F.data.startswith(LANG_PREFIX))
    async def on_lang(callback: CallbackQuery, state: FSMContext, space: str) -> None:
        await callback.answer()
        message = callback.message
        if not isinstance(message, Message):
            return
        report_lang = (callback.data or "").removeprefix(LANG_PREFIX)
        if report_lang not in LANG_LABELS:
            return
        lang = chat_ui_lang(message.chat.id)
        data = await state.get_data()
        unit = str(data.get("unit", "")).strip()
        kind_code = str(data.get("kind", ""))
        if not unit or kind_code not in KIND_TITLES:
            # Мастер потерял ответы прошлых шагов (перезапуск, старая кнопка) и
            # начинается заново — для человека это тот же отказ, и он посчитан.
            await state.clear()
            await stops.refuse(
                message,
                lang,
                step="start.lang",
                key="start.greeting",
                reply_markup=new_inspection_keyboard(lang),
            )
            return

        auditor = auditor_name(
            callback.from_user.id, callback.from_user.full_name, settings.auditor_names
        )
        # Считаем ДО обрезки, пока имя профиля ещё под рукой: `auditor` выше
        # уже обрезан (это и есть контракт `auditor_name`), а обрезалось ли
        # оно — узнать можно только сравнением с тем же необрезанным именем.
        auditor_shortened = auditor_name_was_shortened(
            callback.from_user.id, callback.from_user.full_name, settings.auditor_names
        )
        try:
            # Подпроцесс — в поток: старт проверки не должен останавливать бота
            # для остальных аудиторов (T101).
            inspection = await asyncio.to_thread(
                domain.start_inspection,
                message.chat.id,
                unit=unit,
                # Вид проверки уходит КОДОМ, а не словом (T152): словом он
                # жил как данные — в проверке, в колонке базы, в отпечатке — и
                # переводился обратно сопоставлением строк. Перевод по языку
                # отчёта делает сам `domain` в тот момент, когда шапку
                # заполняет для движка: на кнопке аудитор прочитал вид сам, а
                # партнёру в документ он уезжает на языке отчёта.
                kind=kind_code,
                report_lang=report_lang,
                # Языка в проверке три (T025). Интерфейс — язык ЧЕЛОВЕКА
                # (D303): его выбор `/lang`, иначе язык стенда; отчёт к нему
                # больше не привязан — до D303 английский отчёт заодно
                # переключал и разговор. Речь по-прежнему идёт за отчётом:
                # отдельного вопроса о ней в мастере нет.
                ui_lang=person_ui_lang(),
                speech_lang=report_lang,
                auditor=auditor,
                # Пространство того, кто начал (волна 1, #340): в нём проверка
                # сливается в базу и в нём ищет прошлые проверки точки.
                tenant=space,
                # Выбран на первом шаге; пусто — открыт был один, и домен
                # возьмёт его сам (или откажет, если за это время открыли второй).
                checklist_code=str(data.get("checklist") or "") or None,
            )
        except DomainError:
            # Отказ движка приходит стеком с путями к его файлам: он написан
            # тому, кто зовёт движок из командной строки. В журнал целиком, в
            # чат — что делать (T151, тот же принцип, что у T127).
            logger.exception("не удалось начать проверку в чате %s", message.chat.id)
            await stops.refuse(message, lang, step="start.lang", key="start.failed")
            return
        finally:
            await state.clear()

        # Заметки бота — того же возраста, что и проверка: источники записей,
        # список кадров и последняя зона от прошлой к новой не относятся.
        sidecar.reset(message.chat.id)
        if pending is not None:
            pending.forget(message.chat.id)
        if store is not None:
            # Очередь ожидания — того же возраста (T249, issue #202). Чистится
            # здесь, а не на входе в мастер: мастер аудитор бросает на полпути,
            # и тогда прежняя проверка остаётся жить — вместе со сказанным в
            # неё. Именно поэтому и сама проверка лежит на диске до этой
            # строки (T052).
            store.forget(message.chat.id)

        started_lang = ui_lang_or_default(inspection.ui_lang)
        # Обрезка не уезжает молча (T128): строка про неё — рядом с именем,
        # той же строкой сообщения, что и старт проверки, а не отдельным
        # сообщением, которое легко потерять среди присланных кадров.
        auditor_note = (
            f"{t('start.auditor_name_shortened', started_lang)}\n" if auditor_shortened else ""
        )
        # Правило фотофиксации — заранее, первым же сообщением проверки (T160,
        # решение D078). Это единственное место, где его можно сказать ДО
        # первой ошибки: дальше остаётся только отвечать правилом на неё, а
        # решение D078 требует, чтобы человек понял это заранее, а не постфактум.
        await message.answer(
            with_photo_rule(
                t(
                    "start.started",
                    started_lang,
                    unit=inspection.unit,
                    # В проверке лежит код, аудитору показывается слово. Язык
                    # тут язык начатой проверки, а не язык кнопки: сообщение о
                    # старте читает он же, но уже внутри проверки.
                    kind=kind_title(inspection.kind, started_lang),
                    lang=LANG_LABELS[report_lang],
                    auditor=inspection.auditor,
                    auditor_note=auditor_note,
                    date=inspection.date,
                ),
                started_lang,
            )
        )

    return router
