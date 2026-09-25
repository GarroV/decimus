"""Пачка кадров с комментарием в разборе (D180): кадры уходят модели, увиденное — отдельно.

До D180 кадры с комментарием в модель не шли вовсе (D081). Боевой случай
24.09.2026 показал цену: подпись «овощи и сыр» ушла без семи кадров со щупами в
мясе, и модель выбрала пункт класса ниже, чем видно на кадрах. Здесь
проверяется граница правила: пачка — все кадры и поле `also_seen`; один кадр с
комментарием — по-прежнему по словам, без картинки и без нового поля.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.recognize.classify import album_mode, classify
from src.recognize.client import ModelAnswer
from src.recognize.config import NO_CHAT


class _Recorder:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> ModelAnswer:
        self.calls.append(kwargs)
        return ModelAnswer(payload=self.payload, usage={})


def _record(item: str, wording: str) -> dict[str, Any]:
    return {
        "item": item,
        "zone": "hot_kitchen",
        "wording": wording,
        "reason": "",
        "confidence": 0.9,
    }


def test_пачка_с_комментарием_уходит_модели_всеми_кадрами(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = _Recorder(
        {
            "records": [_record("CLN05:D1", "по словам")],
            "question": "",
            "also_seen": [_record("CLN06:D1", "видно на кадре")],
        }
    )
    monkeypatch.setattr("src.recognize.classify.ask_model", recorder)

    итог = classify("печь грязная", None, "hot_kitchen", chat_id=NO_CHAT, photos=(b"1", b"2", b"3"))

    call = recorder.calls[0]
    assert tuple(call["photos"]) == (b"1", b"2", b"3"), "кадры пачки не ушли модели"
    assert "also_seen" in call["schema"]["required"], "схема не просит увиденное сверх слов"
    assert "кадров: 3" in call["question"]
    assert [c.code for c in итог.candidates] == ["CLN05"]
    assert [c.code for c in итог.also_seen] == ["CLN06"]
    assert итог.used_photo is True


def test_один_кадр_с_комментарием_тоже_уходит_модели(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D181: одиночный кадр с подписью модель видит, а время отправки уходит в запрос."""
    recorder = _Recorder({"records": [_record("CLN05:D1", "по словам")], "question": ""})
    monkeypatch.setattr("src.recognize.classify.ask_model", recorder)

    classify(
        "печь грязная",
        None,
        "hot_kitchen",
        chat_id=NO_CHAT,
        photos=(b"1",),
        sent_at="2026-09-25 10:32",
    )

    call = recorder.calls[0]
    assert tuple(call["photos"]) == (b"1",), "одиночный кадр с подписью не ушёл модели"
    assert "2026-09-25 10:32 UTC" in call["question"], "время отправки не попало в запрос"
    assert "не опровергай" in call["question"], (
        "модели не сказано, что слова аудитора не проверяются"
    )


def test_без_кадров_комментарий_разбирается_по_словам(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = _Recorder({"records": [_record("CLN05:D1", "по словам")], "question": ""})
    monkeypatch.setattr("src.recognize.classify.ask_model", recorder)

    итог = classify("печь грязная", None, "hot_kitchen", chat_id=NO_CHAT)

    call = recorder.calls[0]
    assert call["photo"] is None and tuple(call["photos"]) == ()
    assert "also_seen" not in call["schema"]["properties"]
    assert итог.also_seen == ()


@pytest.mark.parametrize(
    ("note", "frames", "expected"),
    [("печь", 2, True), ("печь", 1, False), ("", 5, False), ("   ", 3, False)],
)
def test_граница_пачки(note: str, frames: int, expected: bool) -> None:
    assert album_mode(note, frames) is expected
