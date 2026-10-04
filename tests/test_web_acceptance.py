"""Этап приёмки в админке (D199) и правка записи на приёмке (D200).

Проверяется поверхность: кто видит кнопки, кто может отправить форму, что
доходит до двери блока `db` и как показан отказ. Подтверждает и правит только
админ своего пространства (D283); УК видит ждущую партнёра на чтение.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from flask.testing import FlaskClient
from test_web_app import ПУСТАЯ_СЕТЬ, ТЕНАНТ, карточка, шапка
from web_harness import ЛОГИН, войти, подменить_двери, собрать

from src.db.errors import AcceptError, ReviseError
from src.domain.tenants import canonical_tenant
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
    подменить_двери(monkeypatch, tenant=ТЕНАНТ, role=getattr(request, "param", "auditor"))
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

    # Assert — подтвердить и исправить можно, переносить и отклонять до приёмки нечего.
    assert "Проверка на приёмке" in страница
    assert "/accept?lang=" in страница
    assert "/findings/f1/revise?lang=" in страница
    assert "Сохранить и пересчитать" in страница
    assert "/move?lang=" not in страница
    assert "/retract?lang=" not in страница


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


def test_аудитор_не_подтверждает(стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
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


def test_аудитор_записи_не_исправляет(стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch) -> None:
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
