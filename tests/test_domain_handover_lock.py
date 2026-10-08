"""Сдача и запись мини-аппа идут под одним замком (D080, D312).

Мини-апп проверяет «не сдана» и пишет внутри `domain.while_open`, а бот ставит
признак сдачи под замком своих заметок. Если это разные замки, сдача
проскакивает между проверкой и записью, и запись ложится в уже отданный отчёт.
Здесь доказывается, что замок один: пока запись идёт, бот сдать не может.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.bot import sidecar
from src.bot.errors import BotNotesError
from src.domain import HandedOverError, handed_over, start_inspection, while_open
from src.domain import state as domain_state
from src.domain.handover import HANDED_OVER_KEY, NOTES_FILE_NAME

ЧАТ = 7001


def test_пока_идёт_запись_бот_не_сдаёт(domain_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    start_inspection(ЧАТ, unit="Белград-1", kind="planned", report_lang="ru", ui_lang="ru")
    monkeypatch.setattr(domain_state, "LOCK_TIMEOUT_SEC", 0.2)

    with while_open(ЧАТ), pytest.raises(BotNotesError):
        sidecar.mark_handed_over(ЧАТ, 0)

    assert handed_over(ЧАТ) is False, "сдача прошла сквозь замок записи"
    sidecar.mark_handed_over(ЧАТ, 0)
    assert handed_over(ЧАТ) is True, "после записи сдача обязана пройти"


def test_сданная_проверка_не_открывается_на_запись(domain_env: Path) -> None:
    start_inspection(ЧАТ, unit="Белград-1", kind="planned", report_lang="ru", ui_lang="ru")
    заметки = domain_env / f"chat_{ЧАТ}" / NOTES_FILE_NAME
    заметки.write_text(json.dumps({HANDED_OVER_KEY: 3}), encoding="utf-8")
    записано = []

    with pytest.raises(HandedOverError), while_open(ЧАТ):
        записано.append("запись")

    assert записано == []
