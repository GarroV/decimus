"""Материал без записи не пропадает молча: у кадра — причина, у слов — строка (T269, #219).

Дефект живого прогона: аудитор сказал о находке, система не нашла пункт,
аудитор пошёл дальше — и не осталось ни записи, ни следа. Кадр при завершении
показывался (T068, T138), но одной и той же фразой на все случаи сразу:
«этот кадр остался без записи». Три разных случая — не нашлось пункта, аудитор
сам отказался, методика не держит пункт в этой зоне — чинятся по-разному, а
выглядели одинаково.

Вторая половина — накопитель (#228): управляющая компания обязана увидеть,
чего не хватило карте кадров. Здесь же стережётся и то, ЧЕГО в накопителе
быть не должно: одна формулировка не имеет права лечь в него дважды (читается
он счётом «встретилось N раз»), а занятая пара «пункт + зона» — не пробел
карты, а обычный повтор обхода.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from bot_harness import (
    AUDITOR_ID,
    CHAT_ID,
    build_report,
    callback_query,
    feed,
    make_bot,
    photo_message,
    stub_classify,
    suggestion,
    text_message,
)

from src.bot.app import build_dispatcher
from src.bot.config import BotSettings
from src.bot.texts import t
from src.domain import add_finding, read_uncovered, start_inspection
from src.domain.config import check_environment
from src.domain.engine import chat_dir

pytestmark = pytest.mark.asyncio

SETTINGS = BotSettings(
    token="unused-in-tests",
    allowed_ids=frozenset({AUDITOR_ID}),
    mode="polling",
    auditor_names={},
)

#: Комментарий, на котором сверка с картой кадров молчит (колонка не названа
#: однозначно), и материал уходит модели — то есть туда, где стоит подмена.
СКАЗАНО = "печь, посмотри что тут"


def начата() -> None:
    start_inspection(CHAT_ID, "Белград 2", "planned", "ru", date="2026-09-16", auditor="Гарро")


def подписи_кадров(session: Any) -> list[str]:
    return [str(call.caption) for call in session.calls if type(call).__name__ == "SendPhoto"]


def файл_накопителя() -> dict[str, Any]:
    путь = chat_dir(CHAT_ID, check_environment()) / "uncovered.json"
    return dict(json.loads(путь.read_text(encoding="utf-8")))


async def test_кадр_без_найденного_пункта_называет_причину(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Главный случай #219: система не нашла ничего — и сказала об этом в конце."""
    начата()
    stub_classify(monkeypatch, suggestion())
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await feed(dp, bot, photo_message("frame-1", caption=СКАЗАНО))
    session.clear()
    await feed(dp, bot, text_message("/finish"))

    assert подписи_кадров(session) == [t("finish.unclaimed_nothing", "ru")]


async def test_отказ_аудитора_называется_своей_причиной(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """«Не записывать» — тоже ответ, и он не тот же, что «не нашлось»."""
    начата()
    stub_classify(monkeypatch, suggestion())
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await feed(dp, bot, photo_message("frame-1", caption=СКАЗАНО))
    await feed(dp, bot, callback_query("rec:skip"))
    session.clear()
    await feed(dp, bot, text_message("/finish"))

    assert подписи_кадров(session) == [t("finish.unclaimed_abandoned", "ru")]


async def test_формулировка_не_ложится_в_накопитель_дважды(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """«Не нашлось» — ещё не потеря: следом открывается ручной перечень.

    Строка накопителя заводится, когда путей к записи не осталось. Запиши её
    оба раза — и одна формулировка показалась бы управляющей компании двумя
    случаями, то есть счёт «встретилось N раз» соврал бы вдвое.
    """
    начата()
    stub_classify(monkeypatch, suggestion())
    bot, _ = make_bot()
    dp = build_dispatcher(SETTINGS)

    await feed(dp, bot, photo_message("frame-1", caption=СКАЗАНО))
    assert read_uncovered(chat_id=CHAT_ID) == (), "запись заведена до того, как судьба решена"

    await feed(dp, bot, callback_query("rec:skip"))

    (запись,) = read_uncovered(chat_id=CHAT_ID)
    assert запись.note == СКАЗАНО
    assert запись.outcome == "abandoned"


async def test_накопитель_уезжает_в_историю_при_сдаче_отчёта(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Собранное относится к ЭТОЙ проверке: следующая начинается с пустого накопителя.

    Иначе слова прошлой точки посчитались бы в этой — ровно та ошибка, ради
    которой накопитель и разделён на открытую часть и историю.
    """
    начата()
    stub_classify(monkeypatch, suggestion())
    add_finding(CHAT_ID, "CLN05", "D1", "hot_kitchen", "Нагар на подине печи")
    bot, _ = make_bot()
    dp = build_dispatcher(SETTINGS)

    await feed(dp, bot, photo_message("frame-1", caption=СКАЗАНО))
    await feed(dp, bot, callback_query("rec:skip"))
    assert файл_накопителя()["open"], "предпосылка теста: накопитель до сдачи не пуст"

    await build_report(dp, bot)

    накопитель = файл_накопителя()
    assert накопитель["open"] == [], "открытая часть обязана опустеть при сдаче"
    assert [строка["note"] for строка in накопитель["history"]] == [СКАЗАНО], (
        "перенесённая строка обязана найтись в истории, а не пропасть"
    )
