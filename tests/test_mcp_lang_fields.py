"""Поля перевода инструментов правки методики выводятся из `REPORT_LANGS` (#541)."""

from __future__ import annotations

import inspect

import pytest

from src.domain.models import BASE_LANG, REPORT_LANGS
from src.mcp import checklist_tools, lang_fields
from src.mcp.errors import ToolError


def test_сигнатура_показывает_поле_перевода_на_каждый_небазовый_язык() -> None:
    params = set(inspect.signature(checklist_tools.add_checklist_item).parameters)
    for lang in REPORT_LANGS:
        if lang != BASE_LANG:
            assert {f"process_{lang}", f"question_{lang}"} <= params
    zone = set(inspect.signature(checklist_tools.add_zone).parameters)
    assert {f"name_{lang}" for lang in REPORT_LANGS if lang != BASE_LANG} <= zone
    assert "texts" not in params


def test_cli_options_переводит_имя_поля_в_опцию_движка() -> None:
    texts = {f"question_{lang}": "q" for lang in REPORT_LANGS if lang != BASE_LANG}
    got = lang_fields.cli_options(texts, "process", "question")
    assert set(got) == {key.replace("_", "-") for key in texts}


def test_незнакомое_поле_перевода_отказ() -> None:
    with pytest.raises(ToolError, match="Неизвестные поля"):
        lang_fields.cli_options({"question_xx": "q"}, "process", "question")
