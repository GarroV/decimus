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
    FEEDBACK_LANG_FIELD,
    FROM_SNAPSHOT,
    PLAN_DUE_FIELD,
    LetterError,
    Papers,
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
    monkeypatch.setattr(data, "letter_sources", lambda: Papers(live=None, store=None))
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


def test_карточка_ведёт_к_письму(стенд: FlaskClient) -> None:
    # Act
    страница = стенд.get(f"/inspections/{ПРОВЕРКА}").get_data(as_text=True)

    # Assert
    assert f"inspection={ПРОВЕРКА}&amp;view=letter" in страница


def test_выбранный_язык_доезжает_до_сборщика(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Язык письма — параметр, и он обязан доехать до того, кто его исполняет.

    Потерянный по дороге, он молчит: экран покажет письмо на языке отчёта
    проверки, подпишет его выбранным языком и не скажет ничего.
    """
    # Arrange
    спрошено: list[str | None] = []

    def запомнить(
        _detail: Any, *, lang: str | None, papers: Any, template: int | None = None
    ) -> dict[str, object]:
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

    def запомнить(
        _detail: Any, *, lang: str | None, papers: Any, template: int | None = None
    ) -> dict[str, object]:
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


# --- письмо в панели реестра (владелец 20.10.2026: «просто выплывала справа») -----


def test_письмо_открывается_в_панели_реестра(стенд: FlaskClient) -> None:
    # Act
    страница = стенд.get(f"/inspections?inspection={ПРОВЕРКА}&view=letter&lang=ru").get_data(
        as_text=True
    )

    # Assert — письмо в панели, переходы остаются в ней, сохранение — фоном.
    панель = страница.split("spanel--letter", 1)[1]
    assert "Your inspection scored 92%." in панель
    assert "lt--panel" in панель and "data-panel-form" in панель
    назад = панель.split('class="back"', 1)[1].split(">", 1)[0]
    assert f"inspection={ПРОВЕРКА}" in назад and "view=letter" not in назад
    assert "data-drawer-open" in назад
    языки = панель.split("data-pick-nav", 1)[1].split("</select>", 1)[0]
    assert "view=letter" in языки and "data-drawer-open" in языки.split(">", 1)[0]
    # Черновик в почте уходит обычной отправкой: окно согласия Google фоном не открыть.
    assert "data-full-submit" in панель


def test_без_вида_письма_в_панели_карточка(стенд: FlaskClient) -> None:
    страница = стенд.get(f"/inspections?inspection={ПРОВЕРКА}&lang=ru").get_data(as_text=True)
    assert "spanel--letter" not in страница
    кнопка = страница.split('data-tip="Письмо партнёру"', 1)[0].rsplit("<a ", 1)[1]
    assert "view=letter" in кнопка and "data-drawer-open" in кнопка


def test_у_загруженной_задним_числом_вместо_письма_карточка(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D310: письма у заведённой задним числом нет — и в панели тоже."""
    monkeypatch.setattr(data, "load_card", lambda *_a, **_k: карточка(шапка(origin="import")))
    страница = стенд.get(f"/inspections?inspection={ПРОВЕРКА}&view=letter&lang=ru").get_data(
        as_text=True
    )
    assert "spanel--letter" not in страница
    assert "Demo Pizzeria #1" in страница


def test_сохранение_возвращает_в_панель_письма(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(data, "remember_letter", lambda *_a, **_k: None)
    ответ = стенд.post(
        f"/inspections/{ПРОВЕРКА}/letter/save",
        data={"text": "Текст", "letter_lang": "en"},
        headers=СВОЙ,
    )
    куда = ответ.headers["Location"]
    assert ответ.status_code == 303
    assert куда.startswith("/inspections?") and "view=letter" in куда and "saved=ok" in куда


def test_со_страницы_письма_назад_в_реестр_а_не_на_карточку(стенд: FlaskClient) -> None:
    страница = стенд.get(f"/inspections/{ПРОВЕРКА}/letter?lang=ru").get_data(as_text=True)
    назад = страница.split('class="back"', 1)[1].split(">", 1)[0]
    assert f"/inspections?inspection={ПРОВЕРКА}" in назад


# --- шаблон письма и язык обратной связи (D663, D664) --------------------------


def test_переключатель_шаблона_и_выбор_доезжает_до_сборщика(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Шаблон 1 и 2 предлагаются; выбранный уходит сборщику, а не теряется на странице."""
    # Arrange
    запросы: list[object] = []

    def сборка(*_a: object, **k: object) -> dict[str, object]:
        запросы.append(k.get("template"))
        return собранное()

    monkeypatch.setattr(data, "build_letter", сборка)

    # Act
    обычная = стенд.get(f"/inspections/{ПРОВЕРКА}/letter").get_data(as_text=True)
    второй = стенд.get(f"/inspections/{ПРОВЕРКА}/letter?letter_template=2").get_data(as_text=True)

    # Assert — оба шаблона в списке, по умолчанию не выбран явно ничего.
    assert "Шаблон 1" in обычная and "Шаблон 2" in обычная
    assert "letter_template=2" in обычная
    assert запросы == [None, 2], "шаблон не дошёл до сборщика письма"
    # Явный выбор переезжает в адреса языка: смена языка не сбрасывает шаблон.
    assert "letter_lang=en&amp;letter_template=2" in второй


def test_выбор_шаблона_не_трогает_сохранённое_письмо(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Сохранённое письмо правится по умолчанию; выбор шаблона — явное действие.

    Он показывает в поле свежую пересборку, а запись остаётся на месте: письмо
    партнёру могло уже уйти, и подменять его без команды человека нельзя.
    """
    # Arrange
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
    выбран = стенд.get(f"/inspections/{ПРОВЕРКА}/letter?letter_template=2").get_data(as_text=True)

    # Assert
    assert "Правленое человеком письмо" in обычная
    assert "Правленое человеком письмо" not in выбран
    assert "Your inspection scored 92%." in выбран
    assert "director" in выбран, "запись исчезла из виду"


def test_обратная_связь_не_на_языке_письма_называется_словами(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Блок не вставлен — отправитель видит это на экране до отправки (D663)."""
    # Arrange
    monkeypatch.setattr(
        data,
        "build_letter",
        lambda *_a, **_k: собранное(not_restored=[FEEDBACK_LANG_FIELD], ready_to_send=False),
    )

    # Act
    страница = стенд.get(f"/inspections/{ПРОВЕРКА}/letter").get_data(as_text=True)

    # Assert
    assert "Отправлять как есть нельзя" in страница
    assert "обратная связь аудитора" in страница and "не вставлена" in страница
    assert FEEDBACK_LANG_FIELD not in страница, "код сборщика попал на экран вместо слов"
