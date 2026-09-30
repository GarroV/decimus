"""T127: отказ движка — сырьё, а не сообщение (задача #102).

Так это выглядело до задачи, дословно из прогона сверки:

    Не записал: CLN05 в зоне hot_kitchen уже зафиксировано — запись #1.
    Доснимите фото (audit.py photo 1 --add ...) или поправьте её
    (audit.py edit --n 1 ...)

Человеку с телефоном на точке предлагают запустить командную строку, зона
названа кодом, а текст всегда русский — даже если весь остальной интерфейс у
него английский. Случай при этом частый: тот же пункт в той же зоне аудитор
снимает дважды за обход.

Проверяется здесь то, что бот говорит своими словами: командной строки и кода
зоны в чате нет, пункт и зона названы по-человечески, а «поправить» делается
кнопками той записи, которая пару заняла. С #443 кадр в занятую пару при
фиксации ложится в ту запись (`tests/test_bot_merge_frames.py`), и отказ
занятой пары остался у правки.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from bot_harness import AUDITOR_ID, CHAT_ID, feed, make_bot, photo_message
from bot_harness import callback_query as callback

from src import domain
from src.bot.app import build_dispatcher
from src.bot.config import BotSettings
from src.bot.texts import t
from src.bot.view import zone_title

pytestmark = [pytest.mark.asyncio]

SETTINGS = BotSettings(token="unused-in-tests", allowed_ids=frozenset({AUDITOR_ID}), mode="polling")


def кнопки_под(session: Any, начало: str) -> list[str]:
    """Кнопки того самого сообщения, а не последнего с клавиатурой.

    Последним оно не бывает: после отказа материал уходит дальше и рисует свои
    кнопки поверх (T121). Смотреть на хвост переписки значило бы проверять не
    отказ, а то, что случилось после него.
    """
    for call in session.calls:
        if type(call).__name__ != "SendMessage":
            continue
        if not str(getattr(call, "text", "")).startswith(начало):
            continue
        markup = getattr(call, "reply_markup", None)
        rows = getattr(markup, "inline_keyboard", None) or []
        return [b.callback_data or "" for row in rows for b in row]
    return []


def начата(lang: str = "ru") -> None:
    domain.start_inspection(
        CHAT_ID, "Белград 2", "planned", lang, ui_lang=lang, date="2026-08-21", auditor="Гарро"
    )


def занять_пару() -> None:
    """Пара «пункт + зона» занята — то, что случается дважды за обход."""
    domain.add_finding(CHAT_ID, "CLN05", "D1", "hot_kitchen", "нагар на подине печи")


async def повторить_ту_же_фиксацию(lang: str = "ru") -> object:
    """Тот же пункт в той же зоне ещё раз — быстрым путём, как на точке."""
    начата(lang)
    занять_пару()
    bot, session = make_bot()
    await feed(
        build_dispatcher(SETTINGS),
        bot,
        photo_message("frame-2", caption="печь в нагаре, тепловой участок"),
    )
    return session


async def test_отказ_не_зовёт_аудитора_в_командную_строку(domain_env: Path) -> None:
    """Главное в задаче: человеку с телефоном не предлагают запустить `audit.py`."""
    session = await повторить_ту_же_фиксацию()

    сказанное = "\n".join(session.texts)
    assert "audit.py" not in сказанное, "аудитору предложили командную строку"
    assert "--add" not in сказанное and "--n" not in сказанное


# Кадр в занятую пару при ФИКСАЦИИ отказом больше не становится (#443, D243,
# D247): он ложится в занявшую запись. Это поведение — в
# `tests/test_bot_merge_frames.py`; здесь остаётся отказ правки.


# --- то же самое при правке записи ------------------------------------------


async def test_правка_в_занятую_зону_отвечает_по_человечески(domain_env: Path) -> None:
    """Смена зоны — самый частый способ упереться в занятую пару при правке.

    Пункт взят CLN06, а не CLN05 из `занять_пару()`: методика держит CLN05
    только за `hot_kitchen`, а тесту нужна вторая запись того же пункта в
    ДРУГОЙ допустимой зоне (T271 отклоняет пару, которой методика не даёт).
    CLN06 держит и `hot_kitchen`, и `dining`.
    """
    начата()
    domain.add_finding(CHAT_ID, "CLN06", "D1", "hot_kitchen", "нагар на подине печи")
    domain.add_finding(CHAT_ID, "CLN06", "D1", "dining", "нагар и здесь")
    bot, session = make_bot()

    await feed(build_dispatcher(SETTINGS), bot, callback("ez:2:hot_kitchen"))

    assert session.last_text == t(
        "edit.duplicate",
        "ru",
        n=1,
        item=domain.get_item("CLN06").question("ru"),
        zone=zone_title("hot_kitchen", "ru", chat_id=CHAT_ID),
    )
    assert "audit.py" not in session.last_text
    assert кнопки_под(session, "Не поправил") == [
        "edit:1:zone",
        "edit:1:level",
        "edit:1:text",
        "edit:1:repeat",
        "edit:1:drop",
    ]


async def test_прочий_отказ_правки_тоже_не_показывает_кишки(domain_env: Path) -> None:
    """Класс, не разрешённый пункту: запись цела, а сообщение — человеческое."""
    начата()
    занять_пару()
    bot, session = make_bot()

    await feed(build_dispatcher(SETTINGS), bot, callback("el:1:D3"))

    assert session.last_text == t(
        "edit.failed",
        "ru",
        n=1,
        item=domain.get_item("CLN05").question("ru"),
        zone=zone_title("hot_kitchen", "ru", chat_id=CHAT_ID),
    )
    проверка = domain.get_state(CHAT_ID)
    assert проверка is not None
    запись = проверка.finding(1)
    assert запись is not None and запись.level == "D1", "отказ движка испортил запись"
