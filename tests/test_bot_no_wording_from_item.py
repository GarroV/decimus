"""Бот не пишет за аудитора формулировку вопроса методики (T287, решение D128).

Вопросы методики написаны утверждением нормы: «Замороженные продукты
размораживаются в соответствии со стандартом». Ручной выбор пункта по кадру без
комментария клал этот текст в запись как слова аудитора — и партнёр читал в
отчёте утверждение нормы ровно там, где зафиксировано отклонение. Правила
фиксации требуют обратного: в поле формулировки идёт факт и ничего кроме факта
(`docs/03-recording-rules.md`).

Порядок взят у блока `engine-fix` (T248): запись остаётся БЕЗ формулировки, а
как назвать её в документе, решает место печати — отчёт строки записи не
печатает, письмо зовёт пункт пунктом (`пункт стандарта «…»`). Связь с пунктом у
записи никуда не девается: она держится кодом (`qid`), а коды не переводятся и
не правятся. Написать ту же ссылку словами в самом боте значило бы завести
вторую копию выражения, которая разъедется с первой при первой же правке.

Почему тест, хотя роутер — обвязка (`docs/furca/constitution.md`, таблица
слоёв): сторожится здесь не хендлер, а правило формулировок — слой, где сбой
молчит. Запись выглядит заполненной, отчёт правдоподобен, и неверный текст
получает партнёр.
"""

from __future__ import annotations

import pytest
from bot_harness import (
    AUDITOR_ID,
    CHAT_ID,
    feed,
    make_bot,
    manual,
    photo_message,
    stub_classify,
    stub_manual,
    suggestion,
)
from bot_harness import callback_query as callback

from src.bot.app import build_dispatcher
from src.bot.config import BotSettings
from src.domain import get_item, get_state, start_inspection

pytestmark = pytest.mark.asyncio

SETTINGS = BotSettings(
    token="unused-in-tests",
    allowed_ids=frozenset({AUDITOR_ID}),
    mode="polling",
    auditor_names={},
)

#: Пункт, который аудитор выбирает руками, и зона, в которой он его выбирает.
ПУНКТ = "CLN05"
ЗОНА = "hot_kitchen"


async def _ручной_выбор(
    monkeypatch: pytest.MonkeyPatch, *, caption: str | None = None, lang: str = "ru"
) -> str:
    """Кадр → «Разобрать» → зона кнопкой → пункт из ручного перечня.

    Модель молчит намеренно (`suggestion()` без кандидатов): ручной перечень
    показывается ровно тогда, когда разобрать материал не вышло, — это и есть
    путь, на котором стояла подмена. Возвращает текст последнего сообщения бота.
    """
    stub_classify(monkeypatch, suggestion())
    stub_manual(monkeypatch, (manual(ПУНКТ, ("D1",), get_item(ПУНКТ).question(lang)),))
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await feed(dp, bot, photo_message("frame-1", caption=caption, message_id=501))
    await feed(dp, bot, callback("rec:analyze:501"))
    await feed(dp, bot, callback(f"rec:zm:{ЗОНА}"))
    await feed(dp, bot, callback("rec:mi:0"))
    return session.last_text


async def test_кадр_без_комментария_кладёт_запись_без_формулировки(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Слов аудитор не сказал — значит, формулировки у записи нет.

    Главная проверка задачи. Раньше сюда попадал вопрос пункта целиком, и
    отличить такую запись от честно записанной было нечем ни человеку, ни
    движку.
    """
    start_inspection(CHAT_ID, "Белград 2", "planned", "ru")

    await _ручной_выбор(monkeypatch)

    state = get_state(CHAT_ID)
    assert state is not None and len(state.findings) == 1, "запись не появилась"
    найденное = state.findings[0]
    assert найденное.text.strip() == "", f"боту нашлись слова за аудитора: {найденное.text!r}"


async def test_вопрос_методики_в_запись_не_попадает_ни_на_одном_языке(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Сторож от обходного пути: подставить тот же текст вручную или переводом.

    Язык разговора здесь английский, а проверяются ОБА: пересказать вопрос
    методики словами аудитора нельзя ни на языке чата, ни на языке отчёта.
    """
    start_inspection(CHAT_ID, "Belgrade 2", "planned", "en", ui_lang="en")

    await _ручной_выбор(monkeypatch, lang="en")

    state = get_state(CHAT_ID)
    assert state is not None and len(state.findings) == 1, "запись не появилась"
    записано = state.findings[0].text
    пункт = get_item(ПУНКТ)
    for язык in ("ru", "en"):
        assert пункт.question(язык) not in записано, f"вопрос методики ({язык}) выдан за запись"


async def test_связь_с_пунктом_держится_кодом_а_не_текстом(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Формулировки нет — пункт всё равно назван: в записи стоит его код.

    Это и есть «ссылка на пункт» из D128. Без этого сторожа правка выглядела бы
    как потеря связи с методикой, а не как отказ писать за аудитора.
    """
    start_inspection(CHAT_ID, "Белград 2", "planned", "ru")

    await _ручной_выбор(monkeypatch)

    state = get_state(CHAT_ID)
    assert state is not None and len(state.findings) == 1, "запись не появилась"
    найденное = state.findings[0]
    assert найденное.code == ПУНКТ, f"пункт записи потерян: {найденное.code!r}"
    assert найденное.zone == ЗОНА, f"зона записи потеряна: {найденное.zone!r}"


async def test_слова_аудитора_текстом_записи_остаются(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Граница правки: комментарий аудитора — по-прежнему текст записи.

    Без этого сторожа «не писать за аудитора» легко превращается в «не писать
    вовсе», и молча пропадали бы настоящие слова с подписи к кадру.
    """
    start_inspection(CHAT_ID, "Белград 2", "planned", "ru")
    слова = "жирный налёт на решётке гриля"

    await _ручной_выбор(monkeypatch, caption=слова)

    state = get_state(CHAT_ID)
    assert state is not None and len(state.findings) == 1, "запись не появилась"
    assert state.findings[0].text == слова, "слова аудитора не стали текстом записи"


async def test_подтверждение_не_показывает_пустую_формулировку(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Аудитор читает вопрос пункта, а не пустые кавычки «В отчёт: «»».

    Показ и был причиной, по которой вопрос когда-то подставили в текст записи.
    Пустые кавычки читаются как сбой бота, а не как «формулировки пока нет».
    """
    start_inspection(CHAT_ID, "Белград 2", "planned", "ru")

    показано = await _ручной_выбор(monkeypatch)

    assert "«»" not in показано, f"в подтверждении пустые кавычки: {показано!r}"
    assert "В отчёт" not in показано, "подтверждение обещает партнёру пустую формулировку"
    assert get_item(ПУНКТ).question("ru") in показано, "пункт в подтверждении не назван"
