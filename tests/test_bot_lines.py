"""Бот ведёт себя как мини-апп: несколько нарушений — несколько строк (D718, D713).

Боевой случай 06.11.2026: аудитор прислала три кадра с «Столы, плинтуса, пол,
очень грязный холодный цех». Бот показал одно предложение с пятью кандидатами, а
«Записать №1» забирало разговор целиком — остальные дефекты записать было нельзя.

Что защищает этот файл:

**Комментарий с несколькими разными дефектами — по сообщению на дефект**, у
каждого свои кандидаты и своя кнопка. Запись одного не гасит остальные.

**Комментарий об одном дефекте остаётся одним сообщением.**

**Кадр без слов с несколькими вещами — по сообщению на вещь**, и ничего не
записывается без нажатия.

**«На кадрах видно ещё» — одно отдельное предложение на материал**, а не по
штуке на строку, и пункта строки оно не подменяет.

Деление комментария делает модель (`recognize.split`); тесты подменяют её
ответ, как остальные тесты бота подменяют разбор.
"""

from __future__ import annotations

from typing import Any

import pytest
from bot_harness import (
    CHAT_ID,
    Calls,
    candidate,
    feed,
    make_bot,
    photo_message,
    stub_classify,
    suggestion,
    text_message,
)
from bot_harness import callback_query as callback

from src.bot.app import build_dispatcher
from src.bot.config import BotSettings
from src.bot.keyboards import ANALYZE_PREFIX, PICK_PREFIX
from src.bot.texts import t
from src.domain import Finding, get_state, start_inspection
from src.recognize.errors import ModelUnavailable
from src.recognize.models import Suggestion

pytestmark = pytest.mark.asyncio

SETTINGS = BotSettings(token="unused-in-tests", mode="polling")

#: Слова боевого случая и то, как их делит модель: три разных дефекта.
TRIGGER = "Столы, плинтуса, пол, очень грязный холодный цех"
TRIGGER_PARTS = ("Столы очень грязный", "плинтуса очень грязный", "пол очень грязный")

#: Пункты разные: пара «пункт + зона» занимается один раз.
BY_WORDS = {
    TRIGGER_PARTS[0]: candidate("CLN05", "D1", "hot_kitchen", "столы"),
    TRIGGER_PARTS[1]: candidate("CLN06", "D1", "hot_kitchen", "плинтуса"),
    TRIGGER_PARTS[2]: candidate("PRD06", "D1", "hot_kitchen", "пол"),
}


def started() -> None:
    start_inspection(CHAT_ID, "Белград 2", "planned", "ru")


def findings() -> list[Finding]:
    state = get_state(CHAT_ID)
    return [] if state is None else list(state.findings)


def stub_split(monkeypatch: pytest.MonkeyPatch, parts: tuple[str, ...] | Exception) -> Calls:
    """Подменить деление комментария: что вернёт модель."""
    calls = Calls()

    def fake(words: str, **_: object) -> tuple[str, ...]:
        calls.append((words,))
        if isinstance(parts, Exception):
            raise parts
        return parts

    monkeypatch.setattr("src.bot.lines.split_violations", fake)
    return calls


def stub_by_words(monkeypatch: pytest.MonkeyPatch, also: tuple[Any, ...] = ()) -> Calls:
    """Разбор отвечает по словам строки: у каждой строки свой кандидат."""
    calls = Calls()

    def fake(note: str, photo: object = None, zone_hint: object = None, **kw: Any) -> Suggestion:
        calls.append((note, kw.get("photos")))
        found = BY_WORDS[note]
        return Suggestion(candidates=(found,), needs_human=False, also_seen=also)

    monkeypatch.setattr("src.bot.routers.record.classify", fake)
    return calls


def shown_with(session: Any, marker: str) -> list[int]:
    """Номера сообщений бота, в тексте которых есть `marker`, — по порядку показа."""
    return [i for i, x in zip(session.sent_ids, session.texts, strict=True) if marker in x]


async def send_album(dp: Any, bot: Any, *file_ids: str, caption: str) -> None:
    """Альбом с подписью, закрытый событием (кадр чужой группы), а не таймером."""
    await feed(dp, bot, photo_message(file_ids[0], media_group_id="album", caption=caption))
    for file_id in file_ids[1:]:
        await feed(dp, bot, photo_message(file_id, media_group_id="album"))
    await feed(dp, bot, photo_message("closing-frame"))


def dispatcher() -> Any:
    return build_dispatcher(SETTINGS, album_window=5.0)


async def test_три_дефекта_комментария_три_сообщения_и_запись_одного_не_гасит_другие(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Боевой случай: «Записать №1» под столами не должно убить плинтуса и пол."""
    started()
    stub_split(monkeypatch, TRIGGER_PARTS)
    classify_calls = stub_by_words(monkeypatch)
    bot, session = make_bot()
    dp = dispatcher()

    await send_album(dp, bot, "f1", "f2", "f3", caption=TRIGGER)

    header = [
        t("record.candidates_line", "ru", no=n, total=3, words=w, lines="").strip()
        for n, w in enumerate(TRIGGER_PARTS, start=1)
    ]
    ids = [shown_with(session, h)[0] for h in header]
    assert len(ids) == 3
    assert [c[0] for c in classify_calls] == list(TRIGGER_PARTS), "по разбору на строку"
    assert findings() == [], "без нажатия ничего не записано"

    await feed(dp, bot, callback(f"{PICK_PREFIX}0", message_id=ids[0]))
    await feed(dp, bot, callback(f"{PICK_PREFIX}0", message_id=ids[2]))
    assert session.last_text != t("record.stale", "ru"), "строка 3 погасла после записи строки 1"
    await feed(dp, bot, callback(f"{PICK_PREFIX}0", message_id=ids[1]))

    assert [f.code for f in findings()] == ["CLN05", "PRD06", "CLN06"]
    assert all(len(f.photos) == 3 for f in findings()), "кадры — в каждую запись ссылкой"


async def test_комментарий_об_одном_дефекте_остаётся_одним_сообщением(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """«Грязный пол у двери» модель не режет: никакого «Нарушение 1 из N»."""
    started()
    whole = "грязный пол у двери"
    stub_split(monkeypatch, (whole,))
    stub_classify(monkeypatch, suggestion(candidate("PRD06", "D1", "hot_kitchen", "пол у двери")))
    bot, session = make_bot()
    dp = dispatcher()

    await send_album(dp, bot, "g1", "g2", caption=whole)

    assert not any("Нарушение" in x for x in session.texts)
    assert not any("несколько разных нарушений" in x for x in session.texts)
    assert len(shown_with(session, "Что записать?")) == 1


async def test_слова_без_кадров_строки_тоже_живут_вместе(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Кадров нет — «те же кадры» строки не связывают, связывает номер материала."""
    started()
    stub_split(monkeypatch, TRIGGER_PARTS)
    stub_by_words(monkeypatch)
    bot, session = make_bot()
    dp = dispatcher()

    await feed(dp, bot, text_message(TRIGGER))
    await feed(dp, bot, photo_message("closing-frame"))  # закрывает материал событием

    ids = shown_with(session, "Нарушение")
    assert len(ids) == 3
    await feed(dp, bot, callback(f"{PICK_PREFIX}0", message_id=ids[0]))
    await feed(dp, bot, callback(f"{PICK_PREFIX}0", message_id=ids[1]))
    assert session.last_text != t("record.stale", "ru")


async def test_сбой_деления_не_останавливает_разбор(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Модель деления недоступна — комментарий идёт одной строкой, как до деления."""
    started()
    stub_split(monkeypatch, ModelUnavailable("нет ключа"))
    calls = stub_classify(monkeypatch, suggestion(candidate("PRD06", "D1", "hot_kitchen", "пол")))
    bot, session = make_bot()
    dp = dispatcher()

    await send_album(dp, bot, "h1", "h2", caption=TRIGGER)

    assert [c[0] for c in calls] == [TRIGGER]
    assert shown_with(session, "Что записать?")


async def test_на_кадрах_видно_ещё_одно_предложение_и_пункт_строки_не_подменяет(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Увиденное сверх слов — отдельный вопрос, один на материал, а не на каждую строку."""
    started()
    stub_split(monkeypatch, TRIGGER_PARTS[:2])
    seen = (candidate("PRD07", "D1", "hot_kitchen", "видно на кадре"),)
    stub_by_words(monkeypatch, also=seen)
    bot, session = make_bot()
    dp = dispatcher()

    await send_album(dp, bot, "k1", "k2", caption=TRIGGER)

    header = t("record.also_seen", "ru", lines="").strip()
    also_ids = shown_with(session, header)
    assert len(also_ids) == 1, "увиденное показано один раз, а не по разу на строку"
    lines = shown_with(session, "Нарушение")
    assert len(lines) == 2
    await feed(dp, bot, callback(f"{PICK_PREFIX}0", message_id=lines[0]))
    await feed(dp, bot, callback(f"{PICK_PREFIX}0", message_id=also_ids[0]))
    assert [f.code for f in findings()] == ["CLN05", "PRD07"]


async def test_кадр_без_слов_каждая_вещь_своё_сообщение_и_запись_только_по_нажатию(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Как «Пункт верный» в мини-аппе: увиденное подтверждается явно и по одному."""
    started()
    stub_classify(
        monkeypatch,
        suggestion(
            candidate("CLN05", "D1", "hot_kitchen", "стол грязный"),
            candidate("CLN06", "D1", "hot_kitchen", "плинтус грязный"),
        ),
    )
    bot, session = make_bot()
    dp = dispatcher()

    await feed(dp, bot, photo_message("frame-1", message_id=501))
    await feed(dp, bot, callback(f"{ANALYZE_PREFIX}501"))

    ids = shown_with(session, "вы об этом не говорили")
    assert len(ids) == 2
    assert findings() == [], "без нажатия ничего не записано"

    await feed(dp, bot, callback(f"{PICK_PREFIX}0", message_id=ids[0]))
    await feed(dp, bot, callback(f"{PICK_PREFIX}0", message_id=ids[1]))
    assert session.last_text != t("record.stale", "ru")
    assert [f.code for f in findings()] == ["CLN05", "CLN06"]
