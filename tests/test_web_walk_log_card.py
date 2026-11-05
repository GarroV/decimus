# ruff: noqa: F811 — фикстура стенда приходит импортом из test_web_app
"""D710: «Журнал обхода» на карточке проверки — кто его видит и что в нём написано.

Читает базу `walk_log_read` (её заслон по роли проверяет `tests/test_db_walk_log.py`);
здесь — что страница ставит блок только тому, кому он положен, говорит словами и не
падает, когда журнал не прочитался.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from flask.testing import FlaskClient
from test_web_app import карточка, стенд, шапка  # noqa: F401

from src.db import walk_log
from src.db.errors import AccessError
from src.db.walk_log import StepRow
from src.web import inspections as data

АДРЕС = "/inspections/{id}"
ЗАГОЛОВОК = "Журнал обхода"


def _шаг(**kw: object) -> StepRow:
    base: dict[str, object] = dict(
        id=1,
        at=datetime(2026, 11, 5, 15, 33, 7, tzinfo=UTC),
        run_id="run-1",
        unit="Brasov-1",
        step="class",
        outcome="ok",
        words="повреждённая мусорка на улице",
        photos=1,
        item_code="CLN02",
        zone="KITCHEN",
        level=None,
        verdict="not_established",
        reason="не мешает работе",
        via=None,
        detail={},
        duration_ms=2310,
        error="",
        login="pavel",
    )
    return StepRow(**{**base, **kw})  # type: ignore[arg-type]


def _открыть(стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch, читает) -> str:
    строка = шапка()
    monkeypatch.setattr(data, "load_card", lambda *_a, **_k: карточка(строка))
    monkeypatch.setattr(data, "load_moves", lambda *_a, **_k: ())
    monkeypatch.setattr(walk_log, "read", читает)
    return стенд.get(АДРЕС.format(id=строка.id)).get_data(as_text=True)


@pytest.mark.parametrize("стенд", ["superadmin", "admin"], indirect=True)
def test_главный_админ_и_админ_ук_видят_шаги_словами_без_кодов(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    страница = _открыть(стенд, monkeypatch, lambda *_a: (_шаг(),))

    assert ЗАГОЛОВОК in страница and "Нарушение по этим фактам не установлено" in страница
    assert "повреждённая мусорка на улице" in страница and "аудитор pavel" in страница
    assert "Зона: Кухня" in страница, "зона названа, а не кодом"


@pytest.mark.parametrize("стенд", ["developer"], indirect=True)
def test_прочим_блока_нет_и_за_журналом_не_ходят(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    ходили: list[object] = []

    def читает(*a: object) -> tuple[StepRow, ...]:
        ходили.append(a)
        return (_шаг(),)

    страница = _открыть(стенд, monkeypatch, читает)

    assert ЗАГОЛОВОК not in страница and not ходили


@pytest.mark.parametrize("стенд", ["superadmin"], indirect=True)
def test_без_шагов_блока_нет(стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch) -> None:
    страница = _открыть(стенд, monkeypatch, lambda *_a: ())

    assert ЗАГОЛОВОК not in страница


@pytest.mark.parametrize("стенд", ["superadmin"], indirect=True)
def test_отказ_базы_карточку_не_роняет_и_назван(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def падает(*_a: object) -> tuple[StepRow, ...]:
        raise AccessError("База недоступна")

    страница = _открыть(стенд, monkeypatch, падает)

    assert "Журнал обхода сейчас не прочитался" in страница
    assert "Demo Pizzeria #1" in страница, "карточка осталась на месте"
