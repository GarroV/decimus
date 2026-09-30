"""Занятый пункт в перечне помечен, а не предложен молча (T137, issue #108).

Сцена целиком. Аудитор снимает то, что уже записал, и просит разобрать кадр
моделью. Модель предлагает **тот же самый** пункт в той же зоне, и в перечне он
не должен ничем не отличаться от остальных: аудитор обязан видеть, что такая
запись уже есть. С #443 (D243, D247) нажатие на такой пункт положит кадр в ту
запись, а не заведёт вторую, — пометка говорит, куда именно он ляжет.

Пометка идёт по ПАРЕ «пункт + зона», а не по одному коду. Тот же пункт в другой
зоне — законная и частая запись (движок отказывает именно на паре), и пометить
его значило бы отговаривать аудитора от верного действия.

Ручного перечня (`manual_keyboard`) это не касается: там кнопка занята кодом и
формулировкой во всю ширину ряда (T217), пометка съела бы формулировку, и
разговор об этом отдельный.
"""

from __future__ import annotations

import pytest
from bot_harness import (
    AUDITOR_ID,
    CHAT_ID,
    candidate,
    feed,
    make_bot,
    photo_message,
    stub_classify,
    suggestion,
)
from bot_harness import callback_query as callback

from src.bot.app import build_dispatcher
from src.bot.config import BotSettings
from src.bot.texts import t
from src.domain import add_finding, start_inspection

pytestmark = pytest.mark.asyncio

SETTINGS = BotSettings(
    token="unused-in-tests",
    allowed_ids=frozenset({AUDITOR_ID}),
    mode="polling",
    auditor_names={},
)

#: Однозначная фраза синтетической карты кадров: строка «Печь» произнесена
#: целиком, колонка выбрана словом «грязная» → CLN05, единственный класс D1.
CLEAR = "печь грязная"


async def test_модель_предлагает_занятый_пункт_с_пометкой(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Сам дефект: запись есть, модель по второму кадру предлагает ту же пару."""
    start_inspection(CHAT_ID, "Белград 2", "planned", "ru")
    add_finding(CHAT_ID, "CLN05", "D1", "hot_kitchen", "Нагар на подине печи")
    stub_classify(monkeypatch, suggestion(candidate("CLN05", "D1", "hot_kitchen", "Печь в нагаре")))
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await feed(dp, bot, photo_message("frame-2", message_id=501))
    await feed(dp, bot, callback("rec:analyze:501"))

    assert t("record.candidate_taken", "ru", n=1) in session.last_text


async def test_пометка_ставится_по_паре_пункт_и_зона_а_не_по_коду(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Тот же пункт в другой зоне — законная запись, отговаривать от неё нельзя."""
    start_inspection(CHAT_ID, "Белград 2", "planned", "ru")
    add_finding(CHAT_ID, "CLN05", "D1", "hot_kitchen", "Нагар на подине печи")
    stub_classify(monkeypatch, suggestion(candidate("CLN05", "D1", "dining", "Нагар")))
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await feed(dp, bot, photo_message("frame-1", message_id=501))
    await feed(dp, bot, callback("rec:analyze:501"))

    assert t("record.candidate_taken", "ru", n=1) not in session.last_text


async def test_занятый_кандидат_остаётся_нажимаемым(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Кнопку не убираем: уход к модели задуман, и выбор остаётся за человеком.

    Нажатие положит кадр в уже существующую запись (#443, D243) — это законный
    путь «доснять фото», а не тупик. Пропади кнопка,
    поехали бы и номера остальных кандидатов.
    """
    start_inspection(CHAT_ID, "Белград 2", "planned", "ru")
    add_finding(CHAT_ID, "CLN05", "D1", "hot_kitchen", "Нагар на подине печи")
    stub_classify(
        monkeypatch,
        suggestion(
            candidate("CLN05", "D1", "hot_kitchen", "Нагар"),
            candidate("CLN02", "D1", "dishwashing", "Налёт на смесителе"),
        ),
    )
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await feed(dp, bot, photo_message("frame-1", message_id=501))
    await feed(dp, bot, callback("rec:analyze:501"))

    assert session.keyboard_data()[:2] == ["rec:pick:0", "rec:pick:1"]
    assert t("record.candidate_taken", "ru", n=1) in session.last_text


async def test_пометка_называет_номер_занявшей_записи(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Номер — то, чем аудитор находит запись и правит её; без него пометка тупик."""
    start_inspection(CHAT_ID, "Белград 2", "planned", "ru")
    add_finding(CHAT_ID, "CLN02", "D1", "dishwashing", "Налёт")
    add_finding(CHAT_ID, "CLN05", "D1", "hot_kitchen", "Нагар")
    stub_classify(monkeypatch, suggestion(candidate("CLN05", "D1", "hot_kitchen", "Нагар")))
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await feed(dp, bot, photo_message("frame-1", message_id=501))
    await feed(dp, bot, callback("rec:analyze:501"))

    assert t("record.candidate_taken", "ru", n=2) in session.last_text
    assert t("record.candidate_taken", "ru", n=1) not in session.last_text


async def test_пометка_переводится(domain_env: object, monkeypatch: pytest.MonkeyPatch) -> None:
    """Язык — параметр: русская пометка в английском перечне так же неверна."""
    start_inspection(CHAT_ID, "Belgrade 2", "planned", "en", ui_lang="en")
    add_finding(CHAT_ID, "CLN05", "D1", "hot_kitchen", "Soot")
    stub_classify(monkeypatch, suggestion(candidate("CLN05", "D1", "hot_kitchen", "Soot")))
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await feed(dp, bot, photo_message("frame-1", message_id=501))
    await feed(dp, bot, callback("rec:analyze:501"))

    assert t("record.candidate_taken", "en", n=1) in session.last_text
    assert t("record.candidate_taken", "ru", n=1) not in session.last_text
