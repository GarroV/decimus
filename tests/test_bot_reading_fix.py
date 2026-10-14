"""Показание термометра: модель читает цифры неверно, аудитор исправляет (#836).

Случай выезда 14.10.2026: «он распознаёт фотку термометра и распознаёт
температуру неправильно… 6 градусов, а он пишет 26… и я не могла исправить».
Показание стоит отдельной строкой под предложением, под ним кнопка «Исправить
температуру»; верное число пересчитывает предложение, и оно, как любое,
ждёт подтверждения аудитора — ничего не пишется молча.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from bot_harness import (
    AUDITOR_ID,
    CHAT_ID,
    callback_query,
    candidate,
    feed,
    make_bot,
    photo_message,
    suggestion,
    text_message,
)

from src.bot.app import build_dispatcher
from src.bot.config import BotSettings
from src.bot.reading import parse_reading, reading_text
from src.bot.texts import t
from src.domain import get_state, start_inspection
from src.recognize.errors import ModelUnavailable
from src.recognize.models import Suggestion

SETTINGS = BotSettings(token="unused-in-tests", allowed_ids=frozenset({AUDITOR_ID}), mode="polling")

#: Слова без объекта карты: быстрый путь молчит, и материал уходит модели.
WORDS = "посмотри что тут"


def начата() -> None:
    start_inspection(CHAT_ID, "Белград 2", "planned", "ru", date="2026-08-21", auditor="Гарро")


def с_показанием(value: float | None, wording: str) -> Suggestion:
    return suggestion(replace(candidate("CLN03", "D1", "hot_kitchen", wording), reading_c=value))


def stub_model(
    monkeypatch: pytest.MonkeyPatch, *answers: Suggestion | Exception
) -> list[dict[str, Any]]:
    """Подмена разбора: ответы по очереди, вызовы — словарями аргументов."""
    calls: list[dict[str, Any]] = []
    queue = list(answers)

    def fake(note: str, photo: object = None, zone_hint: object = None, **kw: Any) -> Suggestion:
        calls.append({"note": note, "photo": photo, "zone_hint": zone_hint, **kw})
        answer = queue.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr("src.bot.routers.record.classify", fake)
    return calls


# --- разбор числа --------------------------------------------------------------


@pytest.mark.parametrize(
    ("текст", "ожидаемое"),
    [
        ("6", 6.0),
        (" 6 ", 6.0),
        ("-18", -18.0),
        ("−18", -18.0),
        ("4,5", 4.5),
        ("6 °C", 6.0),
        ("6°", 6.0),
        ("6 градусов", 6.0),
        ("+63", 63.0),
    ],
)
def test_число_разбирается(текст: str, ожидаемое: float) -> None:
    assert parse_reading(текст) == ожидаемое


@pytest.mark.parametrize("текст", ["", "много", "около 6", "6 или 7", "1000", "-100", "6.123", "°"])
def test_не_число_не_принимается(текст: str) -> None:
    assert parse_reading(текст) is None


def test_подпись_без_хвоста() -> None:
    assert (reading_text(6.0), reading_text(-18.0), reading_text(4.5)) == ("6", "-18", "4.5")


# --- разговор ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_показание_стоит_отдельной_строкой_с_кнопкой(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    начата()
    stub_model(monkeypatch, с_показанием(26.0, "Температура выше нормы"))
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await feed(dp, bot, photo_message("frame-1", caption=WORDS))

    assert t("record.reading_line", "ru", value="26") in session.last_text
    assert "rec:temp" in session.keyboard_data()
    assert t("btn.fix_reading", "ru") in session.keyboard_texts()


@pytest.mark.asyncio
async def test_без_показания_кнопки_нет(domain_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Негативный прогон: кадр не про термометр — ни строки, ни кнопки."""
    начата()
    stub_model(monkeypatch, с_показанием(None, "Нагар на поду"))
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await feed(dp, bot, photo_message("frame-1", caption=WORDS))

    assert "°C" not in session.last_text
    assert "rec:temp" not in session.keyboard_data()


@pytest.mark.asyncio
async def test_исправленная_температура_пересчитывает_предложение_и_ждёт_подтверждения(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    начата()
    calls = stub_model(
        monkeypatch,
        с_показанием(26.0, "Температура выше нормы"),
        с_показанием(6.0, "Температура в норме"),
    )
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)
    await feed(dp, bot, photo_message("frame-1", caption=WORDS))
    первое = session.sent_ids[-1]

    await feed(dp, bot, callback_query("rec:temp"))
    assert session.last_text == t("record.ask_reading", "ru")
    await feed(dp, bot, text_message("6"))

    assert len(calls) == 2
    assert calls[1]["reading_c"] == 6.0, "модель не получила исправленное число"
    assert "reading_c" not in calls[0], "первый разбор не должен нести исправление"
    assert calls[1]["note"] == WORDS, "слова аудитора потерялись при пересчёте"
    assert t("record.reading_line", "ru", value="6") in session.texts[-1]
    состояние = get_state(CHAT_ID)
    assert состояние is not None and not состояние.findings, "пересчёт записал без подтверждения"

    # Старые кнопки несли неверное число: нажатие под ними не записывает.
    await feed(dp, bot, callback_query("rec:pick:0", message_id=первое))
    состояние = get_state(CHAT_ID)
    assert состояние is not None and not состояние.findings, (
        "нарушение по неверному показанию записано"
    )
    assert session.last_text == t("record.stale", "ru")

    # Подтверждение нового предложения — и число ложится в запись.
    await feed(dp, bot, callback_query("rec:pick:0"))
    состояние = get_state(CHAT_ID)
    assert состояние is not None and len(состояние.findings) == 1
    assert состояние.findings[0].reading_c == 6.0
    assert состояние.findings[0].text == "Температура в норме"


@pytest.mark.asyncio
async def test_при_исправленной_температуре_нарушения_нет_запись_не_создаётся(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    начата()
    stub_model(monkeypatch, с_показанием(26.0, "Температура выше нормы"), suggestion())
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)
    await feed(dp, bot, photo_message("frame-1", caption=WORDS))

    await feed(dp, bot, callback_query("rec:temp"))
    await feed(dp, bot, text_message("6"))

    assert t("record.reading_no_violation", "ru", value="6") in session.texts
    состояние = get_state(CHAT_ID)
    assert состояние is not None and not состояние.findings


@pytest.mark.asyncio
async def test_не_число_спрашивается_снова_без_запроса_к_модели(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    начата()
    calls = stub_model(monkeypatch, с_показанием(26.0, "Температура выше нормы"))
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)
    await feed(dp, bot, photo_message("frame-1", caption=WORDS))

    await feed(dp, bot, callback_query("rec:temp"))
    await feed(dp, bot, text_message("не знаю"))

    assert session.last_text == t("record.reading_bad", "ru")
    assert len(calls) == 1, "модель позвали по не-числу"


@pytest.mark.asyncio
async def test_модель_недоступна_прежнее_предложение_остаётся(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    начата()
    stub_model(
        monkeypatch, с_показанием(26.0, "Температура выше нормы"), ModelUnavailable("нет сети")
    )
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)
    await feed(dp, bot, photo_message("frame-1", caption=WORDS))

    await feed(dp, bot, callback_query("rec:temp"))
    await feed(dp, bot, text_message("6"))
    assert session.last_text == t("record.unavailable", "ru")

    await feed(dp, bot, callback_query("rec:pick:0"))
    состояние = get_state(CHAT_ID)
    assert состояние is not None and len(состояние.findings) == 1, "прежнее предложение пропало"


@pytest.mark.asyncio
async def test_кадр_вместо_числа_снимает_вопрос_и_не_пропадает(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    начата()
    stub_model(
        monkeypatch,
        с_показанием(26.0, "Температура выше нормы"),
        с_показанием(None, "Нагар на поду"),
    )
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)
    await feed(dp, bot, photo_message("frame-1", caption=WORDS))
    await feed(dp, bot, callback_query("rec:temp"))

    await feed(dp, bot, photo_message("frame-2", caption=WORDS))

    assert t("record.reading_dropped", "ru") in session.texts
    assert "rec:pick:0" in session.keyboard_data(), "кадр после снятого вопроса не разобран"


def test_тексты_на_обоих_языках() -> None:
    for key in (
        "record.reading_line",
        "record.ask_reading",
        "record.reading_bad",
        "record.reading_no_violation",
        "record.reading_dropped",
        "btn.fix_reading",
    ):
        assert t(key, "en", value="6") != t(key, "ru", value="6"), key
