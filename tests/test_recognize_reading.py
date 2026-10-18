"""Показание термометра в разборе: структурное поле и пересчёт по числу аудитора (#836)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.recognize.classify import classify
from src.recognize.client import ModelAnswer
from src.recognize.config import NO_CHAT
from src.recognize.schema import picks_for, response_schema


def _record(reading: object) -> dict[str, Any]:
    return {
        "item": "CLN05:D1",
        "zone": "hot_kitchen",
        "wording": "Про градусы.",
        "reason": "термометр на кадре",
        "confidence": 0.9,
        "reading_c": reading,
    }


class _Model:
    def __init__(self, reading: object) -> None:
        self.reading = reading
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> ModelAnswer:
        self.calls.append(kwargs)
        return ModelAnswer(payload={"records": [_record(self.reading)], "question": ""}, usage={})


def _patch(monkeypatch: pytest.MonkeyPatch, model: _Model) -> None:
    monkeypatch.setattr("src.recognize.classify.ask_model", model)


def test_схема_просит_показание_числом_или_null(domain_env: Path) -> None:
    schema = response_schema(picks_for(("CLN05",), chat_id=NO_CHAT), ["hot_kitchen"])

    record = schema["properties"]["records"]["items"]

    assert record["properties"]["reading_c"]["type"] == ["number", "null"]
    assert "reading_c" in record["required"], "строгий режим: поле обязано быть в required"


@pytest.mark.parametrize(
    ("ответ", "ожидаемое"),
    [(26, 26.0), (6.5, 6.5), (-18, -18.0), (None, None), ("26", None), (True, None), (1e9, None)],
)
def test_показание_из_ответа_модели(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch, ответ: object, ожидаемое: float | None
) -> None:
    _patch(monkeypatch, _Model(ответ))

    found = classify("замер", chat_id=NO_CHAT)

    assert found.candidates[0].reading_c == ожидаемое


def test_исправленное_число_уходит_в_запрос_и_остаётся_в_ответе(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = _Model(26)  # модель снова читает 26 с кадра

    _patch(monkeypatch, model)
    found = classify("замер", chat_id=NO_CHAT, reading_c=6.0)

    assert "реальная температура 6 °C" in model.calls[0]["question"]
    assert found.candidates[0].reading_c == 6.0, "слово аудитора перебито чтением модели"


def test_без_исправления_запрос_не_несёт_утверждения(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = _Model(26)

    _patch(monkeypatch, model)
    found = classify("замер", chat_id=NO_CHAT)

    assert "реальная температура" not in model.calls[0]["question"]
    assert found.candidates[0].reading_c == 26.0
