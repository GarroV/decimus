"""Пакетный подбор нарушений в обходе (прототип): `POST /tg/walk/batch`.

Ядро здесь — зона записи и то, что подбор ничего не пишет и не ставит повтор:
ошибка молчалива (запись встанет в правдоподобную, но не ту зону). Модель и
проверка класса подменены; сам путь поиска пункта — настоящий (`bot.propose`).
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from test_web_walk import АУДИТОР
from test_web_walk_write import Клиент, клиент  # noqa: F401 -- фикстура

from src.bot import propose as ядро
from src.domain import get_state
from src.recognize.fastpath import FastPath
from src.recognize.models import Candidate, Suggestion
from src.web import walk_auth, walk_batch

МОДЕЛЬ = Candidate(code="PRD05", level="D2", zone="fridge", wording="Нагар.", confidence=0.8)
КЛАСС = {
    "status": "ready",
    "level": "D2",
    "provisional_level": None,
    "need_fact": "",
    "reason": "synthetic",
}


@pytest.fixture
def подмена(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Модель отвечает одним кандидатом, класс — D2; запоминаем, что спросили у класса."""
    спросили: list[dict[str, Any]] = []
    monkeypatch.setattr(
        ядро,
        "classify",
        lambda *a, **k: Suggestion(candidates=(МОДЕЛЬ,), needs_human=False),
    )
    monkeypatch.setattr(ядро, "fast_path", lambda *a, **k: FastPath(item=None, reason="no_cue"))
    monkeypatch.setattr(ядро, "recall", lambda *a, **k: None)

    def класс(who: int, inspection: Any, **kw: Any) -> dict[str, Any]:
        спросили.append(kw)
        return dict(КЛАСС)

    monkeypatch.setattr(walk_batch, "_level", класс)
    return спросили


def _пакет(клиент: Клиент, *карточки: dict[str, Any], **сверх: Any) -> Any:  # noqa: F811
    return клиент.c.post(
        walk_auth.BATCH_PATH,
        data=json.dumps({"cards": list(карточки)} | сверх),
        content_type="application/json",
        headers={"X-Telegram-Init-Data": клиент.init},
    )


def test_зона_называется_в_комментарии_и_берётся_из_слов(
    клиент: Клиент,  # noqa: F811
    подмена: list[dict[str, Any]],
) -> None:
    ответ = _пакет(
        клиент,
        {"id": "a", "words": "в тепловом нагар на подине", "photos": [клиент.ссылка()]},
        {"id": "b", "words": "нагар", "photos": [клиент.ссылка()]},
        zone_hint="dough",
    )

    assert ответ.status_code == 200, ответ.get_json()
    названа, не_названа = ответ.get_json()["cards"]
    assert (названа["zone"], названа["zone_source"]) == ("hot_kitchen", "words")
    # Зона не названа — зона экрана, и источник об этом говорит (карточка подпишет «текущая»).
    assert не_названа["zone"] == "dough"
    assert не_названа["zone_source"] in {"hint", "screen"}
    assert sorted(запрос["zone"] for запрос in подмена) == ["dough", "hot_kitchen"], (
        "класс считается для той зоны, в которую карточка уйдёт"
    )


def test_подбор_ничего_не_пишет_и_повтор_сам_не_ставит(
    клиент: Клиент,  # noqa: F811
    подмена: list[dict[str, Any]],
) -> None:
    ответ = _пакет(
        клиент, {"id": "a", "words": "нагар", "photos": [клиент.ссылка()]}, zone_hint="hot_kitchen"
    )

    карточка = ответ.get_json()["cards"][0]
    assert карточка["status"] == "found" and карточка["class"]["level"] == "D2"
    assert "repeat" not in карточка, "повтор решает человек, подбор его не предлагает как факт"
    assert get_state(АУДИТОР).findings == []  # type: ignore[union-attr]


def test_зона_и_пункт_человека_сильнее_подбора(
    клиент: Клиент,  # noqa: F811
    подмена: list[dict[str, Any]],
) -> None:
    ответ = _пакет(
        клиент,
        {
            "id": "a",
            "words": "нагар",
            "photos": [клиент.ссылка()],
            "code": "CLN05",
            "zone": "dough",
        },
    )

    карточка = ответ.get_json()["cards"][0]
    assert (карточка["code"], карточка["zone"], карточка["zone_source"]) == (
        "CLN05",
        "dough",
        "human",
    )
    assert карточка["candidates"] == [], "пункт назван человеком — поиск по кадрам не идёт"


def test_сбой_одной_карточки_не_роняет_остальные(
    клиент: Клиент,  # noqa: F811
    подмена: list[dict[str, Any]],
) -> None:
    ответ = _пакет(
        клиент,
        {"id": "bad", "words": "нагар", "photos": ["walk:" + "0" * 64]},
        {"id": "ok", "words": "нагар", "photos": [клиент.ссылка()]},
        zone_hint="hot_kitchen",
    )

    плохая, хорошая = ответ.get_json()["cards"]
    assert плохая["status"] == "unavailable" and плохая["message"]
    assert хорошая["status"] == "found"


def test_пустой_и_слишком_большой_пакет_отклоняются(клиент: Клиент) -> None:  # noqa: F811
    assert _пакет(клиент).status_code == 400
    лишние = [{"id": str(n), "words": "x", "photos": []} for n in range(walk_batch.MAX_CARDS + 1)]
    assert _пакет(клиент, *лишние).status_code == 400


def test_чужая_проверка_отклоняется(клиент: Клиент) -> None:  # noqa: F811
    карточка = {"id": "a", "words": "x", "photos": [клиент.ссылка()]}

    assert _пакет(клиент, карточка, run_id="not-this-run").status_code == 409
