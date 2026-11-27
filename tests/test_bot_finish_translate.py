"""Автоперевод комментариев при сборке отчёта (D443): `bot.finish_translate`.

Перевод — единственное, что подменяется (`translate_text` ходит в модель); запись
и чтение проверки — настоящие, под синтетической методикой.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src import domain
from src.bot import finish_translate
from src.db.errors import DbError
from src.domain.engine import state_file
from src.domain.state import settings_for
from src.recognize.errors import ModelUnavailable
from src.report import localized, snapshot_text

CHAT = 7001


@pytest.fixture
def проверка(domain_env: Path) -> domain.Inspection:
    """Чек-лист на русском, отчёт — на английском; два нарушения и рекомендация."""
    domain.start_inspection(
        CHAT, unit="Белград-1", kind="planned", report_lang="ru", ui_lang="ru", speech_lang="ru"
    )
    domain.add_finding(CHAT, "CLN05", "D1", "hot_kitchen", "Нагар", comment="Грязная печь")
    domain.add_finding(CHAT, "CLN06", "D1", "hot_kitchen", "Грязь", comment="")
    domain.add_finding(CHAT, "CLN02", "R", "dishwashing", "Мыть печь каждый день")
    return domain.set_report_lang(CHAT, "en")


def _режим(monkeypatch: pytest.MonkeyPatch, режим: str | None) -> None:
    monkeypatch.setattr(finish_translate.translate_modes, "chosen_translate_mode", lambda _: режим)


def _перевод(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    вызовы: list[tuple[str, str]] = []

    def перевести(texts: list[str], *, lang: str) -> list[str]:
        вызовы.extend((text, lang) for text in texts)
        return [f"[{lang}] {text}" for text in texts]

    monkeypatch.setattr(localized, "translate_texts", перевести)
    return вызовы


def test_автоматически_переводит_комментарий_и_рекомендацию(
    проверка: domain.Inspection, monkeypatch: pytest.MonkeyPatch
) -> None:
    _режим(monkeypatch, "auto")
    вызовы = _перевод(monkeypatch)

    original = state_file(CHAT, settings_for(CHAT)).read_bytes()
    сбоев = finish_translate.translate_comments(CHAT, проверка)
    assert state_file(CHAT, settings_for(CHAT)).read_bytes() == original

    после = domain.get_state(CHAT)
    assert после is not None
    assert сбоев == 0
    assert после == проверка
    rendered, _ = snapshot_text.render_state(CHAT, settings_for(CHAT))
    assert rendered["findings"][0]["comment"] == "[en] Грязная печь"
    assert rendered["findings"][2]["evidence"] == "[en] Мыть печь каждый день"
    assert len(вызовы) == 4
    assert finish_translate.translate_comments(CHAT, проверка) == 0
    assert len(вызовы) == 4


@pytest.mark.parametrize("режим", [None, "button", "мусор"])
def test_по_кнопке_и_без_выбора_ничего_не_переводится(
    проверка: domain.Inspection, monkeypatch: pytest.MonkeyPatch, режим: str | None
) -> None:
    _режим(monkeypatch, режим)
    вызовы = _перевод(monkeypatch)

    assert finish_translate.translate_comments(CHAT, проверка) == 0
    assert вызовы == []


def test_язык_отчёта_равен_языку_чек_листа_переводить_нечего(
    проверка: domain.Inspection, monkeypatch: pytest.MonkeyPatch
) -> None:
    _режим(monkeypatch, "auto")
    вызовы = _перевод(monkeypatch)
    тот_же = domain.set_report_lang(CHAT, "ru")

    assert finish_translate.translate_comments(CHAT, тот_же) == 0
    assert вызовы == []


def test_база_молчит_это_режим_по_кнопке_а_не_ошибка(
    проверка: domain.Inspection, monkeypatch: pytest.MonkeyPatch
) -> None:
    def молчит(_: int) -> None:
        raise DbError("нет базы")

    monkeypatch.setattr(finish_translate.translate_modes, "chosen_translate_mode", молчит)
    вызовы = _перевод(monkeypatch)

    assert finish_translate.translate_comments(CHAT, проверка) == 0
    assert вызовы == []


def test_модель_недоступна_запись_остаётся_как_написана_и_сбой_посчитан(
    проверка: domain.Inspection, monkeypatch: pytest.MonkeyPatch
) -> None:
    _режим(monkeypatch, "auto")

    def падает(text: str, *, lang: str) -> str:
        raise ModelUnavailable("нет сети")

    monkeypatch.setattr(localized, "translate_texts", падает)

    сбоев = finish_translate.translate_comments(CHAT, проверка)

    после = domain.get_state(CHAT)
    assert после is not None
    assert сбоев == 4
    assert после.findings[0].comment == "Грязная печь"
    assert после.findings[2].text == "Мыть печь каждый день"


def test_слишком_длинный_перевод_не_записывается(
    проверка: domain.Inspection, monkeypatch: pytest.MonkeyPatch
) -> None:
    _режим(monkeypatch, "auto")
    monkeypatch.setattr(
        localized,
        "translate_texts",
        lambda texts, *, lang: ["x" * (snapshot_text.MAX_TEXT + 1) for text in texts],
    )

    assert finish_translate.translate_comments(CHAT, проверка) == 4
    после = domain.get_state(CHAT)
    assert после is not None
    assert после.findings[0].comment == "Грязная печь"


def test_changed_source_never_reuses_old_overlay(проверка, monkeypatch):
    _режим(monkeypatch, "auto")
    _перевод(monkeypatch)
    assert finish_translate.translate_comments(CHAT, проверка) == 0
    domain.edit_finding(CHAT, 1, comment="Новый факт")
    assert snapshot_text.render_state(CHAT, settings_for(CHAT)) == (None, None)


def test_partial_feedback_is_not_labelled_as_translated(проверка, monkeypatch):
    _режим(monkeypatch, "auto")
    domain.set_info(CHAT, "INF01", "Сильные стороны")
    domain.set_info(CHAT, "INF06", "Зоны роста")

    def translate(texts, *, lang):
        if "Зоны роста" in texts:
            raise ModelUnavailable("unavailable")
        return [f"[{lang}] {text}" for text in texts]

    monkeypatch.setattr(localized, "translate_texts", translate)
    assert finish_translate.translate_comments(CHAT, domain.get_state(CHAT)) == 1
    rendered, feedback_lang = snapshot_text.render_state(CHAT, settings_for(CHAT))
    assert feedback_lang is None
    assert rendered["info"]["INF01"]["text"] == "Сильные стороны"
    assert domain.get_state(CHAT).info["INF06"].text == "Зоны роста"


def test_switch_to_manual_does_not_render_cached_auto_text(проверка, monkeypatch):
    _режим(monkeypatch, "auto")
    calls = _перевод(monkeypatch)
    assert finish_translate.translate_comments(CHAT, проверка) == 0
    _режим(monkeypatch, "button")
    assert finish_translate.translate_comments(CHAT, проверка) == 0
    assert snapshot_text.render_state(CHAT, settings_for(CHAT)) == (None, None)
    _режим(monkeypatch, "auto")
    assert finish_translate.translate_comments(CHAT, проверка) == 0
    assert snapshot_text.render_state(CHAT, settings_for(CHAT))[0] is not None
    assert len(calls) == 4
