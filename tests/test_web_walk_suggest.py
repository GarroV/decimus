"""D330: поиск пункта в мини-аппе — та же механика, что у бота.

Ядро здесь — порядок поиска и что уходит в модель: быстрый путь и выученная
фраза отвечают без модели, пачка с комментарием (D208) их обходит, кадр с
комментарием (D209) модель смотрит. Ошибка тут молчалива: запись появится, но
по чужому пункту или классу, — поэтому проверяется само ядро (`bot.propose`),
а адрес — по отказам и по тому, что найденное НЕ записывается.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from test_web_walk import АУДИТОР
from test_web_walk_write import JPEG, Клиент, клиент  # noqa: F401 -- фикстура

from src.bot import propose as ядро
from src.bot.phrases import Learned
from src.db.busy_lock import Hold
from src.domain import get_state
from src.domain.handover import HANDED_OVER_KEY, NOTES_FILE_NAME
from src.recognize.errors import ModelUnavailable
from src.recognize.fastpath import FastItem, FastPath
from src.recognize.hint import HintItem
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
    monkeypatch.setattr(ядро, "zone_from_words", lambda *a, **k: None)
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
    assert итог.candidates[0].wording == "нагар на поду", (
        "как у бота: сказанное и есть формулировка"
    )


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
    карточка = тело["candidates"][0]
    assert {k: v for k, v in карточка.items() if k != "resolution"} | {"confidence": 0} == {
        "reading_c": None,
        "code": "CLN05",
        "level": "D2",
        "zone": "hot_kitchen",
        "wording": "Нагар.",
        "confidence": 0,
        "flags": [],
    }
    assert карточка["resolution"]["source"] in {"single", "words", "model", "hint", "ask"}
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
    monkeypatch.setattr(
        walk_write, "learn", lambda w, *, item_code, **k: выучено.append((w, item_code)) or ""
    )
    ответ = клиент.запись(
        op="add",
        zone="hot_kitchen",
        code="CLN05",
        level="D1",
        text="Нагар на поду.",
        words="нагар",
        photos=[клиент.ссылка()],
        suggested={
            "code": "CLN05",
            "level": "D2",
            "zone": "hot_kitchen",
            "confidence": 0.8,
            "via": "model",
        },
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
    assert выучено == [] and запись.suggested_code == "", (
        "как у бота: выученное не пишется предложением"
    )


def test_в_модель_идёт_не_больше_десяти_кадров(модель: Модель) -> None:
    _найти("нагар", [bytes([i]) for i in range(25)])

    assert len(модель.звали[0]["photos"]) == ядро.MODEL_FRAMES_MAX, "каждый кадр — платный"


def test_photo_cap_boundary_keeps_first_and_reports_omitted() -> None:
    """F-120: ровно предел — всё уходит; на один больше — первые кадры и счёт отброшенных."""
    from src.web.walk_suggest import MAX_SUGGEST_PHOTOS, cap_photos

    ровно = [f"ref{i}" for i in range(MAX_SUGGEST_PHOTOS)]
    assert cap_photos(ровно) == (ровно, 0)
    больше = [*ровно, "лишний"]
    kept, omitted = cap_photos(больше)
    assert kept == ровно
    assert omitted == 1
    assert cap_photos(None) == (None, 0)


def test_поиск_пока_идёт_в_другом_процессе_отказ_без_вызова_модели(
    клиент: Клиент,  # noqa: F811
    модель: Модель,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F-110: набор в памяти про другой процесс не знает — занятость держит замок базы."""
    monkeypatch.setattr(walk_suggest, "try_hold", lambda *_a: Hold(acquired=False))

    ответ = _поиск(клиент, zone="hot_kitchen", words="нагар", photos=[клиент.ссылка()])

    assert ответ.status_code == 429 and модель.звали == []


def test_поиск_отпускает_замок_и_чат_после_себя(
    клиент: Клиент,  # noqa: F811
    модель: Модель,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    взятые: list[Hold] = []

    def взять(*_a: Any) -> Hold:
        взятые.append(Hold(acquired=True))
        return взятые[-1]

    monkeypatch.setattr(walk_suggest, "try_hold", взять)

    первый = _поиск(клиент, zone="hot_kitchen", words="нагар", photos=[клиент.ссылка()])
    второй = _поиск(клиент, zone="hot_kitchen", words="нагар", photos=[клиент.ссылка()])

    assert (первый.status_code, второй.status_code) == (200, 200), "чат остался занятым"
    assert len(взятые) == 2


def test_второе_нарушение_по_тем_же_кадрам_пишется_и_не_учит_слова(
    клиент: Клиент,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D593: «Тоже записать» — вторая запись с теми же кадрами; слова учат только основной пункт."""
    выучено: list[tuple[str, str]] = []
    monkeypatch.setattr(
        walk_write, "learn", lambda w, *, item_code, **k: выучено.append((w, item_code)) or ""
    )
    кадр = клиент.ссылка()
    общее = {"zone": "hot_kitchen", "words": "дозатор", "photos": [кадр]}

    def предложено(code: str, level: str) -> dict[str, Any]:
        return {"code": code, "level": level, "zone": "hot_kitchen", "via": "model"}

    первая = клиент.запись(
        op="add", code="CLN05", level="D1", suggested=предложено("CLN05", "D1"), **общее
    )
    вторая = клиент.запись(
        op="add",
        code="PRD06",
        level="D1",
        also=True,
        suggested=предложено("PRD06", "D1"),
        **общее,
    )

    assert первая.status_code == 200, первая.get_json()
    assert вторая.status_code == 200, вторая.get_json()
    записи = {f.code: f for f in get_state(АУДИТОР).findings}  # type: ignore[union-attr]
    assert set(записи) == {"CLN05", "PRD06"}
    assert записи["PRD06"].photos == записи["CLN05"].photos == [кадр], "кадр общий у обеих"
    assert записи["PRD06"].suggested_code == "PRD06", "предложение второй — её карточка"
    assert выучено == [("дозатор", "CLN05")], "синонимом второго пункта слова не становятся"


def test_пункт_словаря_нижней_карточкой_без_формулировки(
    клиент: Клиент,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D597: модель спросила и не назвала пункт словаря — он в самом низу, текст пишет аудитор."""
    запас = Candidate(code="CLN06", level="D1", zone="unknown", wording="", confidence=0.0)

    def модель(note: str, photo: bytes | None, zone: str | None, **kw: Any) -> Suggestion:
        return Suggestion(candidates=(МОДЕЛЬ,), question="Нагар или жир?", cue_extras=(запас,))

    monkeypatch.setattr(ядро, "classify", модель)
    monkeypatch.setattr(ядро, "fast_path", lambda *a, **k: FastPath(item=None, reason="no_cue"))
    monkeypatch.setattr(ядро, "recall", lambda *a, **k: None)

    тело = _поиск(клиент, zone="hot_kitchen", words="нагар", photos=[клиент.ссылка()]).get_json()

    assert [c["code"] for c in тело["candidates"]] == ["CLN05", "CLN06"]
    assert тело["candidates"][-1]["wording"] == ""
    assert get_state(АУДИТОР).findings == [], "запас ничего не записывает"  # type: ignore[union-attr]


# ── мгновенная подсказка (#1267, D646 п. 3) ─────────────────────────────


def _подсказка(клиент: Клиент, **тело: Any) -> Any:  # noqa: F811
    return клиент.c.post(
        walk_suggest.HINT_PATH,
        data=json.dumps(тело),
        content_type="application/json",
        headers={"X-Telegram-Init-Data": клиент.init},
    )


@pytest.fixture
def без_базы(monkeypatch: pytest.MonkeyPatch) -> Модель:
    """Подсказка идёт настоящим быстрым путём и картой слов; карта синонимов молчит."""
    m = Модель()
    monkeypatch.setattr(ядро, "classify", m)
    monkeypatch.setattr(ядро, "recall", lambda *a, **k: None)
    return m


def test_подсказка_ядро_не_зовёт_модель_и_ставит_пункт_про_пол(
    domain_env: Path, без_базы: Модель
) -> None:
    итог = ядро.hint(
        "грязный пол на тепловом участке",
        1,
        zone=None,
        chat_id=АУДИТОР,
        ui_lang="ru",
        speech_lang="ru",
    )

    assert итог.via == "hint" and без_базы.звали == [], "подсказка не платит модели"
    assert итог.candidates[0].code == "CLN01"
    assert len(итог.candidates) <= 3


def test_подсказка_выученная_фраза_стоит_первой_без_повторов(
    domain_env: Path, без_базы: Модель, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ядро, "recall", lambda *a, **k: Learned(code="TEH05", phrase="печка"))

    итог = ядро.hint(
        "печь в нагаре", 1, zone="hot_kitchen", chat_id=АУДИТОР, ui_lang="ru", speech_lang="ru"
    )

    коды = [c.code for c in итог.candidates]
    assert коды[0] == "TEH05" and len(коды) == len(set(коды))


def test_подсказка_пачке_с_комментарием_не_положена(domain_env: Path, без_базы: Модель) -> None:
    """D208: по словам аудитор выбрал бы пункт, а кадры никто бы не посмотрел."""
    итог = ядро.hint(
        "грязный пол на тепловом участке",
        3,
        zone=None,
        chat_id=АУДИТОР,
        ui_lang="ru",
        speech_lang="ru",
    )

    assert итог.candidates == ()


def test_адрес_подсказки_отдаёт_карточки_с_зоной_и_ничего_не_пишет(
    клиент: Клиент,  # noqa: F811
    без_базы: Модель,
) -> None:
    ответ = _подсказка(клиент, words="печь в нагаре", zone_hint="hot_kitchen", frames=1)

    assert ответ.status_code == 200, ответ.get_json()
    тело = ответ.get_json()
    assert тело["via"] == "hint" and тело["candidates"][0]["code"] == "CLN05"
    assert тело["candidates"][0]["resolution"]["zone"] == "hot_kitchen", (
        "зона записи выводится теми же правилами, что у поиска"
    )
    assert без_базы.звали == []
    assert get_state(АУДИТОР).findings == [], "подсказка не пишет"  # type: ignore[union-attr]


def test_адрес_подсказки_пуст_если_слова_ничего_не_подняли(
    клиент: Клиент,  # noqa: F811
    без_базы: Модель,
) -> None:
    ответ = _подсказка(клиент, words="ничего особенного не видно", frames=1)

    assert ответ.status_code == 200 and ответ.get_json()["candidates"] == []


def test_подсказка_не_ждёт_поиска_того_же_чата(
    клиент: Клиент,  # noqa: F811
    без_базы: Модель,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Подсказка летит параллельно с поиском: замок «один поиск за раз» её не касается."""
    monkeypatch.setattr(walk_suggest, "try_hold", lambda *_a: Hold(acquired=False))

    поиск = _поиск(клиент, zone="hot_kitchen", words="нагар", photos=[клиент.ссылка()])
    подсказка = _подсказка(клиент, words="печь в нагаре", zone_hint="hot_kitchen", frames=1)

    assert поиск.status_code == 429 and подсказка.status_code == 200


def test_подсказка_без_подписи_не_работает(клиент: Клиент, без_базы: Модель) -> None:  # noqa: F811
    ответ = клиент.c.post(
        walk_suggest.HINT_PATH,
        data=json.dumps({"words": "печь в нагаре"}),
        content_type="application/json",
    )

    assert ответ.status_code in (401, 403)


def test_подсказка_неизвестная_зона_не_ломает_экран(
    клиент: Клиент,  # noqa: F811
    без_базы: Модель,
) -> None:
    ответ = _подсказка(клиент, words="печь в нагаре", zone_hint="nowhere", frames=1)

    assert ответ.status_code == 200 and ответ.get_json()["candidates"] == []


def test_запись_по_подсказке_предложение_пишется_а_слова_не_учатся(
    клиент: Клиент,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    выучено: list[str] = []
    monkeypatch.setattr(walk_write, "learn", lambda w, **k: выучено.append(w) or "")

    ответ = клиент.запись(
        op="add",
        zone="hot_kitchen",
        code="CLN05",
        level="D1",
        words="печь в нагаре",
        photos=[клиент.ссылка()],
        suggested={"code": "CLN05", "level": "D1", "zone": "hot_kitchen", "via": "hint"},
    )

    assert ответ.status_code == 200, ответ.get_json()
    запись = get_state(АУДИТОР).findings[0]  # type: ignore[union-attr]
    assert запись.suggested_code == "CLN05" and выучено == []


def test_подсказка_сданной_проверке_не_положена(
    клиент: Клиент,  # noqa: F811
    без_базы: Модель,
    domain_env: Path,
) -> None:
    заметки = domain_env / f"chat_{АУДИТОР}" / NOTES_FILE_NAME
    заметки.write_text(json.dumps({HANDED_OVER_KEY: 0}), encoding="utf-8")

    ответ = _подсказка(клиент, words="печь в нагаре", zone_hint="hot_kitchen", frames=1)

    assert ответ.status_code == 409


def test_подсказка_не_длиннее_предела_и_с_выученной_и_с_быстрым_путём(
    domain_env: Path, без_базы: Модель, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Выученная фраза, быстрый путь и карта вместе дали бы пять карточек — показываем три."""
    monkeypatch.setattr(ядро, "recall", lambda *a, **k: Learned(code="TEH05", phrase="печка"))
    monkeypatch.setattr(
        ядро,
        "hint_rank",
        lambda *a, **k: tuple(
            HintItem(code=c, level="D1", cue="") for c in ("PRD06", "PRD12", "TEH06")
        ),
    )

    итог = ядро.hint(
        "печь в нагаре", 1, zone="hot_kitchen", chat_id=АУДИТОР, ui_lang="ru", speech_lang="ru"
    )

    assert [c.code for c in итог.candidates] == ["TEH05", "CLN05", "PRD06"]


# ── метрика подсказки (#1267): журнал разбора ───────────────────────────


@pytest.fixture
def журнал(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    события: list[tuple[str, dict[str, Any]]] = []
    for модуль in (walk_suggest, walk_write):
        monkeypatch.setattr(
            модуль.journal, "note", lambda chat, event, **kw: события.append((event, kw))
        )
    return события


def _запись(клиент: Клиент, code: str, via: str, shown: Any) -> Any:  # noqa: F811
    return клиент.запись(
        op="add",
        zone="hot_kitchen",
        code=code,
        level="D1",
        words="печь в нагаре",
        photos=[клиент.ссылка()],
        suggested={"code": "CLN05", "level": "D1", "zone": "hot_kitchen", "via": via},
        hint_codes=shown,
    )


def test_показанная_подсказка_пишется_в_журнал(
    клиент: Клиент,  # noqa: F811
    без_базы: Модель,
    журнал: list[tuple[str, dict[str, Any]]],
) -> None:
    _подсказка(клиент, words="печь в нагаре", zone_hint="hot_kitchen", frames=1)

    событие = [kw for name, kw in журнал if name == "walk_hint"]
    assert len(событие) == 1 and событие[0]["codes"][0] == "CLN05"


def test_пустая_подсказка_в_журнал_не_пишется(
    клиент: Клиент,  # noqa: F811
    без_базы: Модель,
    журнал: list[tuple[str, dict[str, Any]]],
) -> None:
    _подсказка(клиент, words="ничего особенного не видно", frames=1)

    assert [name for name, _ in журнал] == []


def test_выбор_подсказки_и_совпадение_с_первой_пишутся(
    клиент: Клиент,  # noqa: F811
    журнал: list[tuple[str, dict[str, Any]]],
) -> None:
    ответ = _запись(клиент, "CLN05", "hint", ["CLN05", "TEH05"])

    assert ответ.status_code == 200, ответ.get_json()
    ((_, kw),) = [e for e in журнал if e[0] == "walk_hint_choice"]
    assert kw["picked"] == "hint" and kw["code"] == "CLN05" and kw["shown"] == ["CLN05", "TEH05"]
    assert kw["match_first"] is True and kw["match_any"] is True


def test_выбор_ответа_модели_при_показанной_подсказке_пишется_как_расхождение(
    клиент: Клиент,  # noqa: F811
    журнал: list[tuple[str, dict[str, Any]]],
) -> None:
    _запись(клиент, "PRD06", "model", ["CLN05", "TEH05"])

    ((_, kw),) = [e for e in журнал if e[0] == "walk_hint_choice"]
    assert kw["picked"] == "model" and kw["match_first"] is False and kw["match_any"] is False


def test_без_показанной_подсказки_события_нет(
    клиент: Клиент,  # noqa: F811
    журнал: list[tuple[str, dict[str, Any]]],
) -> None:
    _запись(клиент, "CLN05", "model", [])
    _запись(клиент, "CLN05", "model", "мусор")

    assert [e for e in журнал if e[0] == "walk_hint_choice"] == []


def test_тоже_запись_в_метрику_подсказки_не_идёт(
    клиент: Клиент,  # noqa: F811
    журнал: list[tuple[str, dict[str, Any]]],
) -> None:
    """D593: вторая запись по тем же кадрам — не выбор подсказки, считать её дважды нельзя."""
    клиент.запись(
        op="add",
        zone="hot_kitchen",
        code="PRD06",
        level="D1",
        also=True,
        words="печь в нагаре",
        photos=[клиент.ссылка()],
        suggested={"code": "PRD06", "level": "D1", "zone": "hot_kitchen", "via": "model"},
        hint_codes=["CLN05"],
    )

    assert [e for e in журнал if e[0] == "walk_hint_choice"] == []


def test_search_journal_contains_monotonic_stage_timings(клиент, модель, monkeypatch):  # noqa: F811
    from src.recognize.timing import measure, report

    events = []
    original = walk_suggest.propose

    def measured(*args, **kwargs):
        with measure("model"):
            return original(*args, **kwargs)

    monkeypatch.setattr(walk_suggest, "propose", measured)
    monkeypatch.setattr(
        walk_suggest.journal, "note", lambda chat, event, **fields: events.append((event, fields))
    )
    response = _поиск(клиент, zone="hot_kitchen", words="synthetic", photos=[клиент.ссылка()])
    assert response.status_code == 200
    fields = next(fields for event, fields in events if event == "walk_suggest")
    assert isinstance(fields["ms"], int) and fields["ms"] >= fields["model_ms"] >= 0
    assert set(fields["timings_ms"]) == {"frames", "propose", "model", "resolution"}
    assert all(isinstance(value, int) and value >= 0 for value in fields["timings_ms"].values())
    assert report() == {"ms": 0, "model_ms": 0, "timings_ms": {}}


@pytest.mark.parametrize("failure", ["auth", "body", "frames", "model"])
def test_failed_search_logs_timing_without_input(клиент, модель, monkeypatch, caplog, failure):  # noqa: F811
    import logging

    from src.recognize.timing import report

    caplog.set_level(logging.INFO, logger=walk_suggest.__name__)
    private_marker = "synthetic-private-input-marker"
    if failure == "frames":

        def missing(*args, **kwargs):
            raise walk_write.WalkRefused("walk.err.photo_lost")

        monkeypatch.setattr(walk_suggest, "_frames", missing)
    if failure == "model":

        def unavailable(*args, **kwargs):
            raise ModelUnavailable(private_marker)

        monkeypatch.setattr(walk_suggest, "propose", unavailable)
    if failure == "auth":
        response = клиент.c.post(walk_suggest.SUGGEST_PATH, json={"words": private_marker})
    elif failure == "body":
        response = клиент.c.post(
            walk_suggest.SUGGEST_PATH,
            json=[],
            headers={"X-Telegram-Init-Data": клиент.init},
        )
    else:
        response = _поиск(
            клиент, zone="hot_kitchen", words=private_marker, photos=[клиент.ссылка()]
        )
    assert response.status_code >= 400
    records = [r for r in caplog.records if r.msg.startswith("Обход: время поиска")]
    assert len(records) == 1
    record = records[0]
    assert private_marker not in record.getMessage()
    status, metrics = record.args
    assert status == response.status_code
    assert metrics["ms"] >= metrics["model_ms"] >= 0
    if failure in {"frames", "model"}:
        assert "frames" in metrics["timings_ms"]
    if failure == "model":
        assert "propose" in metrics["timings_ms"]
    assert report() == {"ms": 0, "model_ms": 0, "timings_ms": {}}
