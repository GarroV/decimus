"""Очередь ожидания не переживает смену проверки (T249, issue #202).

`MaterialStore` живёт в памяти процесса и ключуется только по `chat_id`.
До этой задачи его не чистили ни начало новой проверки, ни сдача отчёта —
поэтому придержанные слова (T229) и кадры без комментария (T053), оставшиеся
от ЗАКОНЧЕННОЙ проверки, доставались следующей.

**Чем это дорого.** Запись уезжает в отчёт партнёру: фотография одной пиццерии
под формулировкой, сказанной в другой. Заметить это можно только на
предвычитке, и то если помнить, о чём была фраза. Перезапуск бота дефект
маскирует — в памяти после него пусто, — поэтому на стенде он ловится не всегда.

**Где именно чистится.** В тот момент, когда новая проверка ДЕЙСТВИТЕЛЬНО
началась (`domain.start_inspection` отработал), рядом с `sidecar.reset` и
`pending.forget` — а не на входе в мастер. Мастер аудитор бросает на полпути,
и очистка на входе стирала бы ожидания ЖИВОЙ проверки, к которой он вернётся.
Ровно по той же причине и сама старая проверка лежит на диске до последнего
шага мастера (T052).

Второе место — «Убрать из чата»: проверки после него нет вовсе.

**Почему не на завершении старой проверки.** Сданную дополнить нечем: кадр,
комментарий и правка упираются в отказ запечатанной проверки (`sealed.py`) и до
очереди не доходят. Забрать ожидания старой может только новая — на её пороге
очистка и стоит. Ровно тот же выбор сделан для `PendingStore.forget` (T206),
и этот файл проверяет именно исход, а не место вызова: после сданного отчёта
следующая проверка начинается с чистого листа.
"""

from __future__ import annotations

import pytest
from aiogram import Bot, Dispatcher
from bot_harness import (
    AUDITOR_ID,
    CHAT_ID,
    build_report,
    callback_query,
    candidate,
    feed,
    make_bot,
    photo_message,
    stub_classify,
    suggestion,
    text_message,
)

from src.bot import sidecar
from src.bot.app import build_dispatcher
from src.bot.config import BotSettings
from src.bot.keyboards import (
    NEW_INSPECTION_CALLBACK,
    RESUME_CONTINUE_CALLBACK,
    RESUME_NEW_CALLBACK,
    SEALED_DROP_CALLBACK,
)
from src.bot.material import ChatMaterialQueue, Comment, MaterialStore, PhotoGroup
from src.bot.texts import t
from src.domain import get_state, start_inspection

#: Часть тестов файла — юнит-тесты хранилища, поэтому отметка стоит на
#: асинхронных по одной, а не на модуле: в строгом режиме pytest-asyncio
#: модульная отметка на синхронном тесте — предупреждение на каждом прогоне.
async_test = pytest.mark.asyncio

SETTINGS = BotSettings(token="unused-in-tests", allowed_ids=frozenset({AUDITOR_ID}), mode="polling")

#: Однозначная фраза на синтетической карте (см. `tests/methodology`): зону
#: подставит память, как на точке.
OVEN = "печь грязная"


def started(unit: str = "Первая точка") -> None:
    start_inspection(CHAT_ID, unit, "planned", "ru", ui_lang="ru")
    sidecar.remember_zone(CHAT_ID, "hot_kitchen")


async def start_new_inspection(dp: Dispatcher, bot: Bot, unit: str) -> None:
    """Пройти мастер целиком — тем же путём, каким идёт аудитор."""
    await feed(dp, bot, text_message("/start"))
    await feed(dp, bot, callback_query(RESUME_NEW_CALLBACK))
    await feed(dp, bot, text_message(unit))
    await feed(dp, bot, callback_query("start:kind:planned"))
    await feed(dp, bot, callback_query("start:lang:ru"))


def findings_count() -> int:
    state = get_state(CHAT_ID)
    return 0 if state is None else len(state.findings)


@async_test
async def test_кадр_новой_проверки_не_забирает_слова_старой(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Главный случай issue #202: слова одной пиццерии под кадром другой."""
    started("Первая точка")
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)
    calls = stub_classify(monkeypatch, suggestion(candidate("CLN05", "D1", "hot_kitchen")))

    await feed(dp, bot, text_message(OVEN))
    assert t("material.waiting_photo", "ru") in session.last_text, "слова не придержаны"

    await start_new_inspection(dp, bot, "Вторая точка")
    session.clear()

    await feed(dp, bot, photo_message("frame-new"))

    assert session.last_text == t("material.photo_taken", "ru"), (
        "кадр новой проверки собрал материал из слов старой"
    )
    assert calls == [], "разбор пошёл по чужим словам"
    assert findings_count() == 0, "запись в новой проверке появилась из слов старой"


@async_test
async def test_слова_новой_проверки_не_забирают_кадр_старой(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Симметричный случай: кадр без комментария остался от прошлой проверки."""
    started("Первая точка")
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)
    calls = stub_classify(monkeypatch, suggestion(candidate("CLN05", "D1", "hot_kitchen")))

    await feed(dp, bot, photo_message("frame-old"))
    assert session.last_text == t("material.photo_taken", "ru"), "кадр не встал в очередь"

    await start_new_inspection(dp, bot, "Вторая точка")
    session.clear()

    await feed(dp, bot, text_message(OVEN))

    assert t("material.waiting_photo", "ru") in session.last_text, (
        "слова новой проверки связались с кадром старой"
    )
    assert calls == [], "разбор пошёл по чужому кадру"
    assert findings_count() == 0


@async_test
async def test_вход_в_мастер_ожиданий_не_стирает(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Мастер, брошенный на полпути, не должен стоить аудитору сказанного.

    Нажатие «Начать новую» — ещё не новая проверка: старая лежит на диске до
    последнего шага мастера (T052), и ожидания обязаны пережить тот же путь.
    """
    started("Первая точка")
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)
    stub_classify(monkeypatch, suggestion(candidate("CLN05", "D1", "hot_kitchen")))

    await feed(dp, bot, text_message(OVEN))
    await feed(dp, bot, text_message("/start"))
    await feed(dp, bot, callback_query(RESUME_NEW_CALLBACK))
    # Аудитор передумал и вернулся к прежней проверке.
    await feed(dp, bot, text_message("/start"))
    await feed(dp, bot, callback_query(RESUME_CONTINUE_CALLBACK))
    session.clear()

    await feed(dp, bot, photo_message("frame-same"))

    assert findings_count() == 1, "придержанные слова живой проверки потерялись на входе в мастер"


@async_test
async def test_после_сданного_отчёта_следующая_проверка_чистая(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Полный боевой путь: слова остались без кадра, отчёт сдан, начата новая.

    Это тот самый прогон из issue #202, только с настоящим завершением посреди:
    сдача отчёта проверку запечатывает (D080), и придержанные слова становятся
    окончательно потерянными — но в СЛЕДУЮЩУЮ они попасть не должны.
    """
    started("Первая точка")
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)
    calls = stub_classify(monkeypatch, suggestion(candidate("CLN05", "D1", "hot_kitchen")))

    await feed(dp, bot, text_message(OVEN))
    await feed(dp, bot, text_message("/finish"))
    await build_report(dp, bot)
    assert sidecar.handed_over(CHAT_ID), "проверка не сдана — тест проверяет не то"

    await start_new_inspection(dp, bot, "Вторая точка")
    calls.clear()
    session.clear()

    await feed(dp, bot, photo_message("frame-new"))

    assert session.last_text == t("material.photo_taken", "ru"), (
        "кадр новой проверки забрал слова сданной"
    )
    assert calls == []
    assert findings_count() == 0


@async_test
async def test_убрать_из_чата_очередь_забывает(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """«Убрать из чата» уносит проверку целиком — вместе с её ожиданиями."""
    started("Первая точка")
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)
    calls = stub_classify(monkeypatch, suggestion(candidate("CLN05", "D1", "hot_kitchen")))

    await feed(dp, bot, text_message(OVEN))
    await feed(dp, bot, text_message("/finish"))
    await build_report(dp, bot)
    await feed(dp, bot, callback_query(SEALED_DROP_CALLBACK))

    await feed(dp, bot, callback_query(NEW_INSPECTION_CALLBACK))
    await feed(dp, bot, text_message("Вторая точка"))
    await feed(dp, bot, callback_query("start:kind:planned"))
    await feed(dp, bot, callback_query("start:lang:ru"))
    calls.clear()
    session.clear()

    await feed(dp, bot, photo_message("frame-new"))

    assert session.last_text == t("material.photo_taken", "ru"), (
        "кадр новой проверки забрал слова убранной из чата"
    )
    assert calls == []


# --- уровень хранилища: очистка адресная ---


def test_forget_чистит_обе_очереди_чата() -> None:
    store = MaterialStore()
    queue = store.queue(CHAT_ID)
    # Порядок важен: кадр, заведённый при непустой очереди слов, забрал бы их
    # себе — и в очереди не осталось бы ни того, ни другого.
    queue.add_group(PhotoGroup("g1", CHAT_ID, (1,), ("f1",), None))
    queue.hold_comment(Comment(text=OVEN))
    assert queue.has_pending() and queue.held_comments()

    store.forget(CHAT_ID)

    свежая = store.queue(CHAT_ID)
    assert свежая.held_comments() == (), "придержанные слова пережили очистку"
    assert not свежая.has_pending(), "кадр без комментария пережил очистку"


def test_forget_не_трогает_соседний_чат() -> None:
    """Аудиторы работают в своих чатах одновременно — очистка обязана быть адресной."""
    store = MaterialStore()
    store.queue(CHAT_ID).hold_comment(Comment(text=OVEN))
    store.queue(777).hold_comment(Comment(text=OVEN))

    store.forget(CHAT_ID)

    assert store.queue(777).held_comments(), "очистка одного чата унесла ожидания другого"


def test_forget_чата_без_очереди_не_падает() -> None:
    """Новая проверка в чате, где ничего не ждало, — обычный случай, а не ошибка."""
    MaterialStore().forget(CHAT_ID)


def test_ответ_на_кадр_забытой_очереди_ничего_не_находит() -> None:
    """Очистка уносит и постоянный индекс «сообщение → группа».

    Иначе ответ на кадр ПРОШЛОЙ проверки завёл бы запись в новой — тем же
    снимком, который аудитор снимал в другой пиццерии.
    """
    store = MaterialStore()
    store.queue(CHAT_ID).add_group(PhotoGroup("g1", CHAT_ID, (11,), ("f1",), None))

    store.forget(CHAT_ID)

    assert store.queue(CHAT_ID).resolve_reply(11, Comment(text=OVEN)) is None


def test_очередь_чата_сама_по_себе_осталась_прежней() -> None:
    """Очистка живёт в хранилище, а не в очереди: связывание не менялось."""
    queue = ChatMaterialQueue()
    queue.hold_comment(Comment(text=OVEN))
    material = queue.add_group(PhotoGroup("g1", CHAT_ID, (1,), ("f1",), None))
    assert material is not None and material.comment.text == OVEN
