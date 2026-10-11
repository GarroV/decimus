"""D393, #538: язык речи проверки доходит до вызова расшифровки голоса.

Сеть не участвует: клиент провайдера и перекодировка подменены. Проверяется
одно — какие параметры уходят в `audio.transcriptions.create`.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.recognize import transcribe as transcribe_module
from src.recognize.config import RecognizeSettings

SETTINGS = RecognizeSettings(
    model="gpt-5.6-sol",
    transcribe_model="gpt-4o-mini-transcribe",
    api_key="sk-test",
    timeout=90.0,
    min_confidence=0.6,
    max_candidates=5,
    ffmpeg="ffmpeg",
)


class _Result:
    text = "слова"


def _fake_openai(sent: dict[str, Any]) -> type:
    class _Transcriptions:
        def create(self, **kwargs: Any) -> _Result:
            sent.update(kwargs)
            return _Result()

    class _Audio:
        transcriptions = _Transcriptions()

    class _Client:
        def __init__(self, **_: Any) -> None:
            self.audio = _Audio()

    return _Client


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(transcribe_module, "OpenAI", _fake_openai(captured))
    monkeypatch.setattr(transcribe_module, "_reencode", lambda audio, ffmpeg: b"wav")
    return captured


def test_speech_language_is_passed_to_the_model(sent: dict[str, Any]) -> None:
    transcribe_module.transcribe(b"ogg", lang="ru", settings=SETTINGS)

    assert sent["language"] == "ru"


def test_without_language_the_model_detects_it_itself(sent: dict[str, Any]) -> None:
    transcribe_module.transcribe(b"ogg", settings=SETTINGS)

    assert "language" not in sent or sent["language"] is transcribe_module.omit
