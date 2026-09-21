"""Экран письма партнёру: что он обязан сказать вслух.

Разметку здесь не сторожим. Сторожим ровно то, чья ошибка молчит, а платит за
неё партнёр — человек вне продукта, который получит письмо и будет считать
написанное фактом:

* **«собралось» и «можно отправлять» — разные ответы**, и второй сказан вслух.
  Письмо с пустой шапкой или подставленным сроком выглядит законченным: связный
  текст, верная оценка, подпись. Заметить по нему, что срок в нём не тот,
  который аудитор назвал партнёру, не по чему;
* **незнакомая оговорка не пропадает** — каждая из них причина, по которой
  отправлять нельзя, и молчание о ней возвращает экран к виду «всё хорошо»;
* **выгружается правленое, а не собранное** — иначе человек правит опечатку,
  скачивает файл и отправляет ровно то, что правил;
* **чужую проверку выгрузка не отдаёт** — ни своим текстом, ни чужим;
* **отказ сборщика не роняет экран** — методики нужной версии может не
  оказаться на диске, и это обычный исход.

Сборщик писем подменяется на границе `src/web/inspections.py`: сам он зовёт
движок подпроцессом, и его собственные правила проверяет `tests/test_mcp_letters.py`.
Шапка проверки берётся из `test_web_app.py`, а не копируется сюда: две копии
одной правдоподобной проверки разъедутся молча.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from flask.testing import FlaskClient
from test_web_app import ТЕНАНТ, карточка, шапка
from web_harness import войти, подменить_двери, собрать

from src.domain.models import TEXT_LANGS
from src.report.letters import (
    BLANK_TEXT_FIELD,
    FROM_SNAPSHOT,
    PLAN_DUE_FIELD,
    LetterError,
)
from src.web import inspections as data

ПРОВЕРКА = "11111111-1111-1111-1111-111111111111"
#: Происхождение своей же страницы. Браузер ставит его сам, а заслон
#: (`src/web/origin.py`) без него отправку не пропустит — и правильно делает.
СВОЙ = {"Origin": "http://localhost"}
ТЕКСТ = "Dear partner,\n\nYour inspection scored 92%.\n\nRegards"


def собранное(**поля: Any) -> dict[str, object]:
    """Ответ сборщика письма в его собственной форме — словарём."""
    основа: dict[str, object] = {
        "lang": "en",
        "report_lang": "en",
        "checklist_version": "2026.09",
        "methodology": FROM_SNAPSHOT,
        "score_verified": True,
        "pct": 92.0,
        "grade": "B",
        "letter": ТЕКСТ,
        "not_restored": [],
        "ready_to_send": True,
        "status": "letter rebuilt",
    }
    основа.update(поля)
    return основа


@pytest.fixture
def стенд(monkeypatch: pytest.MonkeyPatch) -> Iterator[FlaskClient]:
    """Приложение с записанной проверкой, готовым письмом и вошедшим человеком."""
    monkeypatch.setattr(data, "retraction_available", lambda: True)
    monkeypatch.setattr(data, "load_registry", lambda **_: data.Registry((), True))
    monkeypatch.setattr(data, "load_card", lambda *_a, **_k: карточка(шапка()))
    monkeypatch.setattr(data, "letter_sources", lambda: None)
    monkeypatch.setattr(data, "build_letter", lambda *_a, **_k: собранное())
    подменить_двери(monkeypatch, tenant=ТЕНАНТ)
    with собрать(tenant=ТЕНАНТ).test_client() as client:
        assert войти(client).status_code == 302
        yield client


def test_готовое_письмо_показывается_целиком(стенд: FlaskClient) -> None:
    # Act
    страница = стенд.get(f"/inspections/{ПРОВЕРКА}/letter").get_data(as_text=True)

    # Assert — текст движка уезжает на экран как есть, без склейки в шаблоне.
    assert "Your inspection scored 92%." in страница
    assert "готово к отправке" in страница


def test_неготовое_письмо_называет_причины_словами(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Самый дорогой случай: письмо собралось и отправлять его нельзя.

    Подставленный срок не отличается в тексте ни от чего: партнёр получит от
    управляющей компании дату, которой аудитор ему не называл.
    """
    # Arrange
    monkeypatch.setattr(
        data,
        "build_letter",
        lambda *_a, **_k: собранное(not_restored=["auditor", PLAN_DUE_FIELD], ready_to_send=False),
    )

    # Act
    страница = стенд.get(f"/inspections/{ПРОВЕРКА}/letter").get_data(as_text=True)

    # Assert — и заголовок отказа, и обе причины на языке интерфейса.
    assert "Отправлять как есть нельзя" in страница
    assert "не восстановлено имя аудитора" in страница
    assert "подставлен расчётом" in страница
    assert "готово к отправке" not in страница


def test_незнакомая_оговорка_не_пропадает(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Подписи для кода ещё нет — код показывается сам.

    Пропажа здесь дороже некрасивой строки: экран вернулся бы к виду «всё
    хорошо» ровно там, где сборщик сказал обратное.
    """
    # Arrange
    monkeypatch.setattr(
        data,
        "build_letter",
        lambda *_a, **_k: собранное(not_restored=["невиданный-код"], ready_to_send=False),
    )

    # Act
    страница = стенд.get(f"/inspections/{ПРОВЕРКА}/letter").get_data(as_text=True)

    # Assert
    assert "невиданный-код" in страница


def test_пустая_формулировка_названа_отдельно(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    monkeypatch.setattr(
        data,
        "build_letter",
        lambda *_a, **_k: собранное(not_restored=[BLANK_TEXT_FIELD], ready_to_send=False),
    )

    # Act
    страница = стенд.get(f"/inspections/{ПРОВЕРКА}/letter").get_data(as_text=True)

    # Assert — про находку без слов сказано, что дописать их может только аудитор.
    assert "ни на одном языке" in страница


def test_отказ_сборщика_не_роняет_экран(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — методики той версии на диске нет, и это обычный исход.
    def отказать(*_a: Any, **_k: Any) -> dict[str, object]:
        raise LetterError("Снимок методики версии 2026.09 не найден")

    monkeypatch.setattr(data, "build_letter", отказать)

    # Act
    ответ = стенд.get(f"/inspections/{ПРОВЕРКА}/letter")

    # Assert — страница, а не 500-я, и причина словами.
    assert ответ.status_code == 200
    assert "Снимок методики версии 2026.09 не найден" in ответ.get_data(as_text=True)


def test_выгружается_правленое_а_не_собранное(стенд: FlaskClient) -> None:
    """Человек поправил — уехало поправленное.

    Обратное молчит: файл скачался, выглядит письмом, и правка в нём пропала.
    """
    # Arrange
    правленое = ТЕКСТ.replace("92%", "92,0 %")

    # Act
    ответ = стенд.post(f"/inspections/{ПРОВЕРКА}/letter", data={"text": правленое}, headers=СВОЙ)

    # Assert
    assert ответ.status_code == 200
    assert ответ.get_data(as_text=True) == правленое
    assert "attachment" in ответ.headers["Content-Disposition"]
    assert ответ.headers["X-Content-Type-Options"] == "nosniff"
    # Кодировка названа ровно один раз. Дважды — не косметика: заголовок с
    # повтором часть получателей разбирает как имя кодировки «utf-8; charset=utf-8»
    # и откатывается на латиницу, то есть письмо приезжает нечитаемым.
    assert ответ.headers["Content-Type"] == "text/plain; charset=utf-8"


def test_выгрузка_чужой_проверки_отказывает(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Проверки этого арендатора нет — отдавать нечего и не из чего.

    Без этой двери страница выгрузки принимала бы любой присланный текст и
    отдавала его файлом с адреса самой админки.
    """
    # Arrange
    monkeypatch.setattr(data, "load_card", lambda *_a, **_k: None)

    # Act
    ответ = стенд.post("/inspections/чужая/letter", data={"text": "что угодно"}, headers=СВОЙ)

    # Assert
    assert ответ.status_code == 404
    assert "что угодно" not in ответ.get_data(as_text=True)


def test_имя_файла_не_дописывает_заголовок(стенд: FlaskClient) -> None:
    """Идентификатор приходит из адреса, то есть снаружи.

    Кавычка или перевод строки в нём — это уже не имя файла, а дописанный
    заголовок ответа.
    """
    # Act
    ответ = стенд.post('/inspections/a"b/letter', data={"text": ТЕКСТ}, headers=СВОЙ)

    # Assert
    расположение = ответ.headers["Content-Disposition"]
    assert расположение == 'attachment; filename="letter-ab.txt"'


def test_карточка_ведёт_к_письму(стенд: FlaskClient) -> None:
    # Act
    страница = стенд.get(f"/inspections/{ПРОВЕРКА}").get_data(as_text=True)

    # Assert
    assert f"/inspections/{ПРОВЕРКА}/letter" in страница


def test_выбранный_язык_доезжает_до_сборщика(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Язык письма — параметр, и он обязан доехать до того, кто его исполняет.

    Потерянный по дороге, он молчит: экран покажет письмо на языке отчёта
    проверки, подпишет его выбранным языком и не скажет ничего.
    """
    # Arrange
    спрошено: list[str | None] = []

    def запомнить(_detail: Any, *, lang: str | None, papers: Any) -> dict[str, object]:
        спрошено.append(lang)
        return собранное(lang=lang or "en")

    monkeypatch.setattr(data, "build_letter", запомнить)

    # Act
    стенд.get(f"/inspections/{ПРОВЕРКА}/letter?letter_lang=ru")

    # Assert
    assert спрошено == ["ru"]


def test_язык_по_умолчанию_это_язык_отчёта_проверки(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Не спросили — не подставляем свой. Язык выбирает проверка, а не админка."""
    # Arrange
    спрошено: list[str | None] = []

    def запомнить(_detail: Any, *, lang: str | None, papers: Any) -> dict[str, object]:
        спрошено.append(lang)
        return собранное()

    monkeypatch.setattr(data, "build_letter", запомнить)

    # Act
    стенд.get(f"/inspections/{ПРОВЕРКА}/letter")

    # Assert — `None` значит «решает проверка» (`src/report/letters.py: _lang`).
    assert спрошено == [None]


def test_переключатель_предлагает_только_языки_методики(стенд: FlaskClient) -> None:
    """Язык, которого в методике нет, предлагать нельзя.

    Предложенный, он кончается отказом сборщика на ровном месте — человек
    нажал то, что ему показали.
    """
    # Act
    страница = стенд.get(f"/inspections/{ПРОВЕРКА}/letter").get_data(as_text=True)

    # Assert
    for код in TEXT_LANGS:
        assert f"letter_lang={код}" in страница
    assert "letter_lang=fr" not in страница


def test_возврат_к_заготовке_показывает_её_не_трогая_записанного(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — письмо уже зафиксировано человеком, и оно НЕ совпадает с тем,
    # что собирает движок сегодня.
    записанное = SimpleNamespace(
        id="1",
        body="Правленое человеком письмо",
        lang="en",
        saved_by="director",
        created_at=datetime(2026, 9, 21, 12, 0, tzinfo=UTC),
    )
    monkeypatch.setattr(data, "saved_letter", lambda *_a, **_k: записанное)

    # Act
    обычная = стенд.get(f"/inspections/{ПРОВЕРКА}/letter").get_data(as_text=True)
    заготовка = стенд.get(f"/inspections/{ПРОВЕРКА}/letter?draft=1").get_data(as_text=True)

    # Assert — по умолчанию правится зафиксированное: подменять его сегодняшней
    # пересборкой значит отвечать на «что мы отправили» правдоподобной неправдой.
    assert "Правленое человеком письмо" in обычная
    assert "Вернуть заготовку" in обычная

    # А по прямой просьбе в поле — свежая заготовка движка.
    assert "Your inspection scored 92%." in заготовка

    # При этом запись НЕ исчезла и не подменена: письмо партнёру могло уже
    # уйти, и вынуть его из истории нельзя ничем. На экране по-прежнему видно,
    # что зафиксированное существует.
    assert "director" in заготовка
