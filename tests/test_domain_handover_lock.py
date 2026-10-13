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
from src.domain import (
    HandedOverError,
    add_finding,
    drop_finding,
    edit_finding,
    handed_over,
    set_info,
    set_report_lang,
    start_inspection,
    sync_checklist_version,
    while_open,
)
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


def _сдать(domain_env: Path) -> None:
    заметки = domain_env / f"chat_{ЧАТ}" / NOTES_FILE_NAME
    заметки.write_text(json.dumps({HANDED_OVER_KEY: 1}), encoding="utf-8")


@pytest.mark.parametrize(
    "изменение",
    [
        pytest.param(
            lambda: add_finding(ЧАТ, code="CLN05", level="D1", zone="hot_kitchen", text="x"),
            id="add_finding",
        ),
        pytest.param(lambda: edit_finding(ЧАТ, 1, text="y"), id="edit_finding"),
        pytest.param(lambda: drop_finding(ЧАТ, 1), id="drop_finding"),
        pytest.param(lambda: set_info(ЧАТ, "INF06", "ответ"), id="set_info"),
        pytest.param(lambda: set_report_lang(ЧАТ, "en"), id="set_report_lang"),
        pytest.param(lambda: sync_checklist_version(ЧАТ), id="sync_checklist_version"),
    ],
)
def test_домен_сам_отказывает_в_сданную_проверку(domain_env: Path, изменение) -> None:  # type: ignore[no-untyped-def]
    """F-098/F-114: страж стоит внутри изменяющих функций, а не только в роутерах."""
    start_inspection(ЧАТ, unit="Белград-1", kind="planned", report_lang="ru", ui_lang="ru")
    add_finding(ЧАТ, code="CLN05", level="D1", zone="hot_kitchen", text="до сдачи")
    файл = domain_env / f"chat_{ЧАТ}" / "inspection.json"
    _сдать(domain_env)
    до = файл.read_bytes()

    with pytest.raises(HandedOverError):
        изменение()

    assert файл.read_bytes() == до, "сданная проверка изменилась"
