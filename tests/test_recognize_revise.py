"""#454 (D294, D295): правка записи ответом словами — дешёвая модель, без сети.

Провайдер подменён на уровне `ask_model`: проверяется то, что решает сам
модуль, — что модель получает запись целиком, какую модель зовёт, как читает
ответ «правка текста» / «другое нарушение» и какой ответ отвергает.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.recognize import revise
from src.recognize.client import ModelAnswer
from src.recognize.config import MERGE_MODEL_VAR, load_recognize_settings
from src.recognize.errors import ModelUnavailable
from src.recognize.revise import Revision

SETTINGS = load_recognize_settings({"OPENAI_API_KEY": "unused", MERGE_MODEL_VAR: "cheap-model"})

RECORD: dict[str, str] = {
    "item_code": "PRD09",
    "item_text": "Продукты промаркированы",
    "level": "D1",
    "zone": "fridge",
    "wording": "Соус ранч без маркировки",
}


def ответит(monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def fake(**kw: Any) -> ModelAnswer:
        calls.append(kw)
        return ModelAnswer(payload=payload)

    monkeypatch.setattr(revise, "ask_model", fake)
    return calls


def правка(words: str) -> Revision:
    return revise.revise_finding(**RECORD, words=words, lang="ru", settings=SETTINGS)


def test_правка_текста_возвращает_одну_фразу_и_видит_запись_целиком(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = ответит(monkeypatch, {"kind": "wording", "text": "  Соус терияки\nбез маркировки "})

    got = правка("не ранч, а терияки")

    assert got == Revision(kind="wording", text="Соус терияки без маркировки")
    asked = calls[0]
    assert asked["model"] == "cheap-model", "правка зовёт не дешёвую модель"
    assert asked["photo"] is None
    for part in ("PRD09", "Продукты промаркированы", "D1", "fridge", "Соус ранч без маркировки"):
        assert part in asked["question"], f"модель не получила из записи: {part}"
    assert "не ранч, а терияки" in asked["question"]
    assert "Russian" in asked["instructions"], "язык отчёта не дошёл до модели"


def test_другое_нарушение_текста_не_несёт(monkeypatch: pytest.MonkeyPatch) -> None:
    ответит(monkeypatch, {"kind": "other", "text": "Грязь на полке"})

    assert правка("это не маркировка, а грязь на полке") == Revision(kind="other", text="")


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "wording", "text": "   "},
        {"kind": "wording", "text": 5},
        {"kind": "wording"},
        {"kind": "maybe", "text": "Соус терияки без маркировки"},
        {"text": "Соус терияки без маркировки"},
        {},
    ],
)
def test_пустой_или_кривой_ответ_это_отказ(
    monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]
) -> None:
    ответит(monkeypatch, payload)

    with pytest.raises(ModelUnavailable):
        правка("не ранч, а терияки")


def test_масштаб_которого_не_говорили_отвергается(monkeypatch: pytest.MonkeyPatch) -> None:
    """Правило 2: «в нескольких местах» без слов аудитора — додумка, а не правка."""
    ответит(monkeypatch, {"kind": "wording", "text": "Соусы без маркировки в нескольких местах"})

    with pytest.raises(ModelUnavailable):
        правка("и майонез тоже")


def test_масштаб_сказанный_аудитором_принимается(monkeypatch: pytest.MonkeyPatch) -> None:
    ответит(monkeypatch, {"kind": "wording", "text": "Соусы без маркировки в нескольких местах"})

    assert правка("и так в нескольких местах") == Revision(
        kind="wording", text="Соусы без маркировки в нескольких местах"
    )


def test_без_слов_модель_не_зовётся(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = ответит(monkeypatch, {"kind": "wording", "text": "не должно быть"})

    with pytest.raises(ValueError):
        правка("   ")
    assert calls == []
