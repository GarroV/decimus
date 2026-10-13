"""Этап приёмки в админке (D199) и правка записи на приёмке (D200).

Проверяется поверхность: кто видит кнопки, кто может отправить форму, что
доходит до двери блока `db` и как показан отказ. Подтверждает и правит только
админ своего пространства (D283); УК видит ждущую партнёра на чтение.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from typing import Any

import pytest
from flask.testing import FlaskClient
from test_web_app import ПУСТАЯ_СЕТЬ, ТЕНАНТ, карточка, шапка
from test_web_letter import собранное
from web_harness import ЛОГИН, войти, подменить_двери, собрать

from src.db.errors import AcceptError, ReviseError
from src.db.previews import FindingShots
from src.domain.tenants import canonical_tenant
from src.report.letters import Papers
from src.web import country as country_data
from src.web import inspections as data
from src.web import overview as overview_data
from src.web import review, revision

ORIGIN = {"Origin": "http://localhost"}
ЧУЖОЕ = "GE"


@pytest.fixture
def стенд(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> Iterator[FlaskClient]:
    """Тот же стенд, что у `test_web_app`: двери подменены, человек уже вошёл."""
    monkeypatch.setattr(data, "retraction_available", lambda: True)
    monkeypatch.setattr(data, "load_registry", lambda **_: data.Registry((), True))
    monkeypatch.setattr(overview_data, "load", lambda **_: ПУСТАЯ_СЕТЬ)
    monkeypatch.setattr(country_data, "countries", lambda **_: ())
    monkeypatch.setattr(data, "load_card", lambda *_a, **_k: None)
    подменить_двери(monkeypatch, tenant=ТЕНАНТ, role=getattr(request, "param", "developer"))
    with собрать(tenant=ТЕНАНТ).test_client() as client:
        assert войти(client).status_code == 302
        yield client


админ = pytest.mark.parametrize("стенд", ["admin"], indirect=True)


def _приёмка(
    monkeypatch: pytest.MonkeyPatch, *, ждёт: bool = True, пространство: str = ТЕНАНТ
) -> list[dict[str, Any]]:
    вызовы: list[dict[str, Any]] = []

    def подтвердить(inspection_id: str, **kw: Any) -> None:
        вызовы.append({"id": inspection_id, **kw})

    деталь = карточка(шапка(on_review=ждёт, tenant_code=пространство))
    monkeypatch.setattr(data, "accept_card", подтвердить)
    monkeypatch.setattr(data, "load_moves", lambda *_a, **_k: ())
    monkeypatch.setattr(data, "load_units", lambda **_: ())
    monkeypatch.setattr(data, "load_card", lambda *_a, **_k: деталь)
    return вызовы


def _правка(monkeypatch: pytest.MonkeyPatch, **kw: Any) -> list[dict[str, Any]]:
    вызовы: list[dict[str, Any]] = []

    def исправить(inspection_id: str, finding_id: str, **поля: Any) -> None:
        вызовы.append({"id": inspection_id, "finding": finding_id, **поля})

    _приёмка(monkeypatch, **kw)
    monkeypatch.setattr(revision, "revise_card", исправить)
    return вызовы


def _лист(monkeypatch: pytest.MonkeyPatch) -> None:
    """Лист из настоящего `build_sheet`; подменён только чек-лист."""
    пункты = ({"id": "CLN02", "kind": "violation", "question_ru": "Пол", "zones": "*"},)
    зоны = ({"code": "KITCHEN", "name_ru": "Кухня", "name_en": "Kitchen"},)
    monkeypatch.setattr(
        review,
        "load_sheet",
        lambda _h, findings, **kw: review.build_sheet(
            items=пункты, zones=зоны, findings=findings, lang=kw["lang"]
        ),
    )


ИСПРАВЛЕНИЕ = {"code": "CLN05", "level": "D2", "zone": "KITCHEN", "text": "пол в зале"}


# --- подтверждение (D199) ----------------------------------------------------


@админ
def test_администратор_подтверждает_и_подпись_берётся_из_сессии(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    вызовы = _приёмка(monkeypatch)

    # Act — подпись из формы не принимается: её подставляет вход.
    ответ = стенд.post("/inspections/x/accept", data={"actor": "подлог"}, headers=ORIGIN)

    # Assert
    assert ответ.status_code == 200
    assert вызовы == [{"id": "x", "tenant": canonical_tenant(ТЕНАНТ), "actor": ЛОГИН}]
    assert "Проверка принята." in ответ.get_data(as_text=True)


@админ
def test_ждущая_своя_показана_с_плашкой_листом_и_кнопкой_без_переноса(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    _приёмка(monkeypatch)
    _лист(monkeypatch)

    # Act
    страница = стенд.get("/inspections/x").get_data(as_text=True)

    # Assert — принять, исправить и отклонить можно (D465); переносить до приёмки нечего.
    assert "Проверка на приёмке" in страница
    assert "/accept?lang=" in страница
    assert "/findings/f1/revise?lang=" in страница
    assert "Сохранить и пересчитать" in страница
    assert "/move?lang=" not in страница
    assert "/retract?lang=" in страница


@админ
def test_лист_вычитки_показывает_кадры_и_называет_недоступные(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#422: вычитывающий видит кадр записи и то, что ещё один показать нечем."""
    # Arrange
    _приёмка(monkeypatch)
    _лист(monkeypatch)
    кадр = "22222222-2222-2222-2222-222222222222"
    находка = карточка(шапка()).findings[0].id
    monkeypatch.setattr(
        data, "load_previews", lambda *_a, **_k: {находка: FindingShots(shown=(кадр,), missing=1)}
    )

    # Act
    страница = стенд.get("/inspections/x").get_data(as_text=True)

    # Assert — в листе миниатюра и пометка; в записях пометка в строке счётчика.
    assert 'class="review-photo"' in страница
    assert f"/photos/{кадр}" in страница
    assert страница.count("Фото недоступно: 1") == 1
    assert "Фото: 1 · недоступно: 1" in страница


@админ
def test_ждущая_чужого_пространства_только_на_чтение(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """УК видит ждущую партнёра (D283): лист есть, кнопок приёмки и правки нет."""
    # Arrange
    вызовы = _приёмка(monkeypatch, пространство=ЧУЖОЕ)
    _лист(monkeypatch)

    # Act
    страница = стенд.get("/inspections/x").get_data(as_text=True)
    ответ = стенд.post("/inspections/x/accept", headers=ORIGIN)

    # Assert
    assert "Весь чек-лист" in страница
    assert "только для чтения" in страница
    assert "/accept?lang=" not in страница
    assert "/revise?lang=" not in страница
    assert ответ.status_code == 403
    assert вызовы == []


@админ
def test_принятой_проверке_кнопки_подтверждения_нет(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _приёмка(monkeypatch, ждёт=False)
    страница = стенд.get("/inspections/x").get_data(as_text=True)
    assert "/accept?lang=" not in страница
    assert "Проверка на приёмке" not in страница
    assert "Принята" in страница


@pytest.mark.parametrize("стенд", ["guest"], indirect=True)
def test_гость_не_подтверждает(стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange — приёмку ведёт бизнес-девелопер (D440), поэтому отказ держим на госте.
    вызовы = _приёмка(monkeypatch)

    # Act
    ответ = стенд.post("/inspections/x/accept", headers=ORIGIN)
    страница = стенд.get("/inspections/x").get_data(as_text=True)

    # Assert
    assert ответ.status_code == 403
    assert вызовы == []
    assert "/accept" not in страница


@админ
def test_отказ_подтверждения_показан_текстом(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    _приёмка(monkeypatch)

    def отказать(*_a: Any, **_k: Any) -> None:
        raise AcceptError("Проверка x уже принята — подтверждать второй раз нечего")

    monkeypatch.setattr(data, "accept_card", отказать)

    # Act
    ответ = стенд.post("/inspections/x/accept", headers=ORIGIN)

    # Assert
    assert "уже принята" in ответ.get_data(as_text=True)


def test_реестр_показывает_ждущих_приёмки_отдельным_блоком(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    ждущая = шапка(unit_name="Ждущая точка", on_review=True)
    monkeypatch.setattr(
        data, "load_registry", lambda **_: data.Registry((шапка(),), True, review=(ждущая,))
    )

    # Act
    страница = стенд.get("/inspections").get_data(as_text=True)

    # Assert
    assert "Ждут приёмки" in страница
    assert "Ждущая точка" in страница


# --- правка записи на приёмке (D200) ------------------------------------------


@админ
def test_администратор_исправляет_запись_своего_пространства(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    вызовы = _правка(monkeypatch)

    # Act
    ответ = стенд.post("/inspections/x/findings/f1/revise", data=ИСПРАВЛЕНИЕ, headers=ORIGIN)

    # Assert
    assert ответ.status_code == 200
    assert вызовы == [
        {
            "id": "x",
            "finding": "f1",
            "tenant": canonical_tenant(ТЕНАНТ),
            "lang": "ru",
            **ИСПРАВЛЕНИЕ,
        }
    ]
    assert "Запись исправлена, оценка пересчитана." in ответ.get_data(as_text=True)


@админ
def test_запись_чужого_пространства_не_исправляется(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    вызовы = _правка(monkeypatch, пространство=ЧУЖОЕ)
    ответ = стенд.post("/inspections/x/findings/f1/revise", data=ИСПРАВЛЕНИЕ, headers=ORIGIN)
    assert ответ.status_code == 403
    assert вызовы == []


@pytest.mark.parametrize("стенд", ["guest"], indirect=True)
def test_гость_записи_не_исправляет(стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch) -> None:
    вызовы = _правка(monkeypatch)
    ответ = стенд.post("/inspections/x/findings/f1/revise", data=ИСПРАВЛЕНИЕ, headers=ORIGIN)
    assert ответ.status_code == 403
    assert вызовы == []


@админ
def test_отказ_правки_показан_текстом(стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    _правка(monkeypatch)

    def отказать(*_a: Any, **_k: Any) -> None:
        raise ReviseError("Класс D3 для пункта CLN05 не предусмотрен")

    monkeypatch.setattr(revision, "revise_card", отказать)

    # Act
    ответ = стенд.post("/inspections/x/findings/f1/revise", data=ИСПРАВЛЕНИЕ, headers=ORIGIN)

    # Assert
    assert "Запись не исправлена: Класс D3 для пункта CLN05 не предусмотрен" in ответ.get_data(
        as_text=True
    )


@админ
def test_запись_вне_чек_листа_тоже_исправляется(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Запись, перенесённую в необычную зону, лист показывает отдельно — с формой правки."""
    # Arrange — пункт записи в чек-листе только в зале, а запись — на кухне.
    _приёмка(monkeypatch)
    пункты = ({"id": "CLN02", "kind": "violation", "question_ru": "Пол", "zones": "HALL"},)
    зоны = (
        {"code": "KITCHEN", "name_ru": "Кухня", "name_en": "Kitchen"},
        {"code": "HALL", "name_ru": "Зал", "name_en": "Hall"},
    )
    monkeypatch.setattr(
        review,
        "load_sheet",
        lambda _h, findings, **kw: review.build_sheet(
            items=пункты, zones=зоны, findings=findings, lang=kw["lang"]
        ),
    )

    # Act
    страница = стенд.get("/inspections/x").get_data(as_text=True)

    # Assert
    assert "Записи вне чек-листа версии: 1" in страница
    assert "/findings/f1/revise?lang=" in страница


@админ
def test_письмо_открывается_и_у_ждущей_приёмки(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Экран письма (#488) читает карточку с ждущими — проверка на приёмке не теряет письма."""
    # Arrange
    _приёмка(monkeypatch)
    monkeypatch.setattr(data, "letter_sources", lambda: Papers(live=None, store=None))
    monkeypatch.setattr(data, "build_letter", lambda *_a, **_k: собранное())

    # Act
    ответ = стенд.get("/inspections/x/letter")

    # Assert — смотреть можно; отказ сохранения и почты объясняется словами.
    assert ответ.status_code == 200
    assert "Your inspection scored 92%." in ответ.get_data(as_text=True)
    for отказ in ("saved=on_review", "gmail=on_review"):
        страница = стенд.get(f"/inspections/x/letter?{отказ}").get_data(as_text=True)
        assert "Проверка ещё не подтверждена" in страница, отказ


# --- панель реестра — полный просмотр (D465) ---------------------------------

ПАНЕЛЬ = "/inspections?inspection=x"


@админ
def test_панель_ждущей_принимает_и_правит_на_месте(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Приёмка и правка записей — формами самой панели, а не ссылкой в полную карточку."""
    _приёмка(monkeypatch)
    _лист(monkeypatch)

    страница = стенд.get(ПАНЕЛЬ).get_data(as_text=True)

    assert (
        'action="/inspections/11111111-1111-1111-1111-111111111111/accept?lang=ru" data-panel-form'
        in страница
    )
    assert "Принять проверку" in страница
    assert (
        "/findings/f1/revise?lang=ru" in страница
        and '<form method="post" class="stack mt-gap" data-panel-form' in страница
    )
    assert "data-edit-toggle" in страница  # «Исправить» ведёт к формам правки
    assert 'id="review"' in страница
    # Отдельной страницы карточки среди действий панели нет: «Открыть полностью» снято.
    assert 'href="/inspections/11111111-1111-1111-1111-111111111111?lang=ru"' not in страница
    assert "?lang=ru#review" not in страница


@админ
def test_панель_принятой_не_предлагает_исправить(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Принятую не правят (решение владельца 13.10): ни карандаша, ни переноса."""
    _приёмка(monkeypatch, ждёт=False)

    страница = стенд.get(ПАНЕЛЬ).get_data(as_text=True)

    assert "data-edit-toggle" not in страница
    assert "/move?lang=" not in страница
    assert "/retract?lang=" in страница  # отклонить — по прежнему правилу


@админ
def test_панель_показывает_все_записи_без_ещё_n(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Раньше панель резала список на 8 записей ссылкой «Ещё N — в полной карточке»."""
    _приёмка(monkeypatch, ждёт=False)
    базовая = карточка(шапка())
    записи = tuple(
        replace(базовая.findings[0], id=f"f{n}", n=n, text=f"Замечание номер {n}")
        for n in range(1, 13)
    )
    monkeypatch.setattr(data, "load_card", lambda *_a, **_k: replace(базовая, findings=записи))

    страница = стенд.get(ПАНЕЛЬ).get_data(as_text=True)

    assert "Замечание номер 12" in страница
    assert "в полной карточке" not in страница


@админ
def test_действие_из_панели_отвечает_карточкой_а_не_страницей(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`split.js` шлёт форму фоном с `X-Panel` и подменяет панель ответом (D465)."""
    вызовы = _приёмка(monkeypatch)
    _лист(monkeypatch)

    ответ = стенд.post("/inspections/x/accept", headers={**ORIGIN, "X-Panel": "1"})

    текст = ответ.get_data(as_text=True)
    assert ответ.status_code == 200 and len(вызовы) == 1
    assert "<html" not in текст and 'class="sdetail spanel"' in текст
    assert "Проверка принята." in текст


@админ
def test_действие_без_скрипта_отвечает_страницей_карточки_как_раньше(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _приёмка(monkeypatch)
    _лист(monkeypatch)

    текст = стенд.post("/inspections/x/accept", headers=ORIGIN).get_data(as_text=True)

    assert "<html" in текст and "Проверка принята." in текст
