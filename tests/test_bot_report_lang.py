"""Страна проверки для списка языков отчёта (D415): точка справочника, затем город, затем ничего.

Без страны перечень — по умолчанию; недоступная база не мешает дойти до отчёта.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from conftest import TEST_DATA

from src.bot import report_lang
from src.db.directory import Unit
from src.db.errors import PushError
from src.domain import models
from src.domain import report_langs as langs


def _inspection(unit: str = "Tbilisi-1", city: str = "") -> models.Inspection:
    return models.Inspection(
        chat_id=1,
        unit=unit,
        kind="planned",
        date="2026-10-12",
        report_lang="ru",
        ui_lang="ru",
        speech_lang="ru",
        checklist_version="v1",
        tenant="hq",
        city=city,
    )


def _units(monkeypatch: pytest.MonkeyPatch, *units: Unit) -> None:
    monkeypatch.setattr(report_lang.directory, "list_units", lambda **_k: list(units))
    # Охват читается из базы, которой в этих тестах нет, — подставляем готовый.
    monkeypatch.setattr(report_lang, "reach_of", lambda tenant: tenant)


def test_country_comes_from_the_directory_unit(monkeypatch: pytest.MonkeyPatch) -> None:
    _units(monkeypatch, Unit(id="u1", name="Tbilisi-1", code=None, aliases=(), country="GE"))

    assert report_lang.inspection_country(_inspection()) == "GE"


def test_country_matches_a_synonym_and_ignores_case(monkeypatch: pytest.MonkeyPatch) -> None:
    _units(
        monkeypatch,
        Unit(id="u1", name="Batumi-1", code=None, aliases=("Батуми 1",), country="GE"),
    )

    assert report_lang.inspection_country(_inspection(unit="батуми 1")) == "GE"


def test_unit_without_country_falls_back_to_the_city(monkeypatch: pytest.MonkeyPatch) -> None:
    _units(monkeypatch, Unit(id="u1", name="Tbilisi-1", code=None, aliases=(), country=None))

    assert report_lang.inspection_country(_inspection(city="beograd")) == "RS"


def test_unreachable_directory_falls_back_to_the_city(monkeypatch: pytest.MonkeyPatch) -> None:
    def down(**_k: object) -> list[Unit]:
        raise PushError("база недоступна")

    monkeypatch.setattr(report_lang.directory, "list_units", down)

    assert report_lang.inspection_country(_inspection(city="tbilisi")) == "GE"
    assert report_lang.inspection_country(_inspection()) is None


def test_offered_languages_follow_the_country(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    data = tmp_path / "methodology"
    shutil.copytree(TEST_DATA, data)
    (data / langs.REPORT_LANGS_FILE).write_text(
        '{"default": ["ru", "en"], "countries": {"GE": ["en"]}}', encoding="utf-8"
    )
    monkeypatch.setenv("AUDIT_DATA_DIR", str(data))
    _units(monkeypatch, Unit(id="u1", name="Tbilisi-1", code=None, aliases=(), country="GE"))

    assert report_lang.langs_for_inspection(_inspection()) == ["en"]
    assert report_lang.langs_for_inspection(_inspection(unit="Nowhere-9")) == ["ru", "en"]
