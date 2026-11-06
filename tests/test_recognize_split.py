"""D713: деление комментария на отдельные нарушения — дешёвая модель, без сети.

Провайдер подменён на уровне `ask_model`: проверяется то, что решает сам модуль, —
когда модель вообще зовётся, какую модель и что ей уходит, какой ответ отвергается.
Сам смысл деления («разные дефекты» против «один дефект с местом») проверен на
настоящей модели на стенде, не здесь.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.recognize import split
from src.recognize.client import ModelAnswer
from src.recognize.config import MERGE_MODEL_VAR, load_recognize_settings
from src.recognize.errors import ModelUnavailable

SETTINGS = load_recognize_settings({"OPENAI_API_KEY": "unused", MERGE_MODEL_VAR: "cheap-model"})


def ответит(monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def fake(**kw: Any) -> ModelAnswer:
        calls.append(kw)
        return ModelAnswer(payload=payload)

    monkeypatch.setattr(split, "ask_model", fake)
    return calls


def test_разные_дефекты_делятся_на_отдельные_нарушения(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = ответит(monkeypatch, {"violations": ["пол грязный", "дверь не закрывается"]})

    got = split.split_violations("пол грязный, дверь не закрывается", settings=SETTINGS)

    assert got == ("пол грязный", "дверь не закрывается")
    assert calls[0]["model"] == "cheap-model", "деление зовёт не дешёвую модель"
    assert calls[0]["photo"] is None
    assert "пол грязный, дверь не закрывается" in calls[0]["question"]


def test_один_дефект_с_местом_остаётся_одним_нарушением(monkeypatch: pytest.MonkeyPatch) -> None:
    ответит(monkeypatch, {"violations": ["грязный пол у двери"]})

    assert split.split_violations("грязный пол у двери", settings=SETTINGS) == (
        "грязный пол у двери",
    )


def test_короткий_комментарий_модель_не_зовёт(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = ответит(monkeypatch, {"violations": ["x"]})

    assert split.split_violations("  грязный   пол ", settings=SETTINGS) == ("грязный пол",)
    assert split.split_violations("   ", settings=SETTINGS) == ()
    assert calls == [], "два слова не называют два дефекта, платить за них незачем"


def test_пустой_ответ_модели_оставляет_комментарий_целиком(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ответит(monkeypatch, {"violations": []})

    assert split.split_violations("пол грязный и тихо", settings=SETTINGS) == (
        "пол грязный и тихо",
    )


@pytest.mark.parametrize(
    "payload",
    [{"violations": "пол грязный"}, {"violations": [1]}, {}, {"violations": ["пол в крови"]}],
    ids=["не список", "не строки", "нет поля", "чужое слово"],
)
def test_кривой_ответ_отвергается_а_не_принимается_молча(
    monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]
) -> None:
    ответит(monkeypatch, payload)

    with pytest.raises(ModelUnavailable):
        split.split_violations("пол грязный, дверь не закрывается", settings=SETTINGS)


def test_лишние_нарушения_сливаются_в_последнюю_строку_а_не_теряются(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    слова = [f"дефект{n}" for n in range(split.MAX_PARTS + 2)]
    ответит(monkeypatch, {"violations": слова})

    got = split.split_violations(", ".join(слова), settings=SETTINGS)

    assert len(got) == split.MAX_PARTS
    assert got[-1] == " ".join(слова[split.MAX_PARTS - 1 :]), "хвост не потерян"
