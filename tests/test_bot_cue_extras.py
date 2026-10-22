"""Пункты словаря подсказок, которых модель не назвала, — и в боте (#1112, D597).

Модель задаёт вопрос и называет один пункт, а словарь управляющей компании
связывает слова аудитора ещё и с другим. В мини-приложении такой пункт уже
стоит нижней карточкой; в боте он пропадал, и аудитор выбирал соседний,
неверный. Здесь стережётся, что бот показывает его кандидатом ниже
предложенных моделью, с пометкой, и что нажатие записывает именно его.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from bot_harness import (
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
from src.bot.keyboards import PICK_PREFIX
from src.bot.texts import t
from src.domain import get_state, start_inspection
from src.recognize.classify import CUE_REASON
from src.recognize.models import UNKNOWN_ZONE, Candidate

pytestmark = pytest.mark.asyncio

SETTINGS = BotSettings(token="unused-in-tests", mode="polling", auditor_names={})

#: Пункт словаря — без зоны и формулировки, как его дописывает `with_cue_extras`.
#: CLN05 в синтетической методике держится за одну зону, и бот выводит её сам.
CUE = Candidate(
    code="CLN05", level="D1", zone=UNKNOWN_ZONE, wording="", confidence=0.0, reason=CUE_REASON
)


async def _show(dp: object, bot: object, monkeypatch: pytest.MonkeyPatch, *, cue: bool) -> None:
    ответ = suggestion(candidate("CLN06", "D1", "hot_kitchen", "по модели"), question="Что именно?")
    stub_classify(monkeypatch, replace(ответ, cue_extras=(CUE,) if cue else ()))
    await feed(dp, bot, photo_message("frame-1", message_id=501))
    await feed(dp, bot, callback("rec:analyze:501"))


async def test_пункт_словаря_показан_ниже_модели_с_пометкой(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    start_inspection(CHAT_ID, "Белград 2", "planned", "ru")
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    # Act
    await _show(dp, bot, monkeypatch, cue=True)

    # Assert
    пометка = t("record.candidate_cue", "ru").strip()
    перечень = next(text for text in session.texts if пометка in text)
    assert перечень.index("по модели") < перечень.index(пометка), "пункт словаря выше модельного"
    assert len(session.keyboard_texts()) >= 2, "кнопки под пунктом словаря нет"


async def test_без_пункта_словаря_пометки_нет(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    start_inspection(CHAT_ID, "Белград 2", "planned", "ru")
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    # Act
    await _show(dp, bot, monkeypatch, cue=False)

    # Assert
    пометка = t("record.candidate_cue", "ru").strip()
    assert not any(пометка in text for text in session.texts)


async def test_нажатие_на_пункт_словаря_записывает_его(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    start_inspection(CHAT_ID, "Белград 2", "planned", "ru")
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)
    await _show(dp, bot, monkeypatch, cue=True)

    # Act
    await feed(dp, bot, callback(f"{PICK_PREFIX}1", message_id=session.sent_ids[-1]))

    # Assert
    state = get_state(CHAT_ID)
    assert state is not None
    assert [(f.code, f.zone) for f in state.findings] == [("CLN05", "hot_kitchen")]
