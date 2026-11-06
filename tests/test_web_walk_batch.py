"""Пакетный подбор нарушений в обходе: `POST /tg/walk/batch`.

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
from src.web.server_limits import walk_model_gate

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
    # Деление комментария — отдельный платный шаг: по умолчанию комментарий одно нарушение.
    monkeypatch.setattr(walk_batch, "split_violations", lambda words, **kw: (words,))
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
    названа, не_названа = (c["lines"][0] for c in ответ.get_json()["cards"])
    assert (названа["zone"], названа["zone_source"]) == ("hot_kitchen", "words")
    # Зона не названа — зона экрана, и источник об этом говорит (карточка подпишет «текущая»).
    assert не_названа["zone"] == "dough"
    assert не_названа["zone_source"] in {"hint", "screen"}
    assert sorted(запрос["zone"] for запрос in подмена) == ["dough", "hot_kitchen"], (
        "класс считается для той зоны, в которую карточка уйдёт"
    )


def test_зона_экрана_не_подставляется_если_пункта_в_ней_не_бывает(
    клиент: Клиент,  # noqa: F811
    подмена: list[dict[str, Any]],
) -> None:
    """Пакет открыт на фасаде, а нагар на фасаде не бывает: зону спрашивают, а не берут фасад
    (жалоба аудитора 06.11.2026 — пункт кухни получил зону фасада)."""
    ответ = _пакет(
        клиент, {"id": "a", "words": "нагар", "photos": [клиент.ссылка()]}, zone_hint="facade"
    )

    assert ответ.status_code == 200, ответ.get_json()
    строка = ответ.get_json()["cards"][0]["lines"][0]
    assert строка["zone"] != "facade"
    assert строка["zone_source"] != "screen"
    assert "facade" not in строка["zone_options"]


def test_подбор_ничего_не_пишет_и_повтор_сам_не_ставит(
    клиент: Клиент,  # noqa: F811
    подмена: list[dict[str, Any]],
) -> None:
    ответ = _пакет(
        клиент, {"id": "a", "words": "нагар", "photos": [клиент.ссылка()]}, zone_hint="hot_kitchen"
    )

    карточка = ответ.get_json()["cards"][0]["lines"][0]
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

    карточка = ответ.get_json()["cards"][0]["lines"][0]
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
    assert плохая["status"] == "unavailable" and плохая["message"] and плохая["lines"] == []
    assert хорошая["lines"][0]["status"] == "found"


def test_пустой_и_слишком_большой_пакет_отклоняются(клиент: Клиент) -> None:  # noqa: F811
    assert _пакет(клиент).status_code == 400
    лишние = [{"id": str(n), "words": "x", "photos": []} for n in range(walk_batch.MAX_CARDS + 1)]
    assert _пакет(клиент, *лишние).status_code == 400


def test_предел_пачки_пять_карточек_и_отказ_называет_число(
    клиент: Клиент,  # noqa: F811
    подмена: list[dict[str, Any]],
) -> None:
    assert walk_batch.MAX_CARDS == 5
    карточки = [{"id": str(n), "words": "нагар", "photos": [клиент.ссылка()]} for n in range(6)]

    отказ = _пакет(клиент, *карточки)
    принято = _пакет(клиент, *карточки[:5])

    assert отказ.status_code == 400 and "5" in отказ.get_json()["message"]
    assert "{n}" not in отказ.get_json()["message"]
    assert принято.status_code == 200 and len(принято.get_json()["cards"]) == 5


def test_журнал_пишет_строку_на_карточку_с_путём_пакет(
    клиент: Клиент,  # noqa: F811
    подмена: list[dict[str, Any]],
    walk_log_steps: list[Any],
) -> None:
    _пакет(
        клиент,
        {"id": "bad", "words": "нагар", "photos": ["walk:" + "0" * 64]},
        {"id": "ok", "words": "нагар", "photos": [клиент.ссылка(), клиент.ссылка()]},
        zone_hint="hot_kitchen",
    )

    плохая, хорошая = walk_log_steps
    assert (хорошая.step, хорошая.via, хорошая.outcome, хорошая.verdict) == (
        "suggest",
        "batch",
        "ok",
        "found",
    )
    assert (хорошая.words, хорошая.photos, хорошая.item_code) == ("нагар", 2, "PRD05")
    assert хорошая.level == "D2" and хорошая.zone and хорошая.duration_ms is not None
    assert (плохая.outcome, плохая.verdict, плохая.via) == ("error", "unavailable", "batch")
    assert плохая.error, "сбой записан кодом, не молчанием"
    assert "walk:" not in repr(хорошая.detail) and "нагар" not in repr(плохая.error)


def test_журнал_пишет_отказ_всего_пакета_одной_строкой(
    клиент: Клиент,  # noqa: F811
    walk_log_steps: list[Any],
) -> None:
    лишние = [{"id": str(n), "words": "x", "photos": []} for n in range(walk_batch.MAX_CARDS + 1)]

    _пакет(клиент, *лишние)

    (строка,) = walk_log_steps
    assert (строка.via, строка.outcome, строка.item_code) == ("batch", "refused", None)
    assert строка.detail["reason_code"] == "walk.batch.too_many"


def test_чужая_проверка_отклоняется(клиент: Клиент) -> None:  # noqa: F811
    карточка = {"id": "a", "words": "x", "photos": [клиент.ссылка()]}

    assert _пакет(клиент, карточка, run_id="not-this-run").status_code == 409


def test_при_занятом_пределе_модели_карточки_получают_занято_а_не_уходят_в_модель(
    клиент: Клиент,  # noqa: F811
    подмена: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    звали: list[str] = []
    monkeypatch.setattr(ядро, "classify", lambda *a, **k: звали.append("model"))
    gate = walk_model_gate()
    занято = 0
    while gate.try_enter():
        занято += 1
    try:
        ответ = _пакет(
            клиент,
            {"id": "a", "words": "нагар", "photos": [клиент.ссылка()]},
            {"id": "b", "words": "нагар", "photos": [клиент.ссылка()]},
        )
    finally:
        for _ in range(занято):
            gate.leave()

    assert ответ.status_code == 200, ответ.get_json()
    карточки = ответ.get_json()["cards"]
    assert [c["status"] for c in карточки] == ["busy", "busy"]
    assert all(c["message"] for c in карточки), "отказ сказан словами, не молчанием"
    assert звали == [] and подмена == [], "карточка без слота в модель не идёт"


def test_карточка_без_слов_идёт_путём_кадра_и_помечена(
    клиент: Клиент,  # noqa: F811
    подмена: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    видела: list[Any] = []

    def модель(note: str, photo: bytes | None, zone: str | None, **kw: Any) -> Suggestion:
        видела.append((note, photo, kw["photos"]))
        return Suggestion(candidates=(МОДЕЛЬ,), needs_human=False)

    monkeypatch.setattr(ядро, "classify", модель)
    ответ = _пакет(
        клиент,
        {"id": "a", "words": "", "photos": [клиент.ссылка()]},
        {"id": "b", "words": "нагар", "photos": [клиент.ссылка()]},
        zone_hint="dough",
    )

    без_слов, со_словами = (c["lines"][0] for c in ответ.get_json()["cards"])
    assert без_слов["photo_only"] is True and со_словами["photo_only"] is False
    assert без_слов["status"] == "found" and без_слов["wording"], "модель описала кадр"
    assert без_слов["zone"] == "dough", "зона для карточки без слов — зона экрана"
    assert ("", True) in [(n, p is not None) for n, p, _ in видела], "кадр ушёл в модель без слов"
    assert get_state(АУДИТОР).findings == []  # type: ignore[union-attr]


def test_слишком_большое_тело_отклоняется_до_разбора(клиент: Клиент) -> None:  # noqa: F811
    карточка = {"id": "a", "words": "x" * 200_000, "photos": []}

    assert _пакет(клиент, карточка).status_code == 413


ПОЛ = Candidate(code="CLN05", level="D2", zone="fridge", wording="Пол грязный.", confidence=0.9)
ДВЕРЬ = Candidate(code="PRD05", level="D1", zone="fridge", wording="Дверь.", confidence=0.9)


def test_комментарий_с_разными_дефектами_делится_и_у_каждой_строки_свой_пункт(
    клиент: Клиент,  # noqa: F811
    подмена: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    искали: list[str] = []

    def модель(note: str, *a: Any, **kw: Any) -> Suggestion:
        искали.append(note)
        return Suggestion(candidates=(ПОЛ if "пол" in note else ДВЕРЬ,), needs_human=False)

    monkeypatch.setattr(ядро, "classify", модель)
    monkeypatch.setattr(
        walk_batch,
        "split_violations",
        lambda words, **kw: ("пол грязный", "дверь не закрывается"),
    )

    ответ = _пакет(
        клиент,
        {"id": "a", "words": "пол грязный, дверь не закрывается", "photos": [клиент.ссылка()]},
        zone_hint="fridge",
    )

    (карточка,) = ответ.get_json()["cards"]
    пол, дверь = карточка["lines"]
    assert (пол["code"], пол["words"]) == ("CLN05", "пол грязный")
    assert (дверь["code"], дверь["words"]) == ("PRD05", "дверь не закрывается")
    assert пол["id"] != дверь["id"]
    assert sorted(искали) == ["дверь не закрывается", "пол грязный"], "каждая строка ищет сама"
    assert len(подмена) == 2, "класс считается на каждую строку"


def test_один_дефект_с_местом_остаётся_одной_строкой(
    клиент: Клиент,  # noqa: F811
    подмена: list[dict[str, Any]],
) -> None:
    ответ = _пакет(
        клиент,
        {"id": "a", "words": "грязный пол у двери", "photos": [клиент.ссылка()]},
        zone_hint="fridge",
    )

    (карточка,) = ответ.get_json()["cards"]
    assert [x["words"] for x in карточка["lines"]] == ["грязный пол у двери"]


def test_сбой_деления_оставляет_комментарий_одной_строкой_и_говорит_об_этом(
    клиент: Клиент,  # noqa: F811
    подмена: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.recognize.errors import ModelUnavailable

    def упало(words: str, **kw: Any) -> tuple[str, ...]:
        raise ModelUnavailable("нет связи")

    monkeypatch.setattr(walk_batch, "split_violations", упало)

    ответ = _пакет(
        клиент,
        {"id": "a", "words": "пол грязный, дверь не закрывается", "photos": [клиент.ссылка()]},
        zone_hint="fridge",
    )

    (карточка,) = ответ.get_json()["cards"]
    assert [x["words"] for x in карточка["lines"]] == ["пол грязный, дверь не закрывается"]
    assert карточка["split_failed"] is True


def test_кадр_без_слов_даёт_строку_на_каждое_увиденное_нарушение(
    клиент: Клиент,  # noqa: F811
    подмена: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ядро,
        "classify",
        lambda *a, **k: Suggestion(candidates=(ПОЛ, ДВЕРЬ, ПОЛ), needs_human=False),
    )

    ответ = _пакет(
        клиент, {"id": "a", "words": "", "photos": [клиент.ссылка()]}, zone_hint="fridge"
    )

    (карточка,) = ответ.get_json()["cards"]
    строки = карточка["lines"]
    assert [x["code"] for x in строки] == ["CLN05", "PRD05"], "повтор модели строку не множит"
    assert all(x["photo_only"] and x["status"] == "found" for x in строки)
    assert len({x["id"] for x in строки}) == 2


def test_повтор_строки_по_выбору_человека_возвращает_одну_строку_с_тем_же_id(
    клиент: Клиент,  # noqa: F811
    подмена: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    делили: list[str] = []
    monkeypatch.setattr(
        walk_batch, "split_violations", lambda words, **kw: делили.append(words) or (words,)
    )

    ответ = _пакет(
        клиент,
        {
            "id": "a",
            "line": "a-2",
            "words": "пол грязный, дверь не закрывается",
            "code": "CLN05",
            "photos": [клиент.ссылка()],
        },
        zone_hint="fridge",
    )

    (карточка,) = ответ.get_json()["cards"]
    assert [x["id"] for x in карточка["lines"]] == ["a-2"]
    assert делили == [], "строка уже выбрана, комментарий заново не режется"


def test_журнал_пишет_строку_на_нарушение(
    клиент: Клиент,  # noqa: F811
    подмена: list[dict[str, Any]],
    walk_log_steps: list[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(walk_batch, "split_violations", lambda words, **kw: ("пол", "дверь"))

    _пакет(
        клиент,
        {"id": "a", "words": "пол грязный, дверь не закрывается", "photos": [клиент.ссылка()]},
        zone_hint="fridge",
    )

    первая, вторая = walk_log_steps
    assert (первая.words, вторая.words) == ("пол", "дверь")
    assert (первая.detail["line"], вторая.detail["line"], первая.detail["lines"]) == (1, 2, 2)


def test_один_кадр_ложится_в_несколько_записей_ссылкой_а_не_копией(
    клиент: Клиент,  # noqa: F811
) -> None:
    ссылка = клиент.ссылка()
    тело = {"op": "add", "zone": "hot_kitchen", "level": "D1", "photos": [ссылка]}

    первая = клиент.запись(**тело, code="CLN05", text="Пол грязный")
    вторая = клиент.запись(**тело, code="PRD05", text="Дверь не закрывается")

    assert первая.status_code == 200 and вторая.status_code == 200, (
        первая.get_json(),
        вторая.get_json(),
    )
    записи = get_state(АУДИТОР).findings  # type: ignore[union-attr]
    assert [(f.code, f.photos) for f in записи] == [("CLN05", [ссылка]), ("PRD05", [ссылка])]


def test_параллельных_вызовов_модели_не_больше_слотов_предела_а_строк_в_вызове_не_больше_общего(
    клиент: Клиент,  # noqa: F811
    подмена: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import threading
    import time

    gate = walk_model_gate()
    слотов = 2
    занято = 0
    while gate.try_enter():
        занято += 1
    for _ in range(занято):
        gate.leave()
    assert занято >= 1
    # Оставляем предел в `слотов` свободных: остальные заняты на время теста.
    держим = max(занято - слотов, 0)
    for _ in range(держим):
        gate.try_enter()
    lock, сейчас, пик, звали = threading.Lock(), [0], [0], [0]

    def модель(note: str, *a: Any, **kw: Any) -> Suggestion:
        with lock:
            сейчас[0] += 1
            звали[0] += 1
            пик[0] = max(пик[0], сейчас[0])
        time.sleep(0.05)
        with lock:
            сейчас[0] -= 1
        return Suggestion(candidates=(МОДЕЛЬ,), needs_human=False)

    monkeypatch.setattr(ядро, "classify", модель)
    monkeypatch.setattr(
        walk_batch,
        "split_violations",
        lambda words, max_parts=8, **kw: tuple(f"дефект{n}" for n in range(max_parts)),
    )
    try:
        ответ = _пакет(
            клиент,
            *[
                {"id": str(n), "words": "раз два три четыре", "photos": [клиент.ссылка()]}
                for n in range(5)
            ],
        )
    finally:
        for _ in range(держим):
            gate.leave()

    карточки = ответ.get_json()["cards"]
    принятых = [c for c in карточки if c["status"] == "ok"]
    assert пик[0] <= min(занято, слотов), "строки не должны обходить предел модели"
    assert len(принятых) <= слотов and len(карточки) == 5
    assert all(c["status"] == "busy" and c["message"] for c in карточки if c not in принятых)
    assert sum(len(c["lines"]) for c in принятых) <= walk_batch.MAX_LINES_TOTAL
    assert звали[0] <= walk_batch.MAX_LINES_TOTAL


def test_пункт_строки_решают_её_слова_а_увиденное_на_кадре_чужой_строке_не_достаётся(
    клиент: Клиент,  # noqa: F811
    подмена: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Общий кадр — пол; модель по словам про дверь ничего не нашла, но «увидела» пол."""

    def модель(note: str, *a: Any, **kw: Any) -> Suggestion:
        if "пол" in note:
            return Suggestion(candidates=(ПОЛ,), needs_human=False)
        return Suggestion(candidates=(), also_seen=(ПОЛ,), needs_human=False)

    monkeypatch.setattr(ядро, "classify", модель)
    monkeypatch.setattr(
        walk_batch,
        "split_violations",
        lambda words, **kw: ("пол грязный", "дверь не закрывается"),
    )

    ответ = _пакет(
        клиент,
        {"id": "a", "words": "пол грязный, дверь не закрывается", "photos": [клиент.ссылка()]},
        zone_hint="fridge",
    )

    пол, дверь = ответ.get_json()["cards"][0]["lines"]
    assert пол["code"] == "CLN05"
    assert дверь["status"] == "no_item" and "code" not in дверь, (
        "строка про дверь не получает пункт про пол"
    )


def test_зона_выбранная_на_карточке_держится_при_новом_подборе_и_деление_остаётся(
    клиент: Клиент,  # noqa: F811
    подмена: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Человек сменил зону, потом дописал слова — карточку подбирают заново. Его зона остаётся,
    зона экрана её не перебивает (Брашов-1, 06.11.2026: мойка → «Фасад» после правки текста)."""
    monkeypatch.setattr(
        ядро,
        "classify",
        lambda note, *a, **kw: Suggestion(
            candidates=(ПОЛ if "пол" in note else ДВЕРЬ,), needs_human=False
        ),
    )
    monkeypatch.setattr(
        walk_batch,
        "split_violations",
        lambda words, **kw: ("пол грязный", "дверь не закрывается"),
    )

    ответ = _пакет(
        клиент,
        {
            "id": "a",
            "words": "пол грязный, дверь не закрывается",
            "photos": [клиент.ссылка()],
            "card_zone": "dishwashing",
        },
        zone_hint="facade",
    )

    (карточка,) = ответ.get_json()["cards"]
    assert len(карточка["lines"]) == 2, "зона карточки не выключает деление на нарушения"
    for строка in карточка["lines"]:
        assert (строка["zone"], строка["zone_source"]) == ("dishwashing", "human")
