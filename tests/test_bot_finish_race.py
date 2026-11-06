"""#1407: правка из другой вкладки между сверкой отпечатка и печатью не уходит в отчёт.

Раньше мини-апп сверял отпечаток проверки до замка, а печать ставила `deliver` —
позже. Запись, пришедшая в окно между ними, попадала в отчёт неподтверждённой.
Теперь отпечаток сверяется внутри печати, под замком заметок (`sidecar.mark_handed_over`).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from bot_harness import CHAT_ID, make_bot, text_message

from src.bot import sidecar
from src.bot.routers.finish import deliver
from src.bot.texts import t
from src.domain import add_finding, get_state, handed_over, start_inspection
from src.domain.revision import revision


def _начать() -> None:
    start_inspection(
        CHAT_ID, "Белград 2", "planned", "ru", date="2026-08-21", auditor="Владимир Гарро"
    )
    add_finding(CHAT_ID, code="CLN05", level="D1", zone="hot_kitchen", text="Нагар на подине печи")


def _правка_из_другой_вкладки(*_a: object, **_k: object) -> int:
    """Подмена автоперевода: он идёт между проверкой отпечатка и печатью."""
    add_finding(CHAT_ID, code="CLN06", level="D1", zone="hot_kitchen", text="Жир на вытяжке")
    return 0


@pytest.mark.asyncio
async def test_правка_между_сверкой_и_печатью_отчёт_не_собирает(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _начать()
    увиденное = revision(get_state(CHAT_ID))  # type: ignore[arg-type]
    monkeypatch.setattr("src.bot.routers.finish.translate_comments", _правка_из_другой_вкладки)
    bot, session = make_bot()

    await deliver(
        text_message("/finish").as_(bot),
        CHAT_ID,
        "ru",
        allow_missing=False,
        expected_revision=увиденное,
    )

    assert session.documents == [], "в отчёт ушла правка, которую аудитор не видел"
    assert not handed_over(CHAT_ID), "печать встала поверх неподтверждённой правки"
    assert sidecar.read(CHAT_ID).handed_over_findings == sidecar.NEVER_HANDED_OVER
    assert session.last_text == t("finish.changed_since_review", "ru")
    assert get_state(CHAT_ID).finished_at is None  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_без_правки_тот_же_вызов_отчёт_отдаёт(domain_env: Path) -> None:
    """Контроль: сверка не отказывает всем подряд — совпавший отпечаток пропускается."""
    _начать()
    увиденное = revision(get_state(CHAT_ID))  # type: ignore[arg-type]
    bot, session = make_bot()

    await deliver(
        text_message("/finish").as_(bot),
        CHAT_ID,
        "ru",
        allow_missing=False,
        expected_revision=увиденное,
    )

    assert len(session.documents) == 1
    assert handed_over(CHAT_ID)
