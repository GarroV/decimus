"""F-131: свободные поля ответа модели ограничены, но находка не теряется."""

from __future__ import annotations

from src.recognize.classify import _candidate, _suggestion
from src.recognize.config import RecognizeSettings
from src.recognize.guard import (
    MAX_QUESTION_CHARS,
    MAX_WORDING_CHARS,
    TRUNCATED_MARK,
    clean_text,
)

_SETTINGS = RecognizeSettings(
    api_key="k",
    model="m",
    transcribe_model="t",
    timeout=1.0,
    min_confidence=0.5,
    max_candidates=5,
    ffmpeg="ffmpeg",
)
ЗАПИСЬ = {"item": "CLN05:D1", "zone": "hot_kitchen", "confidence": 0.9}


def test_нормальный_текст_проходит_без_изменений() -> None:
    текст = "Пол у печи грязный;\nна полке — 3 просроченных соуса 🍕 (👨‍🍳)."

    assert clean_text(текст, MAX_WORDING_CHARS) == текст


def test_управляющие_символы_и_невидимки_вырезаются() -> None:
    грязный = "пол\x00 гря\x1bзный​‮!\x7f"

    assert clean_text(грязный, MAX_WORDING_CHARS) == "пол грязный!"


def test_сверхдлинное_поле_усекается_с_пометкой_а_находка_остаётся() -> None:
    длинное = "а" * (MAX_WORDING_CHARS * 3)

    кандидат = _candidate({**ЗАПИСЬ, "wording": длинное, "reason": "основание"})

    assert кандидат is not None
    assert len(кандидат.wording) == MAX_WORDING_CHARS + len(TRUNCATED_MARK)
    assert кандидат.wording.endswith(TRUNCATED_MARK)
    assert кандидат.reason == "основание"


def test_вопрос_модели_тоже_ограничен() -> None:
    payload = {"records": [ЗАПИСЬ], "question": "?\x00" * MAX_QUESTION_CHARS}

    suggestion = _suggestion(payload, {}, _SETTINGS, used_photo=False)

    assert len(suggestion.question) <= MAX_QUESTION_CHARS + len(TRUNCATED_MARK)
    assert "\x00" not in suggestion.question
    assert suggestion.needs_human
