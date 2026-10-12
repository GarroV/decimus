"""«Завершить проверку» из приложения (D422, D439): сводка или сразу отчёт.

`POST /tg/walk/app {op: "finish"}` (адрес и опознание — `walk_settings`). Что
уходит в чат, решает режим человека (`db.finish_modes`, выбирается в настройках
приложения):

* `summary` (по умолчанию) — тот же итог, что даёт `/finish`: зовётся
  `bot.routers.finish.show_summary`, текст и кнопки здесь не пишутся заново.
  Дальше человек подтверждает в чате, и отчёт собирает обычная цепочка бота;
* `report` — отчёт сразу: язык отчёта (из перечня страны, `bot.report_lang`),
  проверка информационной части, затем `bot.routers.finish.deliver` — та же
  функция, что собирает отчёт в чате.

Отличие от бота одно — сообщения уходят не из процесса бота, а отсюда, прямым
запросом к Bot API с тем же токеном; поэтому «Message» здесь — заготовка с
номером чата, привязанная к клиенту Bot API.

Что решено:

* **Сообщение уходит только по явному нажатию человека и его подтверждению в
  приложении (D439) — и только в чат из подписанного initData.** Чужой чат
  назвать нельзя: номер берётся из подписи, а не из тела запроса.
* **Информационную часть отсюда не провести.** Её вопросы живут в
  конечном автомате бота (память другого процесса), веб его не запускает.
  Остались неотвеченные поля — отчёт не собирается, приложение просит
  заполнить «Сведения» (их можно заполнить и в приложении, D312) и нажать ещё
  раз. Это предел решения, а не недосмотр.
* **Очередь ожидания бота** (кадры и слова без пары, `MaterialStore`) тоже в
  памяти бота. Итог из приложения собирается с пустой очередью; кадры,
  присланные в чат без записи, он не назовёт. См. `docs/13-walk-mini-app.md`.
* **Сборка отчёта — в фоне, по одной на чат.** PDF, архив и письмо занимают
  десятки секунд: приложение получает ответ сразу и закрывается, отчёт приходит
  в чат. Вторая сборка того же чата, пока идёт первая, отказывается.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from src.domain import get_state, set_report_lang
from src.domain.errors import DomainError

if TYPE_CHECKING:
    from aiogram import Bot
    from aiogram.types import Message

logger = logging.getLogger(__name__)

#: Результат шага: ушёл ли итог в чат.
SENT = "sent"
NO_INSPECTION = "no_inspection"
FAILED = "failed"
#: Отчёт: сборка запущена; язык не из перечня страны; не заполнены сведения; уже собирается.
STARTED = "started"
LANG_GONE = "lang_gone"
INFO_MISSING = "info_missing"
BUSY = "busy"

#: Чаты, у которых сейчас собирается отчёт. Один процесс веба — один набор.
_building: set[int] = set()
_building_lock = threading.Lock()


@dataclass(frozen=True)
class ReportStart:
    """Итог запуска отчёта: статус и, для `INFO_MISSING`, сколько полей осталось."""

    status: str
    missing: int = 0


def has_inspection(chat_id: int) -> bool:
    """Есть ли у чата проверка. Нечитаемое состояние — «есть»: отказывать нечем."""
    try:
        return get_state(chat_id) is not None
    except DomainError:
        logger.exception("Завершение из приложения: состояние чата %s не читается", chat_id)
        return True


def _stub_message(bot: Bot, chat_id: int) -> Message:
    """Сообщение-заготовка: номер чата и клиент Bot API, остального отсюда не нужно."""
    from aiogram.types import Chat, Message

    return Message(message_id=0, date=datetime.now(UTC), chat=Chat(id=chat_id, type="private")).as_(
        bot
    )


async def _send_summary(token: str, chat_id: int) -> None:
    # Лениво: цепочка `bot.routers.finish` тянет отчёт и PDF, а вебу без запроса
    # завершения они не нужны.
    from aiogram import Bot

    from src.bot.lang import chat_ui_lang
    from src.bot.material import MaterialStore
    from src.bot.routers.finish import show_summary

    bot = Bot(token)
    try:
        await show_summary(
            _stub_message(bot, chat_id), chat_id, chat_ui_lang(chat_id), store=MaterialStore()
        )
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


async def _deliver_report(token: str, chat_id: int) -> None:
    from aiogram import Bot

    from src.bot.lang import chat_ui_lang
    from src.bot.routers.finish import deliver
    from src.bot.texts import t

    lang = chat_ui_lang(chat_id)
    bot = Bot(token)
    try:
        try:
            await deliver(_stub_message(bot, chat_id), chat_id, lang, allow_missing=False)
        except Exception:  # — человек уже вышел из приложения: молчать нельзя
            logger.exception("Завершение из приложения: отчёт чата %s не собрался", chat_id)
            await bot.send_message(chat_id, t("finish.pdf_failed", lang))
    finally:
        await bot.session.close()


def _run_report(token: str, chat_id: int) -> None:
    try:
        asyncio.run(_deliver_report(token, chat_id))
        logger.info("Завершение из приложения: сборка отчёта чата %s закончена", chat_id)
    except Exception:  # — даже письмо об отказе не ушло: остаётся журнал
        logger.exception("Завершение из приложения: отчёт чата %s — сбой без ответа в чат", chat_id)
    finally:
        with _building_lock:
            _building.discard(chat_id)


def _offered(chat_id: int) -> list[str] | None:
    """Языки отчёта этой проверки; `None` — проверки нет. Лениво, как и остальная цепочка бота."""
    from src.bot.report_lang import langs_for_inspection

    inspection = get_state(chat_id)
    return None if inspection is None else langs_for_inspection(inspection)


def offered_report_langs(chat_id: int) -> list[str]:
    """Языки отчёта по стране пиццерии этой проверки; нет проверки или она нечитаема — пусто."""
    try:
        return _offered(chat_id) or []
    except DomainError:
        logger.warning("Завершение из приложения: языки отчёта чата %s", chat_id, exc_info=True)
        return []


def _missing_info(chat_id: int, ui_lang: str) -> int:
    """Сколько полей информационной части не заполнено — те же, что спросил бы бот."""
    from src.bot.info import fields_to_ask

    return len(fields_to_ask(ui_lang, chat_id=chat_id))


def start_report(token: str, chat_id: int, report_lang: str | None, ui_lang: str) -> ReportStart:
    """Запустить сборку отчёта. Ничего не отправляется, пока не пройдены все проверки.

    Порядок: проверка есть → язык из перечня страны (перечень считается заново, а
    не берётся из запроса) → информационная часть заполнена → в чате не идёт
    другая сборка → язык назначен → сборка в фоне. Отказ на любом шаге до
    последнего состояния проверки не меняет.
    """
    try:
        offered = _offered(chat_id)
        if offered is None:
            return ReportStart(NO_INSPECTION)
        chosen = report_lang or (offered[0] if len(offered) == 1 else None)
        if chosen is None or chosen not in offered:
            return ReportStart(LANG_GONE)
        missing = _missing_info(chat_id, ui_lang)
        if missing:
            return ReportStart(INFO_MISSING, missing)
        with _building_lock:
            if chat_id in _building:
                return ReportStart(BUSY)
            _building.add(chat_id)
    except DomainError:
        logger.exception("Завершение из приложения: чат %s — состояние не читается", chat_id)
        return ReportStart(FAILED)
    try:
        set_report_lang(chat_id, chosen)
        threading.Thread(
            target=_run_report, args=(token, chat_id), name=f"walk-report-{chat_id}", daemon=True
        ).start()
    except Exception:  # — до запуска потока: освободить чат, иначе он заперт навсегда
        logger.exception("Завершение из приложения: отчёт чата %s не запущен", chat_id)
        with _building_lock:
            _building.discard(chat_id)
        return ReportStart(FAILED)
    logger.info("Завершение из приложения: сборка отчёта чата %s запущена", chat_id)
    return ReportStart(STARTED)
