"""Сборка бота: диспетчер, роутеры, доступ, запуск (задача T050).

Точка входа — `python -m src.bot`. Режим только long polling (решение D004,
`BOT_MODE`): постоянного публичного адреса нет ни на ноутбуке, ни на домашнем
сервере, а вебхук без него не поднять.

**Обновления обрабатываются последовательно** (`handle_as_tasks=False`). Это не
экономия и не осторожность, а требование задачи T059: по умолчанию aiogram
заводит задачу на каждое обновление, и пачка сообщений, пришедшая разом после
потери связи, разбирается вперемешку — комментарии привязываются не к тем
кадрам. Последовательная обработка даёт порядок по построению: Telegram
сохраняет порядок доставки внутри чата, и бот его больше не перемешивает.
Цена — пока идёт разбор одного сообщения, следующее ждёт; для проверки, где
работает один аудитор и шаги идут строго друг за другом, это и есть желаемое
поведение.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BotCommand,
    ErrorEvent,
    MenuButtonDefault,
    MenuButtonWebApp,
    Message,
    WebAppInfo,
)

from src import domain

from . import agg_loader, frame_copies, maps_loader, photo_backfill, upload_sweeper
from .access import AccessMiddleware, BindingCache, ChatSpaceMiddleware
from .albums import ALBUM_WINDOW_SECONDS, AlbumBuffer
from .config import BotSettings, load_bot_settings
from .lang import chat_ui_lang
from .lang_choice import PersonMiddleware
from .material import MaterialStore
from .pending import PendingStore
from .roster import Roster
from .routers import (
    build_correct_router,
    build_edit_router,
    build_fallback_router,
    build_finish_router,
    build_help_router,
    build_info_router,
    build_lang_router,
    build_material_router,
    build_mcp_router,
    build_record_router,
    build_records_router,
    build_resend_router,
    build_start_router,
    build_stops_router,
    build_version_router,
)
from .routers.help import HELP_COMMAND
from .routers.lang import LANG_COMMAND
from .routers.material import MaterialHandler
from .routers.mcp import MCP_COMMAND
from .routers.record import make_frame_handler, make_material_handler, make_waiting_handler
from .routers.records import RECORDS_COMMAND
from .routers.resend import RESEND_COMMAND
from .routers.version import VERSION_COMMAND
from .texts import DEFAULT_UI_LANG, default_ui_lang, t
from .version import build_version

logger = logging.getLogger(__name__)


def _asked_here(event: ErrorEvent) -> Message | None:
    """Сообщение, на которое можно ответить, — или ничего.

    Ничего бывает по-настоящему: обновление без чата (нажатие старше 48 часов
    приходит без сообщения), служебные события. Отвечать тогда некому, и
    остаётся журнал.
    """
    update = event.update
    if update.message is not None:
        return update.message
    callback = update.callback_query
    if callback is not None and isinstance(callback.message, Message):
        return callback.message
    return None


def _lang_here(chat_id: int) -> str:
    """Язык последнего рубежа: обычный язык чата, а если и он отказал — русский.

    Ответ на языке стенда хуже ответа на языке проверки, но несравнимо лучше
    молчания: аудитор на точке должен узнать о сбое и увидеть выход.
    """
    try:
        return chat_ui_lang(chat_id)
    except Exception:
        logger.exception("язык чата %s не выбрался — отвечаем на %s", chat_id, DEFAULT_UI_LANG)
        return DEFAULT_UI_LANG


async def on_unexpected_error(event: ErrorEvent) -> bool:
    """Сбой, который не поймал ни один хендлер (задача T126).

    Без этого обработчика aiogram неперехваченное исключение **глотает**:
    аудитор не получает ничего. Проверено на испорченном `inspection.json` —
    `/start`, `/finish`, приём кадра и правка бросали отказ, а в чат не
    приходило ни строки, и выйти из тупика было нечем.

    Аудитору уходит причина и что делать, разбор — в журнал. Текст исключения
    в чат не попадает: он написан для того, кто чинит, в нём пути к файлам и
    внутренние подробности, а человеку на точке нужен выход.

    Возвращает `True`: событие обработано. Ошибку это не прячет — она уже в
    журнале целиком, со стеком; `False` означало бы, что aiogram напишет её
    ещё раз своими словами.

    **Язык выбирается до попытки ответить и со своей защитой.** Раньше и то и
    другое стояло в одном `try`, и обработчик умирал сам: нечитаемое по правам
    состояние роняло `chat_ui_lang`, а в журнал уходило «не удалось сказать
    аудитору о сбое» — последний рубеж честно сообщал, что промолчал. Теперь
    `chat_ui_lang` не падает по построению (`src/bot/lang.py`), но здесь стоит
    вторая защита: за этим обработчиком нет никого, и полагаться в нём на чужую
    исправность — это ровно та ошибка, которой задача T126 и посвящена.
    """
    logger.exception("необработанный сбой на обновлении", exc_info=event.exception)
    message = _asked_here(event)
    if message is None:
        return True
    lang = _lang_here(message.chat.id)
    try:
        await message.answer(t("error.unexpected", lang))
    except Exception:
        # Ответить не вышло — телеграм отказал или чат недоступен. Падать
        # отсюда нельзя: это последний рубеж, за ним обработчика уже нет.
        logger.exception("не удалось сказать аудитору о сбое в чате %s", message.chat.id)
    return True


def build_dispatcher(
    settings: BotSettings,
    *,
    album_window: float = ALBUM_WINDOW_SECONDS,
    on_material: MaterialHandler | None = None,
    roster: Roster | None = None,
    bindings: BindingCache | None = None,
) -> Dispatcher:
    """Диспетчер со всеми роутерами и мидлварью доступа.

    `on_material` подменяется только тестами связывания: им важно, что с чем
    связалось, а не что предложила модель. В продукте это разбор из
    `routers/record.py` — тот самый, который показывает кандидатов кнопками.

    Порядок роутеров не случаен. Мастер начала проверки и правка формулировки
    ждут обычный текст в состоянии диалога, поэтому идут раньше приёма
    материала: иначе название пиццерии уедет в разбор как комментарий к кадру.

    Хранилище конечного автомата — в памяти намеренно: в нём живут только шаги
    мастера начала проверки и вопрос про новую формулировку, а сама проверка
    лежит в файле и переживает перезапуск без него (`src/bot/states.py`).
    """
    dispatcher = Dispatcher(storage=MemoryStorage())
    # Раньше роутеров: сбой в любом из них обязан дойти до аудитора, а не
    # раствориться в aiogram (T126).
    dispatcher.errors.register(on_unexpected_error)

    # Имя из связок, собранных по приглашениям до D286, нужно шапке отчёта; ручная
    # запись `AUDITOR_NAMES` сильнее — иначе исправить имя можно было бы только
    # правкой файла состояния (#230).
    if roster is not None:
        settings = replace(settings, auditor_names={**roster.names(), **settings.auditor_names})

    # Первой из внешних: человек апдейта нужен выбору языка (D303) везде, в
    # том числе в ответе на ссылку привязки, который даёт мидлварь доступа.
    person = PersonMiddleware()
    dispatcher.message.outer_middleware(person)
    dispatcher.callback_query.outer_middleware(person)

    access = AccessMiddleware(
        settings.allowed_ids, bindings if bindings is not None else BindingCache(), roster
    )
    dispatcher.message.outer_middleware(access)
    dispatcher.callback_query.outer_middleware(access)
    # После доступа: внешние мидлвари идут в порядке регистрации, а заслону
    # чата нужно пространство человека, которое кладёт доступ (D286).
    space_guard = ChatSpaceMiddleware()
    dispatcher.message.outer_middleware(space_guard)
    dispatcher.callback_query.outer_middleware(space_guard)

    # Память бота сверяется с личностью проверки на диске (D392): проверку
    # может начать и мини-апп, а он до этой памяти не дотягивается.
    store = MaterialStore(domain.run_id)
    pending = PendingStore(domain.run_id)

    # Мастер получает оба хранилища в памяти (`pending`, `store`) не ради
    # работы, а ради забывания: начатая проверка обязана начинаться с чистого
    # листа — иначе кнопка прошлой проверки выстрелит в новую (T206), а кадр
    # новой заберёт придержанные слова старой (T249).
    dispatcher.include_router(build_start_router(settings, pending, store))
    dispatcher.include_router(build_edit_router())
    # Показ записанного и завершение получают ту же очередь ожидания, из которой
    # собираются записи (T241): при завершении называются не только кадры без
    # записи, но и слова, кадра не дождавшиеся.
    dispatcher.include_router(build_records_router(store))
    # Установка MCP (T209, T253, D448) и версия сборки (T246) —
    # рядом с остальными командами: своих состояний диалога у них нет, обычного
    # текста они не ждут, и на порядок разбора материала не влияют.
    dispatcher.include_router(build_mcp_router())
    dispatcher.include_router(build_stops_router())
    dispatcher.include_router(build_help_router())
    dispatcher.include_router(build_lang_router())
    dispatcher.include_router(build_resend_router())
    dispatcher.include_router(build_version_router())
    dispatcher.include_router(build_finish_router(store))
    # Информационная часть ждёт обычный текст, голос и кадр в своём состоянии
    # диалога (T158), поэтому идёт раньше приёма материала: иначе ответ на
    # вопрос уехал бы в разбор как комментарий к кадру.
    dispatcher.include_router(build_info_router())
    dispatcher.include_router(build_record_router(store=store, pending=pending))
    # Правка ответом на сообщение бота (T204) — ДО приёма материала: иначе ответ
    # уедет комментарием к ждущему кадру, и вместо правки записи появится
    # вторая. Ответ не про запись этот роутер пропускает дальше нетронутым.
    dispatcher.include_router(build_correct_router(pending=pending))
    dispatcher.include_router(
        build_material_router(
            store=store,
            albums=AlbumBuffer(),
            on_material=on_material or make_material_handler(pending),
            on_waiting=make_waiting_handler(pending),
            # Кадр ответом на свои же слова уходит в ту запись, о которой они
            # были (T205): без этого он завёл бы вторую очередь ожидания и
            # второе нарушение о том же самом.
            on_frame=make_frame_handler(),
            album_window=album_window,
        )
    )
    # Последним и без фильтра данных (T134): нажатие, которое не подошло ни
    # одному обработчику выше, обязано получить ответ, иначе телеграм крутит
    # человеку часики до собственного таймаута. Порядок здесь и есть весь
    # механизм — стой этот роутер раньше, он съедал бы живые нажатия.
    dispatcher.include_router(build_fallback_router())
    return dispatcher


def create_bot(settings: BotSettings) -> Bot:
    return Bot(token=settings.token, default=DefaultBotProperties())


#: Команды в меню телеграма: имя и ключ описания в каталоге текстов.
#:
#: Порядок — порядок работы аудитора, а не алфавит: начать, посмотреть
#: записанное, снять последнее, завершить. Версия сборки (T246) стоит последней
#: и этот порядок не ломает: она не шаг обхода, а вопрос «что у нас крутится», —
#: и место ей за работой, а не посреди неё.
#:
#: Чего в меню нет намеренно: снятия сданной проверки. По решению D086 это
#: операция управляющей компании через MCP, а не кнопка у аудитора на точке, —
#: и входа в неё бот не получает вовсе (`src/mcp/retraction.py`).
MENU_COMMANDS = (
    ("start", "cmd.start"),
    (RECORDS_COMMAND, "cmd.records"),
    ("undo", "cmd.undo"),
    ("finish", "cmd.finish"),
    # Справка и версия — не шаги обхода, поэтому стоят за работой, а не
    # посреди неё. Справка выше версии: её читает аудитор, и читает чаще.
    (HELP_COMMAND, "cmd.help"),
    # Язык бота (D303) — рядом со справкой: тоже не шаг обхода, а настройка,
    # и подписан на обоих языках, чтобы его нашёл и тот, кто язык стенда не читает.
    (LANG_COMMAND, "cmd.lang"),
    # Подключение Claude (D448): токен себе выпускает каждый, кого бот пускает,
    # — круга, который видел пункт отдельно, больше нет.
    (MCP_COMMAND, "cmd.mcp"),
    (RESEND_COMMAND, "cmd.resend"),
    (VERSION_COMMAND, "cmd.version"),
)


def _menu(commands: tuple[tuple[str, str], ...], lang: str) -> list[BotCommand]:
    return [BotCommand(command=name, description=t(key, lang)) for name, key in commands]


async def announce_commands(bot: Bot) -> None:
    """Объявить команды в меню телеграма (T139, T253).

    Без этого команда есть, но её не видно: аудитор на точке не набирает
    `/records` по памяти — он нажимает синюю кнопку меню и выбирает из списка.
    Ровно из-за этого показ записанного и был спрятан за «Завершить»: другого
    входа у него не было, а этот никто не показывал.

    Меню одно на всех, кого пускает мидлварь доступа: личные меню круга
    доступа к MCP сняты вместе с кругом (D448).

    Язык — язык стенда (`BOT_UI_LANG`, T131), а не проверки: меню телеграм
    спрашивает один раз при подъёме бота, когда никакой проверки ещё нет.

    Отказ телеграма сюда не пускается наружу: без меню бот работает, а не
    подняться из-за него — цена несоразмерная. В журнал он попадает целиком.
    """
    lang = default_ui_lang()
    try:
        await bot.set_my_commands(_menu(MENU_COMMANDS, lang))
    except Exception:
        logger.exception("команды в меню телеграма не объявились — бот работает без меню")


async def announce_app_button(bot: Bot, settings: BotSettings) -> None:
    """Кнопка запуска мини-аппа у поля ввода вместо ☰ (D372).

    Постоянный вход: до D372 мини-апп открывался только кнопкой под
    сообщением «проверка начата», и вне проверки его было не найти. Команды
    при этом не пропадают — их список открывается набором «/».

    Адреса нет — возвращается ☰: очищенный `BOT_WALK_URL` снимает и кнопку.
    Круг тестеров (`WALK_USERS`) — кнопка только им, остальным ☰. Кого бот не
    пускает, кнопка не пустит тоже: мини-апп сверяет доступ тем же правилом
    (`web.walk_access`). Отказ телеграма — в журнал: без кнопки бот работает.
    """
    кнопка: MenuButtonDefault | MenuButtonWebApp = MenuButtonDefault()
    if settings.walk_url is not None:
        кнопка = MenuButtonWebApp(
            text=t("btn.app", default_ui_lang()), web_app=WebAppInfo(url=settings.walk_url)
        )
    общая = кнопка if settings.walk_users is None else MenuButtonDefault()
    await _menu_button(bot, None, общая)
    # Каждому тестеру — отдельно и со своим отказом: не нажавший /start не
    # должен оставить без кнопки остальных. Без адреса личные тоже снимаются.
    # Выведенного из круга тут не знают — его кнопка остаётся, но мини-апп
    # ему ответит 403 (`walk_open_to`).
    for user_id in sorted(settings.walk_users or ()):
        await _menu_button(bot, user_id, кнопка)


async def _menu_button(
    bot: Bot, chat_id: int | None, кнопка: MenuButtonDefault | MenuButtonWebApp
) -> None:
    try:
        await bot.set_chat_menu_button(chat_id=chat_id, menu_button=кнопка)
    except Exception:
        logger.exception("кнопка у поля ввода не объявилась (%s) — бот работает без неё", chat_id)


def log_startup(settings: BotSettings) -> None:
    """Первая строка журнала: режим, доступ и ВЕРСИЯ сборки.

    Версия здесь не для порядка. Когда бот отвечает отказом, первым уходит
    время на выяснение того, что вообще крутится на площадке, — а образ и
    каталог с кодом расходятся молча (T246, #201).
    """
    logger.info(
        "бот поднят в режиме %s, разрешённых ID: %s, сборка: %s",
        settings.mode,
        len(settings.allowed_ids),
        build_version(),
    )


async def start_polling() -> None:
    """Поднять бота: проверить окружение, затем слушать Telegram."""
    settings = load_bot_settings()
    # Методика проверяется до первого сообщения: пустой чек-лист читался бы как
    # честный ответ «нарушений нет», а узнать об этом на точке — поздно.
    domain_settings = domain.check_environment()
    # Связки «юзернейм → ID», собранные по приглашениям до D286, читаются один
    # раз при подъёме — совместимость до снятия. Каталог состояния здесь уже
    # проверен — раньше него читать нечего.
    roster = Roster.load(domain_settings.state_dir)
    bot = create_bot(settings)
    await announce_commands(bot)
    await announce_app_button(bot, settings)
    dispatcher = build_dispatcher(settings, roster=roster)
    log_startup(settings)
    # Уборка копий кадров старше недели (#367, D179). Ссылка держится до конца
    # опроса: задачу без ссылки сборщик мусора снимает на середине.
    sweeper = asyncio.create_task(frame_copies.sweep_forever())
    # Дозагрузка кадров, не легших в хранилище на сдаче (#459, D259): хранилище
    # на MUSPELHEIM засыпает, и вернуть кадры потом может только бот — байты
    # есть у телеграма, а токен у него одного.
    backfill = asyncio.create_task(photo_backfill.backfill_forever(bot))
    # Брошенные кадры мини-аппа старше недели (F-033, #531): без базы не убирает.
    uploads = asyncio.create_task(upload_sweeper.sweep_forever())
    # Оценки пиццерий на картах из Pointer — раз в сутки (docs/09-pointer-api.md).
    map_ratings = asyncio.create_task(maps_loader.load_forever())
    # Оценки пиццерий в агрегаторах доставки — раз в сутки (D389, docs/17-aggregators.md).
    agg_ratings = asyncio.create_task(agg_loader.load_forever())
    try:
        await dispatcher.start_polling(bot, handle_as_tasks=False)
    finally:
        sweeper.cancel()
        backfill.cancel()
        uploads.cancel()
        map_ratings.cancel()
        agg_ratings.cancel()
        await bot.session.close()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    asyncio.run(start_polling())
