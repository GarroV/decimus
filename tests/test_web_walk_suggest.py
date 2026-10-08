"""D330: поиск пункта в мини-аппе — та же механика, что у бота.

Ядро здесь — порядок поиска и что уходит в модель: быстрый путь и выученная
фраза отвечают без модели, пачка с комментарием (D208) их обходит, кадр с
комментарием (D209) модель смотрит. Ошибка тут молчалива: запись появится, но
по чужому пункту или классу, — поэтому проверяется само ядро (`bot.propose`),
а адрес — по отказам и по тому, что найденное НЕ записывается.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from test_web_walk import АУДИТОР
from test_web_walk_write import JPEG, Клиент, клиент  # noqa: F401 -- фикстура

from src.bot import propose as ядро
from src.bot.phrases import Learned
from src.domain import get_state
from src.recognize.errors import ModelUnavailable
from src.recognize.fastpath import FastItem, FastPath
from src.recognize.models import Candidate, Suggestion
from src.web import walk_suggest, walk_write

МОДЕЛЬ = Candidate(code="CLN05", level="D2", zone="hot_kitchen", wording="Нагар.", confidence=0.8)


class Модель:
    """Подмена модели: запоминает, что ей дали, и отвечает одним кандидатом."""

    def __init__(self) -> None:
        self.звали: list[dict[str, Any]] = []

    def __call__(self, note: str, photo: bytes | None, zone: str | None, **kw: Any) -> Suggestion:
        self.звали.append({"note": note, "photo": photo, "photos": kw["photos"], "zone": zone})
        return Suggestion(candidates=(МОДЕЛЬ,), needs_human=False)


@pytest.fixture
def модель(monkeypatch: pytest.MonkeyPatch) -> Модель:
    m = Модель()
    monkeypatch.setattr(ядро, "classify", m)
    monkeypatch.setattr(ядро, "fast_path", lambda *a, **k: FastPath(item=None, reason="no_cue"))
    monkeypatch.setattr(ядро, "recall", lambda *a, **k: None)
    return m


def _найти(note: str, frames: list[bytes]) -> ядро.Offer:
    return ядро.propose(
        note,
        frames,
        zone="hot_kitchen",
        chat_id=АУДИТОР,
        ui_lang="ru",
        speech_lang="ru",
        report_lang="ru",
    )


# ── ядро: порядок поиска и кадры ────────────────────────────────────────


def test_однозначные_слова_находят_пункт_без_модели(
    модель: Модель, monkeypatch: pytest.MonkeyPatch
) -> None:
    пункт = FastItem(code="CLN05", level="D1", zone="hot_kitchen", title="Печь", cue="нагар")
    monkeypatch.setattr(ядро, "fast_path", lambda *a, **k: FastPath(item=пункт, reason=""))

    итог = _найти("нагар на поду", [b"x"])

    assert итог.via == "fast" and модель.звали == [], "быстрый путь платил бы модели зря"
    assert итог.candidates[0].wording == "нагар на поду", "как у бота: сказанное и есть формулировка"


def test_выученная_фраза_находит_пункт_без_модели(
    модель: Модель, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ядро, "recall", lambda *a, **k: Learned(code="CLN05", phrase="грязь"))

    итог = _найти("грязь в печи", [b"x"])

    assert итог.via == "learned" and модель.звали == []
    assert итог.candidates[0].code == "CLN05"


def test_пачка_с_комментарием_идёт_в_модель_целиком(
    модель: Модель, monkeypatch: pytest.MonkeyPatch
) -> None:
    пункт = FastItem(code="PRD06", level="D1", zone="hot_kitchen", title="Тара", cue="крышка")
    monkeypatch.setattr(ядро, "fast_path", lambda *a, **k: FastPath(item=пункт, reason=""))

    итог = _найти("сыр и ветчина", [b"1", b"2", b"3"])

    assert итог.via == "model", "D208: по словам записалось бы сказанное, кадры никто не увидел бы"
    assert модель.звали[0]["photos"] == (b"1", b"2", b"3")


def test_кадр_с_комментарием_модель_смотрит(модель: Модель) -> None:
    _найти("просроченный чизкейк", [b"1"])

    assert модель.звали[0]["photos"] == (b"1",), "D209: класс выбирается по наклейке на кадре"


def test_голый_кадр_уходит_в_модель_один(модель: Модель) -> None:
    _найти("", [b"1"])

    assert модель.звали[0]["photo"] == b"1" and модель.звали[0]["photos"] == ()


# ── адрес: отказы и «ничего не записано» ────────────────────────────────


def _поиск(клиент: Клиент, **тело: Any) -> Any:  # noqa: F811
    return клиент.c.post(
        walk_suggest.SUGGEST_PATH,
        data=json.dumps(тело),
        content_type="application/json",
        headers={"X-Telegram-Init-Data": клиент.init},
    )


def test_поиск_отдаёт_карточки_и_ничего_не_записывает(
    клиент: Клиент,  # noqa: F811
    модель: Модель,
) -> None:
    ответ = _поиск(клиент, zone="hot_kitchen", words="нагар", photos=[клиент.ссылка()])

    assert ответ.status_code == 200, ответ.get_json()
    тело = ответ.get_json()
    assert тело["via"] == "model"
    assert тело["candidates"][0] | {"confidence": 0} == {
        "code": "CLN05",
        "level": "D2",
        "zone": "hot_kitchen",
        "wording": "Нагар.",
        "confidence": 0,
    }
    assert модель.звали[0]["photos"] == (JPEG,), "кадр мини-аппа дошёл до модели"
    assert get_state(АУДИТОР).findings == [], "модель предлагает, фиксирует человек"  # type: ignore[union-attr]


def test_поиск_без_кадра_отклоняется(клиент: Клиент, модель: Модель) -> None:  # noqa: F811
    ответ = _поиск(клиент, zone="hot_kitchen", words="нагар", photos=[])

    assert ответ.status_code == 422 and модель.звали == []


def test_поиск_без_подписи_не_работает(клиент: Клиент, модель: Модель) -> None:  # noqa: F811
    ответ = клиент.c.post(
        walk_suggest.SUGGEST_PATH,
        data=json.dumps({"words": "нагар", "photos": [клиент.ссылка()]}),
        content_type="application/json",
    )

    assert ответ.status_code in (401, 403) and модель.звали == []


def test_модель_недоступна_аудитор_выбирает_вручную(
    клиент: Клиент,  # noqa: F811
    модель: Модель,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def лежит(*a: Any, **k: Any) -> Suggestion:
        raise ModelUnavailable("нет ключа")

    monkeypatch.setattr(ядро, "classify", лежит)

    ответ = _поиск(клиент, zone="hot_kitchen", words="нагар", photos=[клиент.ссылка()])

    assert ответ.status_code == 503
    assert "нет ключа" not in ответ.get_json()["message"], "внутренности — в журнал, не аудитору"


# ── запись по предложению ───────────────────────────────────────────────


def test_запись_по_предложению_хранит_слова_и_предложенное(
    клиент: Клиент,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    выучено: list[tuple[str, str]] = []
    monkeypatch.setattr(walk_write, "learn", lambda w, *, item_code, **k: выучено.append((w, item_code)) or "")
    ответ = клиент.запись(
        op="add",
        zone="hot_kitchen",
        code="CLN05",
        level="D1",
        text="Нагар на поду.",
        words="нагар",
        photos=[клиент.ссылка()],
        suggested={"code": "CLN05", "level": "D2", "zone": "hot_kitchen", "confidence": 0.8, "via": "model"},
    )

    assert ответ.status_code == 200, ответ.get_json()
    запись = get_state(АУДИТОР).findings[0]  # type: ignore[union-attr]
    assert запись.words == "нагар"
    assert (запись.suggested_code, запись.suggested_level) == ("CLN05", "D2"), (
        "без предложенного не видно, что аудитор поправил класс модели"
    )
    assert выучено == [("нагар", "CLN05")], "D119: слова должны найти пункт в следующий раз"


def test_выученная_фраза_второй_раз_не_учится(
    клиент: Клиент,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    выучено: list[str] = []
    monkeypatch.setattr(walk_write, "learn", lambda w, **k: выучено.append(w) or "")
    клиент.запись(
        op="add",
        zone="hot_kitchen",
        code="CLN05",
        level="D1",
        words="нагар",
        photos=[клиент.ссылка()],
        suggested={"code": "CLN05", "level": "D1", "zone": "hot_kitchen", "via": "learned"},
    )

    запись = get_state(АУДИТОР).findings[0]  # type: ignore[union-attr]
    assert выучено == [] and запись.suggested_code == "", "как у бота: выученное не пишется предложением"
