"""#443 (D243, D247): кадр того же нарушения ложится в уже занятую запись.

Боевой случай: аудитор по одному присылал кадры соусов без маркировки в
холодильной камере, каждый со своей подписью. Первый стал записью, остальные
движок отклонил занятой парой «пункт + зона»: кадры не прикрепились, а в конце
проверки всплыли «без записи».

Проверяется здесь:

* кадр в занятую пару прикрепляется к занявшей записи — и сразу следом, и
  после других нарушений; второй записи не появляется, модель разбора не
  зовётся;
* текст записи сводит дешёвая модель: прежний текст + новые слова, на языке
  отчёта; сообщение называет запись словами и показывает новый текст;
* сбой модели кадр не роняет: кадр прикреплён, текст прежний, причина в логе;
* сообщение — показ записи: ответ на него словами адресует её;
* прикреплённый кадр не числится «без записи»;
* правка ответом (`correcting`) в занятую пару по-прежнему отказывает.
"""

from __future__ import annotations

from typing import Any

import pytest
from bot_harness import (
    AUDITOR_ID,
    CHAT_ID,
    bot_message,
    feed,
    make_bot,
    photo_message,
    stub_classify,
    stub_merge,
    suggestion,
    text_message,
)

from src import domain
from src.bot import sidecar
from src.bot.app import build_dispatcher
from src.bot.config import BotSettings
from src.bot.texts import t
from src.bot.view import zone_title
from src.recognize.errors import ModelUnavailable

pytestmark = pytest.mark.asyncio

SETTINGS = BotSettings(token="unused-in-tests", allowed_ids=frozenset({AUDITOR_ID}), mode="polling")

#: Прежний текст записи #1.
БЫЛО = "Нагар на подине печи"
#: Слова аудитора ко второму кадру: сверка ведёт их в ту же пару CLN05 + hot_kitchen.
СНОВА = "печь в нагаре, тепловой участок"
#: Что вернула подменённая модель.
СВЕДЕНО = "Нагар на подине и на ленте печи"


def начата(lang: str = "ru") -> None:
    domain.start_inspection(CHAT_ID, "Белград 2", "planned", lang, ui_lang=lang)
    domain.add_finding(CHAT_ID, "CLN05", "D1", "hot_kitchen", БЫЛО)


def записи() -> list[domain.Finding]:
    state = domain.get_state(CHAT_ID)
    return [] if state is None else list(state.findings)


def добавил(lang: str, *, count: int, text: str) -> str:
    return t(
        "record.merged",
        lang,
        item=domain.get_item("CLN05").question(lang),
        zone=zone_title("hot_kitchen", lang, chat_id=CHAT_ID),
        count=count,
        text=text,
    )


def номер_сообщения(session: Any, начало: str) -> int:
    номера = iter(session.sent_ids)
    for call in session.calls:
        name = type(call).__name__
        if name not in {"SendMessage", "SendPhoto", "SendDocument", "EditMessageText"}:
            continue
        message_id = next(номера)
        if name == "SendMessage" and str(getattr(call, "text", "")).startswith(начало):
            return message_id
    raise AssertionError(f"бот не отправил сообщения, начинающегося с «{начало}»")


async def test_кадр_в_занятую_пару_ложится_в_запись_и_текст_сводится(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Сам дефект: второй кадр о том же — не отказ, а фото в ту же запись."""
    начата()
    свести = stub_merge(monkeypatch, СВЕДЕНО)
    разбор = stub_classify(monkeypatch, suggestion())
    bot, session = make_bot()

    await feed(build_dispatcher(SETTINGS), bot, photo_message("frame-2", caption=СНОВА))

    assert [(f.n, f.code, f.zone) for f in записи()] == [(1, "CLN05", "hot_kitchen")], (
        "появилась вторая запись о том же нарушении"
    )
    assert записи()[0].photos == ["frame-2"], "кадр не прикрепился к занятой записи"
    assert записи()[0].text == СВЕДЕНО, "текст записи не сведён"
    assert свести == [(БЫЛО, СНОВА, "ru")], "модели ушло не то"
    assert добавил("ru", count=1, text=СВЕДЕНО) in session.texts
    assert not any(text.startswith("Не записал") for text in session.texts), "остался отказ"
    assert "#1" not in "\n".join(session.texts), "запись названа номером, а не словами"
    assert разбор == [], "после прикрепления материал зачем-то ушёл модели разбора"


async def test_кадр_ложится_в_запись_и_после_других_нарушений(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D247: «нарушения могут быть последовательны» — между кадрами была другая запись."""
    начата()
    domain.add_finding(CHAT_ID, "CLN02", "D1", "dishwashing", "Налёт на смесителе")
    stub_merge(monkeypatch, СВЕДЕНО)
    bot, _ = make_bot()

    await feed(build_dispatcher(SETTINGS), bot, photo_message("frame-3", caption=СНОВА))

    assert [(f.n, f.code, f.photos) for f in записи()] == [
        (1, "CLN05", ["frame-3"]),
        (2, "CLN02", []),
    ]


async def test_сбой_модели_не_роняет_кадр_и_оставляет_текст(
    domain_env: object, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Кадр прикрепляется всегда; не ответила модель — текст прежний, причина в логе."""
    начата()
    stub_merge(monkeypatch, ModelUnavailable("сеть легла"))
    bot, session = make_bot()

    with caplog.at_level("WARNING"):
        await feed(build_dispatcher(SETTINGS), bot, photo_message("frame-2", caption=СНОВА))

    assert записи()[0].photos == ["frame-2"], "сбой модели уронил прикрепление кадра"
    assert записи()[0].text == БЫЛО, "при сбое модели текст записи изменился"
    assert добавил("ru", count=1, text=БЫЛО) in session.texts
    assert "не сведён моделью" in caplog.text, "сбой модели не записан в лог"


async def test_сообщение_о_кадре_это_показ_записи(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ответ словами на «Добавил фото к записи …» правит её (карта показов)."""
    начата()
    stub_merge(monkeypatch, СВЕДЕНО)
    bot, session = make_bot()

    await feed(build_dispatcher(SETTINGS), bot, photo_message("frame-2", caption=СНОВА))

    assert sidecar.record_of(CHAT_ID, номер_сообщения(session, "📎 Добавил фото")) == 1


async def test_прикреплённый_кадр_не_числится_без_записи(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Раньше такой кадр показывался в конце проверки «без записи» с исходом «отклонён»."""
    начата()
    bot, _ = make_bot()

    await feed(build_dispatcher(SETTINGS), bot, photo_message("frame-2", caption=СНОВА))

    used = {photo for finding in записи() for photo in finding.photos}
    assert sidecar.unclaimed(CHAT_ID, used) == ()
    assert all(
        frame.outcome != sidecar.OUTCOME_REFUSED for frame in sidecar.read(CHAT_ID).frames
    ), "кадру проставлен исход «движок отклонил»"


async def test_английский_интерфейс_английское_сообщение(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Язык — параметр: сообщение на языке интерфейса, модель — на языке отчёта."""
    начата("en")
    свести = stub_merge(monkeypatch, "Carbon on the oven deck and belt")
    bot, session = make_bot()

    await feed(build_dispatcher(SETTINGS), bot, photo_message("frame-2", caption=СНОВА))

    assert добавил("en", count=1, text="Carbon on the oven deck and belt") in session.texts
    assert свести[0][2] == "en"


async def test_правка_в_занятую_пару_по_прежнему_отказывает(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`correcting`: аудитор правит СВОЮ запись на чужую пару — сливать нельзя."""
    начата()
    domain.add_finding(CHAT_ID, "CLN02", "D1", "dishwashing", "Налёт на смесителе")
    sidecar.remember_record(CHAT_ID, 900, 2)
    свести = stub_merge(monkeypatch, СВЕДЕНО)
    bot, session = make_bot()

    await feed(build_dispatcher(SETTINGS), bot, text_message(СНОВА, reply_to=bot_message(900)))

    assert [(f.n, f.code, f.zone, f.text, f.photos) for f in записи()] == [
        (1, "CLN05", "hot_kitchen", БЫЛО, []),
        (2, "CLN02", "dishwashing", "Налёт на смесителе", []),
    ], "правка слилась с занятой записью"
    assert any(text.startswith("Не поправил") for text in session.texts), "отказа правки нет"
    assert свести == [], "правка позвала модель сведения"
