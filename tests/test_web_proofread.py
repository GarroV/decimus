# ruff: noqa: F811
"""D535: правка прямо в записях на вычитке и «+ Добавить нарушение».

Поверхность: что видно и кому, что доходит до двери, чего НЕ происходит без
выбора человека. Сам подбор пункта (`bot.propose`) здесь подменён — его
проверяют свои наборы; проверяется, как экран его использует.
"""

from __future__ import annotations

import io
from dataclasses import replace
from typing import Any

import pytest
from flask.testing import FlaskClient
from PIL import Image
from test_web_acceptance import ORIGIN, _лист, _приёмка, админ, стенд  # noqa: F401
from test_web_app import карточка, шапка

from src.bot.propose import Offer
from src.db.busy_lock import Hold
from src.db.errors import ReviseError
from src.recognize.errors import ModelUnavailable
from src.recognize.models import Candidate
from src.web import inspections as data
from src.web import proofread, review, revision, walk_suggest
from src.web.guard import ACTIONS_ATTR, OBJECT_IN_ROUTE_ATTR

ПАНЕЛЬ = "/inspections?inspection=x"
ЗАПИСЬ = карточка(шапка()).findings[0]
ФОРМА = {"code": "CLN02", "level": "D2", "zone": "KITCHEN", "text": "пол в зале"}


def _jpeg() -> bytes:
    буфер = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 30, 30)).save(буфер, format="JPEG")
    return буфер.getvalue()


def _файл(имя: str = "p.jpg") -> tuple[io.BytesIO, str]:
    return io.BytesIO(_jpeg()), имя


# --- «Весь чек-лист» снят, отдельной кнопки «Исправить» нет -------------------


@админ
@pytest.mark.parametrize("ждёт", [True, False])
@pytest.mark.parametrize("адрес", ["/inspections/x", ПАНЕЛЬ])
def test_блока_весь_чек_лист_нет_ни_на_вычитке_ни_у_принятой(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch, ждёт: bool, адрес: str
) -> None:
    _приёмка(monkeypatch, ждёт=ждёт)
    _лист(monkeypatch)

    страница = стенд.get(адрес).get_data(as_text=True)

    assert "Весь чек-лист" not in страница and 'id="review"' not in страница
    assert "review-zone" not in страница and "Записи вне чек-листа" not in страница


@админ
def test_в_панели_на_вычитке_нет_режима_исправить(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _приёмка(monkeypatch)
    _лист(monkeypatch)

    страница = стенд.get(ПАНЕЛЬ).get_data(as_text=True)

    assert "data-edit-toggle" not in страница and "is-editing" not in страница
    # Правка — у самой записи: карандаш и скрытая форма под ней.
    assert "data-proofread-edit" in страница and 'data-proofread-form="edit"' in страница
    # Удаление ошибочной записи (#1164): подтверждение раскрывающимся блоком, без alert/confirm.
    assert "/findings/" in страница and "/delete" in страница and "data-del" in страница
    assert "window.confirm" not in страница and "data-confirm" not in страница


# --- «+ Добавить нарушение»: кому и когда --------------------------------------


@админ
def test_кнопка_добавить_нарушение_есть_на_вычитке_у_того_кто_правит(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _приёмка(monkeypatch)
    _лист(monkeypatch)

    for адрес in ("/inspections/x", ПАНЕЛЬ):
        страница = стенд.get(адрес).get_data(as_text=True)
        assert "data-proofread-add" in страница, адрес
        assert "Добавить нарушение" in страница and 'data-proofread-form="add"' in страница


@админ
def test_кнопки_нет_у_принятой(стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _приёмка(monkeypatch, ждёт=False)
    _лист(monkeypatch)

    for адрес in ("/inspections/x", ПАНЕЛЬ):
        страница = стенд.get(адрес).get_data(as_text=True)
        assert "data-proofread" not in страница and "Добавить нарушение" not in страница


@админ
def test_кнопки_нет_у_чужой_ждущей_проверки(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _приёмка(monkeypatch, пространство="GE")
    _лист(monkeypatch)

    страница = стенд.get("/inspections/x").get_data(as_text=True)

    assert "data-proofread" not in страница and "Добавить нарушение" not in страница


@pytest.mark.parametrize("стенд", ["guest"], indirect=True)
def test_кнопки_нет_у_гостя(стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _приёмка(monkeypatch)
    _лист(monkeypatch)

    страница = стенд.get("/inspections/x").get_data(as_text=True)

    assert "data-proofread" not in страница and "Добавить нарушение" not in страница


@админ
def test_без_прочитанного_чек_листа_править_не_из_чего(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _приёмка(monkeypatch)
    monkeypatch.setattr(review, "load_sheet", lambda *_a, **_k: None)

    страница = стенд.get("/inspections/x").get_data(as_text=True)

    assert "data-proofread" not in страница and "Добавить нарушение" not in страница


@админ
def test_замер_и_рекомендацию_правкой_класса_не_делают_нарушением(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D201: у записи вне D1–D3 карандаша нет, как не было формы."""
    _приёмка(monkeypatch)
    _лист(monkeypatch)
    базовая = карточка(шапка(on_review=True))
    замер = replace(базовая.findings[0], level="D0")
    monkeypatch.setattr(data, "load_card", lambda *_a, **_k: replace(базовая, findings=(замер,)))

    страница = стенд.get("/inspections/x").get_data(as_text=True)

    assert "data-proofread-edit" not in страница
    assert "data-proofread-add" in страница


# --- подбор пункта: заслоны и то, что он ничего не пишет ----------------------


def _двери_записи(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    зовы: list[str] = []
    for имя in ("add_card", "revise_card", "change_photos"):
        monkeypatch.setattr(revision, имя, lambda *_a, _и=имя, **_k: зовы.append(_и))
    return зовы


@админ
def test_подбор_закрыт_чужому_пространству_и_чужому_origin(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _приёмка(monkeypatch, пространство="GE")
    monkeypatch.setattr(
        proofread, "suggest", lambda *_a, **_k: pytest.fail("подбор не должен идти")
    )

    чужое = стенд.post("/inspections/x/suggest", data={"text": "грязный пол"}, headers=ORIGIN)
    _приёмка(monkeypatch)
    чужой_origin = стенд.post(
        "/inspections/x/suggest",
        data={"text": "грязный пол"},
        headers={"Origin": "http://evil.example"},
    )

    assert чужое.status_code == 403
    assert чужой_origin.status_code in (400, 403)


@pytest.mark.parametrize("стенд", ["guest"], indirect=True)
def test_подбор_закрыт_гостю(стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _приёмка(monkeypatch)
    monkeypatch.setattr(
        proofread, "suggest", lambda *_a, **_k: pytest.fail("подбор не должен идти")
    )

    ответ = стенд.post("/inspections/x/suggest", data={"text": "грязный пол"}, headers=ORIGIN)

    assert ответ.status_code == 403


def test_подбор_объявлен_в_матрице_тем_же_правом_что_правка_записи() -> None:
    """Объявление маршрута: `inspection.revise` по объекту — адрес не остаётся без заслона."""
    from web_harness import собрать

    вид = собрать(tenant="HQ").view_functions["do_suggest"]

    assert getattr(вид, ACTIONS_ATTR) == ("inspection.revise",)
    assert getattr(вид, OBJECT_IN_ROUTE_ATTR) is True


@админ
def test_подбор_принятой_отказывает_а_не_ищет(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _приёмка(monkeypatch, ждёт=False)
    monkeypatch.setattr(
        proofread, "suggest", lambda *_a, **_k: pytest.fail("подбор не должен идти")
    )

    def принятая(*_a: Any, **_k: Any) -> None:
        raise ReviseError("Проверка уже принята", code="revise_accepted")

    monkeypatch.setattr(revision, "editable", принятая)

    ответ = стенд.post("/inspections/x/suggest", data={"text": "пол"}, headers=ORIGIN)

    assert ответ.status_code == 409
    assert ответ.get_json()["error"] == "refused"


@админ
def test_подбор_отвечает_карточками_и_ничего_не_записывает(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    _приёмка(monkeypatch)
    _лист(monkeypatch)
    зовы = _двери_записи(monkeypatch)
    деталь = карточка(шапка())
    monkeypatch.setattr(revision, "editable", lambda *_a, **_k: деталь)
    увидено: dict[str, Any] = {}

    def подобрать(head: Any, sheet: Any, *, words: str, frames: list[bytes], lang: str) -> dict:
        увидено.update(words=words, frames=len(frames), lang=lang)
        return {"via": "model", "candidates": [], "question": "", "hidden": 0}

    monkeypatch.setattr(proofread, "suggest", подобрать)

    # Act
    ответ = стенд.post(
        "/inspections/x/suggest",
        data={"text": "грязный пол", "photo": _файл()},
        headers=ORIGIN,
        content_type="multipart/form-data",
    )

    # Assert — подсказка получена, а запись не заведена и ничто не пересчитано.
    assert ответ.status_code == 200 and ответ.get_json()["via"] == "model"
    assert увидено == {"words": "грязный пол", "frames": 1, "lang": "ru"}
    assert зовы == []


def _предложение(*кандидаты: Candidate) -> Offer:
    return Offer(via="model", candidates=tuple(кандидаты))


@pytest.fixture
def подбор(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Тот же `propose`, подменённый на границе; зоны пункта — из «методики» набора."""
    состояние: dict[str, Any] = {"offer": _предложение(), "зовы": 0}

    def propose(*_a: Any, **kw: Any) -> Offer:
        состояние["зовы"] += 1
        состояние["kw"] = kw
        if isinstance(состояние["offer"], Exception):
            raise состояние["offer"]
        return состояние["offer"]

    monkeypatch.setattr(proofread, "propose", propose)
    monkeypatch.setattr(proofread, "zone_from_words", lambda *_a, **_k: None)
    monkeypatch.setattr(walk_suggest, "allowed_zones", lambda *_a, **_k: ("KITCHEN", "HALL"))
    return состояние


def _лист_с_пунктами() -> review.Sheet:
    пункты = (
        {"id": "CLN02", "kind": "violation", "question_ru": "Пол", "levels": "D1,D2", "zones": "*"},
    )
    зоны = ({"code": "KITCHEN", "name_ru": "Кухня"}, {"code": "HALL", "name_ru": "Зал"})
    return review.build_sheet(items=пункты, zones=зоны, lang="ru")


def _подобрать(**kw: Any) -> dict[str, Any]:
    return proofread.suggest(
        шапка(), _лист_с_пунктами(), **{"words": "пол", "frames": [], "lang": "ru", **kw}
    )


def test_подбор_показывает_только_пункты_версии_и_допустимые_классы(
    подбор: dict[str, Any],
) -> None:
    # Arrange — второй пункт в версии проверки отсутствует, у первого класс D3 недопустим.
    подбор["offer"] = _предложение(
        Candidate(code="CLN02", level="D3", zone="HALL", wording="пол грязный", confidence=0.9),
        Candidate(code="ZZZ99", level="D1", zone="KITCHEN", wording="чужой", confidence=0.8),
    )

    # Act
    ответ = _подобрать()

    # Assert
    [карточка_] = ответ["candidates"]
    assert (карточка_["code"], карточка_["title"]) == ("CLN02", "Пол")
    assert карточка_["level"] == "" and карточка_["levels"] == ["D1", "D2"]
    assert (карточка_["zone"], карточка_["zone_name"]) == ("HALL", "Зал")
    assert ответ["hidden"] == 1
    assert подбор["kw"]["chat_id"] == шапка().chat_id


def test_подбор_без_слов_и_кадров_отказывает_не_зовя_модель(подбор: dict[str, Any]) -> None:
    with pytest.raises(proofread.SuggestRefused) as отказ:
        _подобрать(words="  ")
    assert отказ.value.key == "proofread.suggest.empty" and подбор["зовы"] == 0


def test_недоступная_модель_отвечает_словами_а_не_падает(подбор: dict[str, Any]) -> None:
    подбор["offer"] = ModelUnavailable("нет ключа")

    with pytest.raises(proofread.SuggestRefused) as отказ:
        _подобрать()

    assert отказ.value.key == "proofread.suggest.failed" and отказ.value.status == 503


def test_кадр_не_изображение_отказ_до_модели(подбор: dict[str, Any]) -> None:
    with pytest.raises(proofread.SuggestRefused) as отказ:
        _подобрать(frames=[b"not an image"])
    assert отказ.value.key == "photo.unreadable" and подбор["зовы"] == 0


def test_подбор_после_отказа_снова_доступен(подбор: dict[str, Any]) -> None:
    подбор["offer"] = ModelUnavailable("нет ключа")
    with pytest.raises(proofread.SuggestRefused):
        _подобрать()
    подбор["offer"] = _предложение()
    assert _подобрать()["candidates"] == []


# --- запись заводит человек: без выбранного пункта — нет -----------------------


@админ
def test_добавление_без_пункта_не_принимается_и_ничего_не_пишет(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Подсказка — не запись: форма без выбранного пункта доходит до сверки и отклоняется."""
    _приёмка(monkeypatch)
    записано: list[str] = []

    def сверка(*_a: Any, **kw: Any) -> None:
        # Как настоящая `add_card`: пункт назван человеком или записи нет.
        if not kw["code"].strip():
            raise ReviseError(
                "Пункта нарушения в чек-листе версии нет",
                code="revise_no_item",
                params={"item": "—"},
            )
        записано.append(kw["code"])

    monkeypatch.setattr(revision, "add_card", сверка)

    ответ = стенд.post(
        "/inspections/x/findings", data={**ФОРМА, "code": ""}, headers={**ORIGIN, "X-Panel": "1"}
    )

    assert "Запись не добавлена" in ответ.get_data(as_text=True)
    assert записано == []


@админ
def test_несколько_кадров_нового_нарушения_доходят_до_двери(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _приёмка(monkeypatch)
    ушло: dict[str, Any] = {}
    monkeypatch.setattr(revision, "add_card", lambda *_a, **kw: ушло.update(kw) or "new")

    ответ = стенд.post(
        "/inspections/x/findings",
        data={**ФОРМА, "photo": [_файл("a.jpg"), _файл("b.jpg"), _файл("c.jpg")]},
        headers=ORIGIN,
        content_type="multipart/form-data",
    )

    assert ответ.status_code == 200
    assert ушло["photo"] is not None and len(ушло["more_photos"]) == 2


@админ
def test_кадров_больше_чем_у_записи_отказ_до_двери(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _приёмка(monkeypatch)
    зовы = _двери_записи(monkeypatch)

    ответ = стенд.post(
        "/inspections/x/findings",
        data={**ФОРМА, "photo": [_файл(f"{n}.jpg") for n in range(11)]},
        headers=ORIGIN,
        content_type="multipart/form-data",
    )

    assert "не больше 10 кадров" in ответ.get_data(as_text=True)
    assert зовы == []


# --- правка записи на месте: пересчёт только когда есть что менять -------------


def _исправление(стенд: FlaskClient, **поля: Any) -> str:
    форма = {
        "code": ЗАПИСЬ.code,
        "level": ЗАПИСЬ.level,
        "zone": ЗАПИСЬ.zone or "",
        "text": ЗАПИСЬ.text or "",
        **поля,
    }
    return стенд.post(
        f"/inspections/x/findings/{ЗАПИСЬ.id}/revise",
        data=форма,
        headers=ORIGIN,
        content_type="multipart/form-data",
    ).get_data(as_text=True)


@админ
def test_правка_без_изменений_не_пересчитывает(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _приёмка(monkeypatch)
    зовы = _двери_записи(monkeypatch)

    страница = _исправление(стенд)

    assert зовы == [] and "ничего не изменилось" in страница


@админ
def test_правка_текста_пересчитывает_и_кадры_меняются_той_же_формой(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _приёмка(monkeypatch)
    зовы: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(revision, "revise_card", lambda *_a, **kw: зовы.append(("revise", kw)))
    monkeypatch.setattr(revision, "change_photos", lambda *_a, **kw: зовы.append(("photos", kw)))

    ответ = стенд.post(
        f"/inspections/x/findings/{ЗАПИСЬ.id}/revise",
        data={
            "code": ЗАПИСЬ.code,
            "level": ЗАПИСЬ.level,
            "zone": ЗАПИСЬ.zone or "",
            "text": "иначе сказано",
            "remove_photo": ["p1", "p2"],
            "photo": _файл(),
        },
        headers=ORIGIN,
        content_type="multipart/form-data",
    )

    assert [имя for имя, _ in зовы] == ["revise", "photos"]
    assert зовы[0][1]["text"] == "иначе сказано"
    assert зовы[1][1]["remove"] == ["p1", "p2"] and len(зовы[1][1]["add"]) == 1
    assert "Запись исправлена, оценка пересчитана." in ответ.get_data(as_text=True)


@админ
def test_отказ_пересчёта_не_трогает_кадры(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _приёмка(monkeypatch)
    зовы = _двери_записи(monkeypatch)

    def отказать(*_a: Any, **_k: Any) -> None:
        raise ReviseError(
            "Класс D3 для пункта не предусмотрен",
            code="revise_bad_level",
            params={"level": "D3", "item": "CLN05", "allowed": "D1"},
        )

    monkeypatch.setattr(revision, "revise_card", отказать)

    страница = стенд.post(
        f"/inspections/x/findings/{ЗАПИСЬ.id}/revise",
        data={
            "code": ЗАПИСЬ.code,
            "level": "D3",
            "zone": ЗАПИСЬ.zone or "",
            "text": "иначе",
            "remove_photo": ["p1"],
        },
        headers=ORIGIN,
        content_type="multipart/form-data",
    ).get_data(as_text=True)

    assert "Запись не исправлена" in страница
    assert "change_photos" not in зовы


def test_подбор_пока_идёт_в_другом_процессе_отказ_и_чат_не_заперт(
    подбор: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """F-110: занятость между процессами держит замок базы, а не набор в памяти."""
    monkeypatch.setattr(proofread, "try_hold", lambda *_a: Hold(acquired=False))

    with pytest.raises(proofread.SuggestRefused) as отказ:
        _подобрать()

    assert (отказ.value.key, отказ.value.status) == ("proofread.suggest.busy", 429)
    assert proofread._busy.held == set(), "отказ запер проверку в этом процессе навсегда"
    assert подбор["зовы"] == 0, "модель вызвана, хотя подбор идёт в другом процессе"
