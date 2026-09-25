"""Журнал разбора проверки и копии кадров (#367, решение владельца D179).

Журнал нужен тому, кто разбирает боевой случай: что система увидела, что
предложила и что сделал человек. Поэтому главный тест здесь сквозной — через
настоящий диспетчер, от кадра с подписью до удалённой записи, — и проверяет он
ровно то, чего не хватило при разборе 24.09.2026: слова аудитора, ответ модели
и запись, которой больше нет в проверке.

Копии кадров живут 7 дней (D179). Срок проверяется отдельно: кадры несут лица
сотрудников, и копия, пережившая срок, — нарушение решения владельца, которое
никто не заметит, пока не спросит.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

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

from src.bot import frame_copies, journal, sidecar
from src.bot.app import build_dispatcher
from src.bot.config import BotSettings
from src.domain import start_inspection

SETTINGS = BotSettings(token="unused-in-tests", allowed_ids=frozenset({AUDITOR_ID}), mode="polling")


def events(chat_id: int = CHAT_ID) -> list[dict[str, object]]:
    path = journal.journal_path(chat_id)
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.mark.asyncio
async def test_journal_keeps_words_model_answer_and_dropped_record(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Кадр с подписью → ответ модели → запись → удаление: всё осталось в журнале."""
    start_inspection(CHAT_ID, "Белград 2", "planned", "ru")
    stub_classify(
        monkeypatch,
        suggestion(
            candidate("CLN05", "D1", "hot_kitchen", "Печь в нагаре"),
            question="Сколько продуктов выше нормы?",
        ),
    )
    bot, _ = make_bot()
    dp = build_dispatcher(SETTINGS)
    подпись = "печь, посмотри что тут, тепловой участок"

    await feed(dp, bot, photo_message("frame-1", caption=подпись, message_id=501))
    await feed(dp, bot, callback("rec:pick:0"))
    await feed(dp, bot, callback("edit:1:drop"))

    log = events()
    kinds = [e["event"] for e in log]
    for wanted in ("frames", "material", "model", "recorded", "dropped"):
        assert wanted in kinds, f"в журнале нет события {wanted}: {kinds}"
    material = next(e for e in log if e["event"] == "material")
    assert material["note"] == подпись, "слова аудитора не дожили до журнала"
    assert material["copies"] == [frame_copies.copy_name("frame-1")]
    model = next(e for e in log if e["event"] == "model")
    assert model["candidates"][0]["code"] == "CLN05"  # type: ignore[index]
    assert model["question"] == "Сколько продуктов выше нормы?"
    assert model["used_photo"] is True, "кадр с подписью уходит в модель (D181)"
    assert model["album_frames"] == 1
    recorded = next(e for e in log if e["event"] == "recorded")
    assert recorded["via"] == "suggestion"
    dropped = next(e for e in log if e["event"] == "dropped")
    assert dropped["before"]["code"] == "CLN05", "удалённая запись исчезла из журнала бесследно"  # type: ignore[index]


def test_new_inspection_closes_the_previous_journal(domain_env: object) -> None:
    """Новая проверка — чистый журнал, а прошлый остаётся лежать под своим именем."""
    start_inspection(CHAT_ID, "Белград 2", "planned", "ru")
    journal.note(CHAT_ID, "material", note="прошлая проверка")

    sidecar.reset(CHAT_ID)

    folder = journal.journal_path(CHAT_ID).parent
    closed = sorted(folder.glob(f"{journal.CLOSED_PREFIX}*.jsonl"))
    assert len(closed) == 1
    assert "прошлая проверка" in closed[0].read_text(encoding="utf-8")
    assert not journal.journal_path(CHAT_ID).exists()


def test_journal_failure_does_not_stop_the_inspection(
    domain_env: object, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Не записалась строка — это потеря для разбора, а не упавший хендлер. Но не молча."""

    def broken(chat_id: int) -> Path:
        raise OSError("диск занят")

    monkeypatch.setattr(journal, "journal_path", broken)

    journal.note(CHAT_ID, "material", note="слова")

    assert "не записалось" in caplog.text


def test_sweep_removes_only_copies_older_than_seven_days(tmp_path: Path) -> None:
    """Копия старше недели убирается, свежая остаётся (срок владельца, D179)."""
    folder = tmp_path / f"chat_{CHAT_ID}"
    folder.mkdir()
    old = folder / frame_copies.copy_name("old")
    fresh = folder / frame_copies.copy_name("fresh")
    old.write_bytes(b"x")
    fresh.write_bytes(b"x")
    now = time.time()
    eight_days = 8 * 24 * 60 * 60
    os.utime(old, (now - eight_days, now - eight_days))
    six_days = 6 * 24 * 60 * 60
    os.utime(fresh, (now - six_days, now - six_days))

    removed = frame_copies.sweep(tmp_path, now=now)

    assert removed == 1
    assert not old.exists(), "копия старше 7 дней осталась лежать"
    assert fresh.exists(), "свежая копия убрана раньше срока"


@pytest.mark.asyncio
async def test_frame_is_copied_when_frames_dir_is_set(
    domain_env: object, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Каталог копий задан — присланный кадр ложится туда под именем из журнала."""
    start_inspection(CHAT_ID, "Белград 2", "planned", "ru")
    monkeypatch.setenv(frame_copies.FRAMES_DIR_VAR, str(tmp_path))

    async def fake_fetch(bot: object, file_id: str) -> bytes:
        return b"jpeg-bytes"

    monkeypatch.setattr(frame_copies, "fetch_bytes", fake_fetch)
    bot, _ = make_bot()
    dp = build_dispatcher(SETTINGS)

    await feed(dp, bot, photo_message("frame-7", message_id=777))
    for task in list(frame_copies._running):
        await task

    copy = frame_copies.copy_path(tmp_path, CHAT_ID, "frame-7")
    assert copy.read_bytes() == b"jpeg-bytes"
