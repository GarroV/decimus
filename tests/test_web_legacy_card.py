# ruff: noqa: F811 — фикстура стенда приходит импортом из test_web_app
"""Карточка исторической и текущей загруженной проверки в вебе (D332, D310).

Историческая показывает оценку старого отчёта как есть, статус и метку методики,
пометку «историческая, оценка по методике того времени»; разбивки по зонам и
«вычтено 0» у неё нет. Записи без класса — «без класса», без пункта — «пункт не
назван». Ни у какой загруженной нет кнопки письма партнёру, экран письма
отказывает словами, а плашки «нужен план» и ручного запроса плана нет.
"""

from __future__ import annotations

from datetime import date

import pytest
from flask.testing import FlaskClient
from test_web_app import карточка, стенд, шапка  # noqa: F401

from src.db.models import FindingRow, InspectionDetail
from src.web import action_plans
from src.web import inspections as data


def _историческая() -> InspectionDetail:
    строка = шапка(
        pct=95.29,
        grade="",
        chat_id=0,
        origin="legacy",
        checklist_version="legacy:Qvalon 133",
        checklist_code="bizdev",
    )
    запись = FindingRow(
        id="f1",
        inspection_id=строка.id,
        unit_name=строка.unit_name,
        inspection_date=date(2024, 3, 15),
        n=1,
        code="LEGACY",
        level="NC",
        zone="",
        zone_unusual=False,
        source="",
        lang="ru",
        text="Грязный пол в зале",
        comment=None,
    )
    return карточка(
        строка,
        deductions=0.0,
        counts={"D3": 1, "NC": 1},
        by_zone={},
        findings=(запись,),
        reported_status="Critical (D3)",
        legacy_method="Qvalon 133",
    )


@pytest.mark.parametrize("стенд", ["admin"], indirect=True)
def test_карточка_исторической_оценка_как_есть_без_зон_и_письма(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — D3 в счёте: у обхода это «нужен план», у исторической — нет.
    деталь = _историческая()
    monkeypatch.setattr(data, "load_card", lambda *_a, **_k: деталь)
    monkeypatch.setattr(action_plans, "card_plan", lambda *_a, **_k: (None, True))
    monkeypatch.setattr(action_plans, "is_hq", lambda: True)

    # Act
    ответ = стенд.get(f"/inspections/{деталь.inspection.id}?lang=ru")
    страница = ответ.get_data(as_text=True)

    # Assert
    assert ответ.status_code == 200
    assert "95.29" in страница
    assert "Историческая проверка, оценка по методике того времени" in страница
    assert "Critical (D3)" in страница and "Qvalon 133" in страница
    assert "без класса" in страница and "пункт не назван" in страница
    assert "зона не названа" in страница
    assert "view=letter" not in страница
    assert "LEGACY" not in страница
    # Экшн-плана у загруженной нет: ни плашки «нужен», ни ручного запроса (D310).
    assert "Экшн-план" not in страница


@pytest.mark.parametrize("origin", ["legacy", "import"])
@pytest.mark.parametrize("стенд", ["admin"], indirect=True)
def test_письма_по_загруженной_нет_и_экран_говорит_почему(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch, origin: str
) -> None:
    деталь = _историческая() if origin == "legacy" else карточка(шапка(origin="import"))
    monkeypatch.setattr(data, "load_card", lambda *_a, **_k: деталь)
    monkeypatch.setattr(
        data, "load_letter", lambda *_a, **_k: pytest.fail("письмо собирать нельзя")
    )

    ответ = стенд.get(f"/inspections/{деталь.inspection.id}/letter?lang=ru")

    assert ответ.status_code == 409
    assert "письма партнёру по ней нет" in ответ.get_data(as_text=True)


@pytest.mark.parametrize("стенд", ["admin"], indirect=True)
def test_у_обхода_кнопка_письма_на_месте(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Контроль к тестам выше: на том же стенде у обхода письмо и экшн-план есть."""
    деталь = карточка(шапка())
    monkeypatch.setattr(data, "load_card", lambda *_a, **_k: деталь)
    monkeypatch.setattr(action_plans, "card_plan", lambda *_a, **_k: (None, True))
    monkeypatch.setattr(action_plans, "is_hq", lambda: True)
    страница = стенд.get(f"/inspections/{деталь.inspection.id}?lang=ru").get_data(as_text=True)
    assert f"inspection={деталь.inspection.id}&amp;view=letter" in страница
    assert "Экшн-план" in страница


@pytest.mark.parametrize("стенд", ["admin"], indirect=True)
@pytest.mark.parametrize(
    ("поля", "ждём", "не_ждём"),
    [
        (
            {"origin": "import", "accepted_at": "2026-10-19T09:30:00+00:00", "accepted_by": "anna"},
            ("Через Claude", "Принята: anna · 2026-10-19 09:30"),
            ("Через бота",),
        ),
        ({"origin": "field"}, ("Через бота",), ("Через Claude",)),
        ({"origin": "import", "on_review": True}, ("Через Claude", "Ждёт приёмки"), ()),
    ],
)
def test_шапка_карточки_говорит_откуда_проверка_и_кем_принята(
    стенд: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
    поля: dict[str, object],
    ждём: tuple[str, ...],
    не_ждём: tuple[str, ...],
) -> None:
    деталь = карточка(шапка(**поля))
    monkeypatch.setattr(data, "load_card", lambda *_a, **_k: деталь)

    страница = стенд.get(f"/inspections/{деталь.inspection.id}?lang=ru").get_data(as_text=True)

    for строка in ждём:
        assert строка in страница
    for строка in не_ждём:
        assert строка not in страница
