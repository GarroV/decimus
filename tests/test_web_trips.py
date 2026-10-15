"""Поездки «Календаря» (D505, D506): права и пространство на маршрутах.

База здесь не поднимается — двери `src/db/trips.py` подменены и пишут, с чем их
звали. Главное, что проверяется: пространство поездки берётся из учётки
вошедшего, а не из адреса или формы; править может админ пространства или сам
исполнитель; гость и чужие — нет. Что база сама не отдаёт чужого, держит
`tests/test_db_trips.py`.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from flask.testing import FlaskClient
from web_harness import СВОЙ, Учётка, войти, подменить_двери, собрать

from src.db import trips as tr
from src.db.directory import Unit
from src.db.errors import TripError
from src.web import calendar_screen as cs

ПОЕЗДКА = "11111111-1111-1111-1111-111111111111"
ТОЧКА = "44444444-4444-4444-4444-444444444444"
ЧУЖАЯ_ТОЧКА = "55555555-5555-5555-5555-555555555555"
СВОЙ_ID = Учётка().id


def поездка(**поля: Any) -> tr.Trip:
    base: dict[str, Any] = {
        "id": ПОЕЗДКА,
        "tenant": "GE",
        "executor_name": "director",
        "executor_user_id": СВОЙ_ID,
        "country": "GE",
        "date_from": date(2026, 10, 20),
        "date_to": date(2026, 10, 22),
        "status": "planned",
        "note": "",
        "created_by": СВОЙ_ID,
    }
    return tr.Trip(**{**base, **поля})


@pytest.fixture
def зовы(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    """Двери поездок, справочника и людей — подменены и пишут вызовы."""
    з: dict[str, list[Any]] = {"list": [], "get": [], "create": [], "update": [], "step": []}
    хранилище: dict[str, tr.Trip] = {}

    def _list(**kw: Any) -> tuple[tr.Trip, ...]:
        з["list"].append(kw)
        return tuple(п for п in хранилище.values() if п.tenant == kw["tenant"])

    def _get(trip_id: str, *, tenant: str) -> tr.Trip | None:
        з["get"].append((trip_id, tenant))
        найдена = хранилище.get(trip_id)
        return найдена if найдена is not None and найдена.tenant == tenant else None

    def _create(draft: tr.Draft, *, tenant: str, actor_id: str) -> str:
        з["create"].append((tr.check_draft(draft), tenant, actor_id))
        return ПОЕЗДКА

    def _update(trip_id: str, draft: tr.Draft, *, tenant: str) -> bool:
        з["update"].append((trip_id, tr.check_draft(draft), tenant))
        return True

    def _add_step(trip: tr.Trip, step: tr.StepDraft) -> None:
        з["step"].append((trip.id, tr.check_step(step, trip)))

    monkeypatch.setattr(cs.tr, "list_trips", _list)
    monkeypatch.setattr(cs.tr, "get_trip", _get)
    monkeypatch.setattr(cs.tr, "create_trip", _create)
    monkeypatch.setattr(cs.tr, "update_trip", _update)
    monkeypatch.setattr(cs.tr, "add_step", _add_step)
    monkeypatch.setattr(cs.tr, "delete_trip", lambda *a, **k: True)
    monkeypatch.setattr(cs.data, "load_dated", lambda **_: ())
    monkeypatch.setattr(
        cs,
        "list_units",
        lambda **_: [Unit(id=ТОЧКА, name="Батуми-1", code=None, aliases=(), country="GE")],
    )

    class Строка:
        def __init__(self, login: str, ident: str) -> None:
            self.login, self.id, self.disabled_at = login, ident, None

    monkeypatch.setattr(
        cs.accounts,
        "everyone",
        lambda **_: (Строка("nino", "66666666-6666-6666-6666-666666666666"),),
    )
    з["store"] = [хранилище]
    return з


def клиент(monkeypatch: pytest.MonkeyPatch, *, tenant: str, role: str) -> FlaskClient:
    подменить_двери(monkeypatch, tenant=tenant, role=role)
    c = собрать(tenant=tenant).test_client()
    assert войти(c).status_code in (302, 303)
    return c


def отправить(c: FlaskClient, путь: str, **поля: str) -> Any:
    return c.post(путь, data=поля, headers={"Origin": СВОЙ})


ФОРМА = {"executor": "Кто-то", "country": "GE", "from": "2026-10-20", "to": "2026-10-22"}


def test_календарь_читает_поездки_только_своего_пространства(
    monkeypatch: pytest.MonkeyPatch, зовы: dict[str, list[Any]]
) -> None:
    """УК читает поездки УК, партнёр — свои: пространство — из учётки, не из адреса."""
    for пространство, роль in (("HQ", "admin"), ("GE", "admin")):
        c = клиент(monkeypatch, tenant=пространство, role=роль)
        assert c.get("/calendar?tenant=AM&space=AM").status_code == 200
        assert зовы["list"][-1]["tenant"] == пространство


def test_пространство_из_формы_не_подменяет_пространство_учётки(
    monkeypatch: pytest.MonkeyPatch, зовы: dict[str, list[Any]]
) -> None:
    c = клиент(monkeypatch, tenant="GE", role="admin")
    ответ = отправить(c, "/calendar/trips", **ФОРМА, tenant="HQ", tenant_code="HQ")
    assert ответ.status_code == 303
    _, пространство, автор = зовы["create"][-1]
    assert пространство == "GE" and автор == СВОЙ_ID


def test_чужая_поездка_не_найдена_и_не_правится(
    monkeypatch: pytest.MonkeyPatch, зовы: dict[str, list[Any]]
) -> None:
    """УК открывает и правит поездку партнёра по её номеру — «не найдена», записи нет."""
    зовы["store"][0][ПОЕЗДКА] = поездка(tenant="GE", executor_name="Исполнитель-партнёра")
    c = клиент(monkeypatch, tenant="HQ", role="superadmin")
    страница = c.get(f"/calendar?trip={ПОЕЗДКА}").get_data(as_text=True)
    assert "Поездка не найдена" in страница and "Исполнитель-партнёра" not in страница
    assert зовы["get"][-1] == (ПОЕЗДКА, "HQ")
    assert отправить(c, f"/calendar/trips/{ПОЕЗДКА}", **ФОРМА).status_code == 404
    assert отправить(c, f"/calendar/trips/{ПОЕЗДКА}/delete").status_code == 404
    assert (
        отправить(
            c, f"/calendar/trips/{ПОЕЗДКА}/steps", day="2026-10-20", kind="other", body="x"
        ).status_code
        == 404
    )
    assert зовы["update"] == [] and зовы["step"] == []


def test_гость_не_заводит_поездок(
    monkeypatch: pytest.MonkeyPatch, зовы: dict[str, list[Any]]
) -> None:
    c = клиент(monkeypatch, tenant="HQ", role="guest")
    assert "trip=new" not in c.get("/calendar").get_data(as_text=True)
    assert отправить(c, "/calendar/trips", **ФОРМА).status_code == 403
    assert зовы["create"] == []


def test_сотрудник_партнёра_планирует_только_себя(
    monkeypatch: pytest.MonkeyPatch, зовы: dict[str, list[Any]]
) -> None:
    c = клиент(monkeypatch, tenant="GE", role="auditor")
    assert отправить(c, "/calendar/trips", **ФОРМА).status_code == 303
    черновик, _, _ = зовы["create"][-1]
    assert черновик.executor_name == "director" and черновик.executor_user_id == СВОЙ_ID


def test_сотрудник_не_правит_чужую_поездку_своего_пространства(
    monkeypatch: pytest.MonkeyPatch, зовы: dict[str, list[Any]]
) -> None:
    зовы["store"][0][ПОЕЗДКА] = поездка(executor_user_id=None, executor_name="nino")
    c = клиент(monkeypatch, tenant="GE", role="auditor")
    assert отправить(c, f"/calendar/trips/{ПОЕЗДКА}", **ФОРМА).status_code == 403
    assert (
        отправить(
            c, f"/calendar/trips/{ПОЕЗДКА}/steps", day="2026-10-20", kind="other", body="x"
        ).status_code
        == 403
    )
    assert зовы["update"] == [] and зовы["step"] == []


def test_исполнитель_правит_свою_но_не_меняет_исполнителя(
    monkeypatch: pytest.MonkeyPatch, зовы: dict[str, list[Any]]
) -> None:
    зовы["store"][0][ПОЕЗДКА] = поездка()
    c = клиент(monkeypatch, tenant="GE", role="auditor")
    assert (
        отправить(c, f"/calendar/trips/{ПОЕЗДКА}", **{**ФОРМА, "executor": "nino"}).status_code
        == 303
    )
    _, черновик, пространство = зовы["update"][-1]
    assert черновик.executor_user_id == СВОЙ_ID and пространство == "GE"


def test_логин_своего_пространства_связывает_учётку(
    monkeypatch: pytest.MonkeyPatch, зовы: dict[str, list[Any]]
) -> None:
    """D506: вписан логин пользователя — это он; любое другое имя — просто текст."""
    c = клиент(monkeypatch, tenant="GE", role="admin")
    отправить(c, "/calendar/trips", **{**ФОРМА, "executor": "NINO"})
    отправить(c, "/calendar/trips", **{**ФОРМА, "executor": "Гость из офиса"})
    первый, второй = зовы["create"][-2][0], зовы["create"][-1][0]
    assert первый.executor_user_id == "66666666-6666-6666-6666-666666666666"
    assert второй.executor_user_id is None and второй.executor_name == "Гость из офиса"


def test_пиццерия_и_страна_вне_охвата_отказ(
    monkeypatch: pytest.MonkeyPatch, зовы: dict[str, list[Any]]
) -> None:
    зовы["store"][0][ПОЕЗДКА] = поездка()
    c = клиент(monkeypatch, tenant="GE", role="admin")
    ответ = отправить(
        c, f"/calendar/trips/{ПОЕЗДКА}/steps", day="2026-10-20", kind="inspection", unit=ЧУЖАЯ_ТОЧКА
    )
    assert ответ.status_code == 400 and "вне вашего охвата" in ответ.get_data(as_text=True)
    assert отправить(c, "/calendar/trips", **{**ФОРМА, "country": "AM"}).status_code == 400
    assert зовы["step"] == [] and зовы["create"] == []


def test_чужая_страница_не_отправит_форму(
    monkeypatch: pytest.MonkeyPatch, зовы: dict[str, list[Any]]
) -> None:
    c = клиент(monkeypatch, tenant="GE", role="admin")
    ответ = c.post("/calendar/trips", data=ФОРМА, headers={"Origin": "https://evil.example"})
    assert ответ.status_code == 403 and зовы["create"] == []


def test_шаг_вне_дат_поездки_отказ() -> None:
    with pytest.raises(TripError) as отказ:
        tr.check_step(
            tr.StepDraft(day=date(2026, 11, 1), at=None, kind="other", unit_id=None, body="x"),
            поездка(),
        )
    assert отказ.value.code == "trip.err.step_day"


def test_экран_показывает_поездку_и_план(
    monkeypatch: pytest.MonkeyPatch, зовы: dict[str, list[Any]]
) -> None:
    шаг = tr.Step(
        id="77777777-7777-7777-7777-777777777777",
        day=date(2026, 10, 21),
        at=None,
        kind="inspection",
        unit_id=ТОЧКА,
        unit_name="Батуми-1",
        body="",
    )
    зовы["store"][0][ПОЕЗДКА] = поездка(steps=(шаг,))
    c = клиент(monkeypatch, tenant="GE", role="admin")
    страница = c.get(f"/calendar?from=2026-10-01&to=2026-10-31&trip={ПОЕЗДКА}").get_data(
        as_text=True
    )
    assert "cal__trip" in страница and "Батуми-1" in страница and "Добавить в план" in страница
