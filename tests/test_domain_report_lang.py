"""Язык отчёта назначается в конце проверки (D415): `set_report_lang` и языки по странам.

Ядро: язык отчёта попадает в шапку, откуда его берёт сборка отчёта, и в
список для страны попадают только языки методики. Опечатка в справочнике
стран не должна ни оставить аудитора без выбора, ни предложить язык, на
котором отчёт не напечатать.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from src.domain import get_state, set_report_lang, start_inspection
from src.domain import report_langs as langs
from src.domain.errors import ConfigError, InspectionNotStarted, ValidationError

CHAT = 7101


def _file(tmp_path: Path, content: object) -> Path:
    (tmp_path / langs.REPORT_LANGS_FILE).write_text(json.dumps(content), encoding="utf-8")
    return tmp_path


# --- set_report_lang ---------------------------------------------------------


def test_report_lang_is_changed_in_the_header(domain_env: Path) -> None:
    start_inspection(CHAT, "Белград 2", "planned", "ru", speech_lang="ru")

    updated = set_report_lang(CHAT, "en")

    assert updated.report_lang == "en"
    stored = get_state(CHAT)
    assert stored is not None
    assert stored.report_lang == "en"
    assert stored.speech_lang == "ru", "язык чек-листа язык отчёта не трогает"


def test_unknown_report_lang_is_refused_and_changes_nothing(domain_env: Path) -> None:
    start_inspection(CHAT, "Белград 2", "planned", "ru")

    with pytest.raises(ValidationError):
        set_report_lang(CHAT, "sr")

    stored = get_state(CHAT)
    assert stored is not None
    assert stored.report_lang == "ru"


def test_report_lang_without_inspection_is_refused(domain_env: Path) -> None:
    with pytest.raises(InspectionNotStarted):
        set_report_lang(CHAT, "en")


# --- языки по странам --------------------------------------------------------


def test_no_file_gives_the_fallback_for_any_country(tmp_path: Path) -> None:
    assert langs.report_langs_for("RS", data_dir=tmp_path) == ["ru", "en"]
    assert langs.report_langs_for(None, data_dir=tmp_path) == ["ru", "en"]


def test_country_override_beats_the_default(tmp_path: Path) -> None:
    data = _file(tmp_path, {"default": ["ru", "en"], "countries": {"GE": ["en"]}})

    assert langs.report_langs_for("GE", data_dir=data) == ["en"]
    assert langs.report_langs_for("ge", data_dir=data) == ["en"], "регистр кода не важен"
    assert langs.report_langs_for("RS", data_dir=data) == ["ru", "en"]
    assert langs.report_langs_for(None, data_dir=data) == ["ru", "en"]


def test_country_order_is_kept(tmp_path: Path) -> None:
    data = _file(tmp_path, {"default": ["ru", "en"], "countries": {"RS": ["en", "ru"]}})

    assert langs.report_langs_for("RS", data_dir=data) == ["en", "ru"]


def test_unknown_languages_are_skipped_with_a_log_line(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    data = _file(tmp_path, {"default": ["ru", "en"], "countries": {"RS": ["sr", "en", "en"]}})

    with caplog.at_level(logging.WARNING):
        result = langs.report_langs_for("RS", data_dir=data)

    assert result == ["en"], "только язык методики, без повторов"
    assert "sr" in caplog.text


def test_country_with_only_unknown_languages_falls_back_to_the_default(tmp_path: Path) -> None:
    data = _file(tmp_path, {"default": ["en"], "countries": {"RS": ["sr"]}})

    assert langs.report_langs_for("RS", data_dir=data) == ["en"]


def test_empty_default_falls_back_to_all_platform_languages(tmp_path: Path) -> None:
    data = _file(tmp_path, {"default": ["sr"], "countries": {}})

    assert langs.report_langs_for(None, data_dir=data) == ["ru", "en"]


@pytest.mark.parametrize("content", ["[1, 2]", "{не json"])
def test_broken_file_is_a_config_error_not_a_silent_default(tmp_path: Path, content: str) -> None:
    (tmp_path / langs.REPORT_LANGS_FILE).write_text(content, encoding="utf-8")

    with pytest.raises(ConfigError):
        langs.report_langs_for("RS", data_dir=tmp_path)


def test_country_of_city() -> None:
    assert langs.country_of_city("Tbilisi") == "GE"
    assert langs.country_of_city("  beograd ") == "RS"
    assert langs.country_of_city("нет-такого") is None
    assert langs.country_of_city("") is None
