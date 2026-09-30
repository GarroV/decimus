"""#443 (D247): сведение комментария записи дешёвой моделью — без сети.

Провайдер подменён на уровне `ask_model`: проверяется то, что решает сам
модуль, — какую модель зовёт, когда не зовёт вовсе и какой ответ отвергает.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.recognize import merge
from src.recognize.client import ModelAnswer
from src.recognize.config import DEFAULT_MERGE_MODEL, MERGE_MODEL_VAR, load_recognize_settings
from src.recognize.errors import ModelUnavailable

SETTINGS = load_recognize_settings({"OPENAI_API_KEY": "unused", MERGE_MODEL_VAR: "cheap-model"})


def ответит(monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def fake(**kw: Any) -> ModelAnswer:
        calls.append(kw)
        return ModelAnswer(payload=payload)

    monkeypatch.setattr(merge, "ask_model", fake)
    return calls


def test_зовёт_дешёвую_модель_из_настроек_и_возвращает_одну_фразу(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = ответит(monkeypatch, {"text": "  Соус и майонез\nбез маркировки  "})

    text = merge.merge_wording("Соус без маркировки", "майонез тоже", settings=SETTINGS)

    assert text == "Соус и майонез без маркировки"
    assert calls[0]["model"] == "cheap-model"
    assert "Соус без маркировки" in calls[0]["question"]
    assert "майонез тоже" in calls[0]["question"]
    assert calls[0]["photo"] is None


def test_имя_модели_по_умолчанию_не_флагман() -> None:
    assert load_recognize_settings({}).merge_model == DEFAULT_MERGE_MODEL
    assert DEFAULT_MERGE_MODEL != load_recognize_settings({}).model


def test_без_новых_слов_модель_не_зовётся(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = ответит(monkeypatch, {"text": "не должно быть"})

    assert merge.merge_wording("Соус без маркировки", "  ", settings=SETTINGS) == (
        "Соус без маркировки"
    )
    assert calls == []


def test_масштаб_которого_не_говорили_отвергается(monkeypatch: pytest.MonkeyPatch) -> None:
    """Правило 2: «в нескольких местах» без слов аудитора — не факт, а додумка."""
    ответит(monkeypatch, {"text": "Соусы без маркировки в нескольких местах"})

    with pytest.raises(ModelUnavailable):
        merge.merge_wording("Соус без маркировки", "майонез тоже", settings=SETTINGS)


def test_масштаб_сказанный_аудитором_принимается(monkeypatch: pytest.MonkeyPatch) -> None:
    ответит(monkeypatch, {"text": "Соусы без маркировки в нескольких местах"})

    assert merge.merge_wording(
        "Соус без маркировки", "и в нескольких местах так же", settings=SETTINGS
    ) == ("Соусы без маркировки в нескольких местах")


@pytest.mark.parametrize("payload", [{"text": "   "}, {"text": 5}, {}])
def test_пустой_или_кривой_ответ_это_отказ(
    monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]
) -> None:
    ответит(monkeypatch, payload)

    with pytest.raises(ModelUnavailable):
        merge.merge_wording("Соус без маркировки", "майонез тоже", settings=SETTINGS)
