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
from src.recognize.errors import ModelUnavailable

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

    def перевести(text: str, *, lang: str) -> str:
        вызовы.append((text, lang))
        return f"[{lang}] {text}"

    monkeypatch.setattr(finish_translate, "translate_text", перевести)
    return вызовы


def test_автоматически_переводит_комментарий_и_рекомендацию(
    проверка: domain.Inspection, monkeypatch: pytest.MonkeyPatch
) -> None:
    _режим(monkeypatch, "auto")
    вызовы = _перевод(monkeypatch)

    сбоев = finish_translate.translate_comments(CHAT, проверка)

    после = domain.get_state(CHAT)
    assert после is not None
    assert сбоев == 0
    assert после.findings[0].comment == "[en] Грязная печь"
    assert после.findings[0].text == "Нагар"  # формулировка из методики не трогается
    assert после.findings[2].text == "[en] Мыть печь каждый день"
    assert вызовы == [("Грязная печь", "en"), ("Мыть печь каждый день", "en")]


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

    monkeypatch.setattr(finish_translate, "translate_text", падает)

    сбоев = finish_translate.translate_comments(CHAT, проверка)

    после = domain.get_state(CHAT)
    assert после is not None
    assert сбоев == 2
    assert после.findings[0].comment == "Грязная печь"
    assert после.findings[2].text == "Мыть печь каждый день"


def test_слишком_длинный_перевод_не_записывается(
    проверка: domain.Inspection, monkeypatch: pytest.MonkeyPatch
) -> None:
    _режим(monkeypatch, "auto")
    monkeypatch.setattr(
        finish_translate,
        "translate_text",
        lambda text, *, lang: "x" * (finish_translate.MAX_TEXT + 1),
    )

    assert finish_translate.translate_comments(CHAT, проверка) == 2
    после = domain.get_state(CHAT)
    assert после is not None
    assert после.findings[0].comment == "Грязная печь"
