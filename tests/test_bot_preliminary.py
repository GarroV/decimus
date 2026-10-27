"""Напоминание под отчётом: он предварительный, проверку принимают в вебе (27.10.2026).

Проверяется то, что делает напоминание опасным или бесполезным: уходит ли оно
последним сообщением после отчёта и письма, ведёт ли ссылка на карточку именно
этой проверки, молчит ли про принятую проверку и про ту, которой в истории нет,
и не роняет ли сдачу стенд без адреса веба.

Состояние проверки в истории подменяется (`db.find_pushed`): сам запрос к базе
здесь не проверяется, а в `requires_db`-наборе он требует живой Postgres.
Соавторов в модели проверки нет (одна проверка — один чат и один аудитор), и
отдельного адресата тест не проверяет по той же причине.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from bot_harness import (
    CHAT_ID,
    RecordingSession,
    build_report,
    candidate,
    feed,
    make_bot,
    photo_message,
    stub_classify,
    suggestion,
    text_message,
)
from bot_harness import callback_query as callback

from src import db
from src.bot.app import build_dispatcher
from src.bot.config import BotSettings
from src.bot.preliminary import card_url
from src.bot.texts import t
from src.db.pushed import PushedInspection
from src.domain import start_inspection

pytestmark = pytest.mark.asyncio

SETTINGS = BotSettings(token="unused-in-tests", mode="polling")
INSPECTION_ID = "0b7f6a52-1d3c-4c1e-9d35-6a1f6f0f2a11"
WEB = "https://decimus.example"


@pytest.fixture(autouse=True)
def _чистое_окружение(monkeypatch: pytest.MonkeyPatch) -> None:
    """Адреса веба берутся только из теста: чужой `.env` ссылку не подменяет."""
    monkeypatch.delenv("ADMIN_PUBLIC_URL", raising=False)
    monkeypatch.delenv("BOT_WALK_URL", raising=False)


def начата(ui_lang: str = "ru") -> None:
    start_inspection(
        CHAT_ID,
        "Белград 2",
        "planned",
        "ru",
        date="2026-08-21",
        auditor="Владимир Гарро",
        ui_lang=ui_lang,
    )


def в_истории(monkeypatch: pytest.MonkeyPatch, *, ждёт_приёмки: bool) -> None:
    monkeypatch.setattr(
        db,
        "find_pushed",
        lambda chat_id: PushedInspection(id=INSPECTION_ID, awaiting_acceptance=ждёт_приёмки),
        raising=False,
    )


async def отчёт_через_бота(
    monkeypatch: pytest.MonkeyPatch, ui_lang: str = "ru"
) -> RecordingSession:
    начата(ui_lang)
    stub_classify(monkeypatch, suggestion(candidate("CLN05", "D1", "hot_kitchen")))
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)
    await feed(dp, bot, photo_message("frame-1", caption="нагар на подине печи"))
    await feed(dp, bot, callback("rec:pick:0"))
    await build_report(dp, bot)
    return session


# --- сдача -------------------------------------------------------------------


async def test_после_отчёта_и_письма_уходит_напоминание_со_ссылкой_на_карточку(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ADMIN_PUBLIC_URL", WEB)
    в_истории(monkeypatch, ждёт_приёмки=True)

    session = await отчёт_через_бота(monkeypatch)

    assert session.documents, "аудитору не отдали отчёт — напоминать не о чем"
    assert session.last_text == t(
        "finish.preliminary", "ru", url=f"{WEB}/inspections/{INSPECTION_ID}"
    )
    assert any(text.startswith("Письмо партнёру") for text in session.texts[:-1]), (
        "напоминание ушло раньше письма партнёру"
    )


async def test_напоминание_на_языке_интерфейса_аудитора(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ADMIN_PUBLIC_URL", WEB)
    в_истории(monkeypatch, ждёт_приёмки=True)

    session = await отчёт_через_бота(monkeypatch, ui_lang="en")

    assert session.last_text.startswith("This is a preliminary report."), session.last_text
    assert session.last_text.endswith(f"{WEB}/inspections/{INSPECTION_ID}")


async def test_принятой_проверке_не_напоминают(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ADMIN_PUBLIC_URL", WEB)
    в_истории(monkeypatch, ждёт_приёмки=False)

    session = await отчёт_через_бота(monkeypatch)

    assert session.documents
    assert not [x for x in session.texts if "предварительный отчёт" in x]


async def test_проверке_которой_нет_в_истории_не_напоминают(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ADMIN_PUBLIC_URL", WEB)
    monkeypatch.setattr(db, "find_pushed", lambda chat_id: None, raising=False)

    session = await отчёт_через_бота(monkeypatch)

    assert not [x for x in session.texts if "предварительный отчёт" in x]


async def test_без_базы_сдача_идёт_и_напоминания_нет(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`DATABASE_URL` не задан: слива и статуса нет, сообщений о них тоже."""
    session = await отчёт_через_бота(monkeypatch)

    assert session.documents
    assert "Письмо партнёру" in session.last_text


async def test_без_адреса_веба_напоминание_уходит_без_ссылки(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    в_истории(monkeypatch, ждёт_приёмки=True)

    session = await отчёт_через_бота(monkeypatch)

    assert session.last_text == t("finish.preliminary_nolink", "ru")


async def test_адрес_веба_берётся_от_адреса_мини_аппа_если_публичного_нет(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BOT_WALK_URL", f"{WEB}/tg/walk")

    assert card_url(INSPECTION_ID) == f"{WEB}/inspections/{INSPECTION_ID}"


async def test_публичный_адрес_главнее_адреса_мини_аппа(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADMIN_PUBLIC_URL", f"{WEB}/")
    monkeypatch.setenv("BOT_WALK_URL", "https://other.example/tg/walk")

    assert card_url(INSPECTION_ID) == f"{WEB}/inspections/{INSPECTION_ID}"


# --- повторная отправка ------------------------------------------------------


async def test_повторная_отправка_напоминает_пока_проверку_не_приняли(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ADMIN_PUBLIC_URL", WEB)
    в_истории(monkeypatch, ждёт_приёмки=True)
    начата()
    bot, session = make_bot()

    await feed(build_dispatcher(SETTINGS), bot, text_message("/resend"))

    assert session.documents, "отчёт при повторной отправке не собрался"
    assert session.last_text == t(
        "finish.preliminary", "ru", url=f"{WEB}/inspections/{INSPECTION_ID}"
    )


async def test_повторная_отправка_молчит_про_принятую_проверку(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ADMIN_PUBLIC_URL", WEB)
    в_истории(monkeypatch, ждёт_приёмки=False)
    начата()
    bot, session = make_bot()

    await feed(build_dispatcher(SETTINGS), bot, text_message("/resend"))

    assert session.documents
    assert not [x for x in session.texts if "предварительный отчёт" in x]
