"""План исправлений через MCP (#1168, D620): права, охват, короткие ответы — без базы.

Двери `src.db.action_plans` и `src.db.plan_flow` подменены: здесь проверяется то, что
решает MCP (кто вызывает, чьи страны, что уходит в дверь, что приходит агенту), а
переходы и сторожа базы — в `tests/test_db_plan_flow.py`.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any

import pytest

from src.db import action_plans as plans
from src.db import plan_flow as flow
from src.db import reach as reach_module
from src.db.errors import ActionPlanError
from src.db.plan_rows import PlanRow
from src.db.reach import Reach
from src.mcp import plans as plans_tools
from src.mcp.catalogue import TOOLS
from src.mcp.rpc import handle

REQUEST = "00000000-0000-0000-0000-0000000000a1"
ROW = "00000000-0000-0000-0000-0000000000b1"
СЕГОДНЯ = date(2026, 10, 23)
ЧЕТЫРЕ_ЗНАКА = "x" * 5000

ПЛАН_УК = {
    "accept_action_plan": {"request_id": REQUEST},
    "return_action_plan": {"request_id": REQUEST, "comment": "уточнить"},
    "confirm_plan_row": {"request_id": REQUEST, "row_id": ROW},
    "return_plan_row": {"request_id": REQUEST, "row_id": ROW, "reason": "нет фото"},
    "set_plan_count_from": {"request_id": REQUEST, "count_from": "2026-10-01"},
}
ПЛАН_ПАРТНЁРА = {
    "fill_plan_row": {"request_id": REQUEST, "row_id": ROW, "measure": "помыть"},
    "submit_action_plan": {"request_id": REQUEST},
    "start_plan_row": {"request_id": REQUEST, "row_id": ROW},
    "finish_plan_row": {"request_id": REQUEST, "row_id": ROW},
}
ДВЕРИ_УК = (
    "accept_plan",
    "return_plan",
    "confirm_row",
    "return_row",
    "set_count_from",
)
ДВЕРИ_ПАРТНЁРА = ("patch_row", "submit_plan", "start_row", "finish_row")


def _row(i: int = 1, **over: Any) -> PlanRow:
    base: dict[str, Any] = {
        "id": ROW if i == 1 else f"00000000-0000-0000-0000-{i:012d}",
        "request_id": REQUEST,
        "finding_id": "f",
        "position": i,
        "item_code": "CLN01",
        "level": "D2",
        "zone": "kitchen",
        "title_ru": "Пол в пятнах",
        "title_en": "Dirty floor",
        "days": 14,
        "measure": "",
        "responsible": "",
        "reason": "",
        "own_due": None,
        "extended_due": None,
        "due_on": date(2026, 10, 30),
        "status": "filling",
        "return_reason": "",
        "updated_at": datetime(2026, 10, 20, tzinfo=UTC),
    }
    return PlanRow(**{**base, **over})


def _plan(rows: tuple[PlanRow, ...] = (), **over: Any) -> plans.PlanRequest:
    base: dict[str, Any] = {
        "id": REQUEST,
        "inspection_id": "i",
        "country": "RS",
        "due_on": date(2026, 11, 5),
        "status": "requested",
        "origin": "auto",
        "requested_by": "web:a",
        "requested_at": datetime(2026, 10, 20, tzinfo=UTC),
        "unit_id": "u",
        "unit_name": "Белград-1",
        "inspection_date": date(2026, 10, 15),
        "pct": 91.0,
        "grade": "B",
        "files": (),
        "events": (),
        "count_from": date(2026, 10, 16),
        "revision": 3,
        "electronic": True,
        "review_comment": None,
        "rows": rows,
    }
    return plans.PlanRequest(**{**base, **over})


def _call(name: str, arguments: dict[str, Any], *, tenant: str, role: str) -> dict[str, Any]:
    ответ = handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
        tenant=tenant,
        role=role,
        actor=f"web:{role}",
    )
    assert ответ is not None
    return ответ


def _text(ответ: dict[str, Any]) -> str:
    return str(ответ["result"]["content"][0]["text"])


@pytest.fixture
def двери(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    """Каждая дверь записи плана записывает вызов; чтение отдаёт один план и охват по стране."""
    вызовы: list[tuple[str, dict[str, Any]]] = []

    def записать(имя: str) -> Any:
        def дверь(*args: Any, **kwargs: Any) -> None:
            вызовы.append((имя, {"args": args, **kwargs}))

        return дверь

    for имя in (*ДВЕРИ_УК, *ДВЕРИ_ПАРТНЁРА):
        monkeypatch.setattr(flow, имя, записать(имя))
    охваты: list[Reach] = []
    monkeypatch.setattr(
        reach_module,
        "reach_of",
        lambda tenant: (
            охваты.append(Reach(tenant, None, ("RS",) if tenant == "RS" else None)) or охваты[-1]
        ),
    )
    monkeypatch.setattr(plans, "today", lambda: СЕГОДНЯ)
    monkeypatch.setattr(plans, "get_request", lambda request_id, *, reach: _plan((_row(),)))
    return вызовы


# ── Права ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("роль", ["admin", "auditor"])
@pytest.mark.parametrize(("имя", "аргументы"), sorted(ПЛАН_УК.items()))
def test_партнёр_не_выносит_вердиктов(
    двери: list[Any], роль: str, имя: str, аргументы: dict[str, Any]
) -> None:
    ответ = _call(имя, аргументы, tenant="RS", role=роль)

    assert ответ["result"]["isError"] is True
    assert "не открыт роли" in _text(ответ)
    assert [в for в in двери if в[0] in ДВЕРИ_УК] == []


@pytest.mark.parametrize("роль", ["admin", "superadmin", "developer"])
@pytest.mark.parametrize(("имя", "аргументы"), sorted(ПЛАН_ПАРТНЁРА.items()))
def test_ук_не_заполняет_за_партнёра(
    двери: list[Any], роль: str, имя: str, аргументы: dict[str, Any]
) -> None:
    ответ = _call(имя, аргументы, tenant="HQ", role=роль)

    assert ответ["result"]["isError"] is True
    assert "не открыт роли" in _text(ответ)
    assert [в for в in двери if в[0] in ДВЕРИ_ПАРТНЁРА] == []


@pytest.mark.parametrize("имя", sorted(plans_tools.READ_TOOLS))
@pytest.mark.parametrize(("тенант", "роль"), [("HQ", "guest"), ("HQ", "control"), ("RS", "bogus")])
def test_чтение_плана_закрыто_ролям_без_раздела_действий(
    двери: list[Any], имя: str, тенант: str, роль: str
) -> None:
    ответ = _call(
        имя, {"request_id": REQUEST} if имя == "get_action_plan" else {}, tenant=тенант, role=роль
    )

    assert ответ["result"]["isError"] is True


def test_вердикт_ук_доходит_до_двери_с_автором_из_токена(двери: list[Any]) -> None:
    ответ = _call("return_plan_row", ПЛАН_УК["return_plan_row"], tenant="HQ", role="admin")

    assert "isError" not in ответ["result"] or ответ["result"]["isError"] is False
    _, kwargs = next(в for в in двери if в[0] == "return_row")
    assert kwargs["actor"] == "web:admin"
    assert kwargs["reason"] == "нет фото"
    assert kwargs["args"] == (REQUEST, ROW)


def test_работа_партнёра_идёт_с_его_пространством_и_охватом(двери: list[Any]) -> None:
    _call("start_plan_row", ПЛАН_ПАРТНЁРА["start_plan_row"], tenant="RS", role="auditor")

    _, kwargs = next(в for в in двери if в[0] == "start_row")
    assert kwargs["tenant"] == "RS"
    assert kwargs["reach"].countries == ("RS",)


# ── Охват ───────────────────────────────────────────────────────────────────


def test_список_читается_в_охвате_токена_без_аргумента_пространства(
    monkeypatch: pytest.MonkeyPatch, двери: list[Any]
) -> None:
    увидено: list[Reach] = []

    def список(*, reach: Reach, country: str | None = None, accepted: bool = False) -> Any:
        увидено.append(reach)
        return plans.PlanList(rows=(_plan((_row(),)),), truncated=False)

    monkeypatch.setattr(plans, "list_requests", список)

    _call("list_action_plans", {}, tenant="RS", role="admin")
    _call("list_action_plans", {}, tenant="HQ", role="admin")

    assert [r.countries for r in увидено] == [("RS",), None]
    assert all("tenant" not in (t.input_schema["properties"]) for t in TOOLS)


def test_чужой_или_несуществующий_план_отвечает_одинаково(
    monkeypatch: pytest.MonkeyPatch, двери: list[Any]
) -> None:
    monkeypatch.setattr(plans, "get_request", lambda request_id, *, reach: None)

    ответ = _call("get_action_plan", {"request_id": REQUEST}, tenant="RS", role="admin")

    assert ответ["result"]["isError"] is True
    assert plans_tools.NO_PLAN in _text(ответ)


# ── Ответы ──────────────────────────────────────────────────────────────────


def test_план_читается_со_сроками_и_просрочкой_на_сегодня(
    monkeypatch: pytest.MonkeyPatch, двери: list[Any]
) -> None:
    строки = (
        _row(1, due_on=date(2026, 10, 20), status="in_work"),
        _row(2, due_on=date(2026, 10, 20), status="done"),
        _row(3, due_on=date(2026, 10, 30), status="in_work"),
    )
    monkeypatch.setattr(plans, "get_request", lambda request_id, *, reach: _plan(строки))

    ответ = json.loads(
        _text(_call("get_action_plan", {"request_id": REQUEST}, tenant="HQ", role="admin"))
    )

    assert [r["overdue"] for r in ответ["rows"]] == [True, False, False]
    assert ответ["rows"][0]["due_on"] == "2026-10-20"
    assert ответ["rows"][0]["n"] == 1
    assert ответ["rows"][0]["title"] == "Dirty floor"
    assert ответ["overdue"] is False


def test_просрочка_плана_на_приёмке_и_число_возвратов_в_ответе(
    monkeypatch: pytest.MonkeyPatch, двери: list[Any]
) -> None:
    """Просрочка и возвраты берутся из плана, а не считаются инструментом."""
    события = tuple(
        plans.PlanEvent(action=a, actor="hq", detail=None, at=datetime(2026, 10, 21, tzinfo=UTC))
        for a in ("uploaded", "returned", "uploaded", "returned", "uploaded")
    )
    итог = _plan(status="on_review", due_on=date(2026, 10, 1), events=события)
    monkeypatch.setattr(plans, "get_request", lambda request_id, *, reach: итог)
    monkeypatch.setattr(plans, "today", lambda: date(2026, 10, 23))

    ответ = json.loads(
        _text(_call("get_action_plan", {"request_id": REQUEST}, tenant="HQ", role="admin"))
    )

    assert ответ["overdue"] is True
    assert ответ["returns"] == 2


def test_ответ_плана_короткий_без_снимков_и_пустых_полей(
    monkeypatch: pytest.MonkeyPatch, двери: list[Any]
) -> None:
    строки = tuple(_row(i, measure=ЧЕТЫРЕ_ЗНАКА, reason=ЧЕТЫРЕ_ЗНАКА) for i in range(1, 31))
    monkeypatch.setattr(plans, "get_request", lambda request_id, *, reach: _plan(строки))

    текст = _text(_call("get_action_plan", {"request_id": REQUEST}, tenant="HQ", role="admin"))
    ответ = json.loads(текст)

    assert len(текст) < 30 * (2 * plans_tools.SHOWN_TEXT + 500)
    assert len(ответ["rows"][0]["measure"]) <= plans_tools.SHOWN_TEXT
    assert "finding_id" not in ответ["rows"][0]
    assert "title_en" not in ответ["rows"][0]
    assert "responsible" not in ответ["rows"][0]
    assert "events" not in ответ


def test_список_коротко_без_строк_плана(monkeypatch: pytest.MonkeyPatch, двери: list[Any]) -> None:
    монтаж = plans.PlanList(rows=(_plan((_row(), _row(2, status="done"))),), truncated=False)
    monkeypatch.setattr(plans, "list_requests", lambda **kw: монтаж)

    ответ = json.loads(_text(_call("list_action_plans", {}, tenant="HQ", role="admin")))

    план = ответ["plans"][0]
    assert "rows" in план and set(план["rows"]) == {"total", "filled", "overdue", "by_status"}
    assert план["rows"]["by_status"] == {"filling": 1, "done": 1}
    assert ответ["total"] == 1


def test_запись_отвечает_статусом_счётчиком_и_одной_строкой_а_не_планом(
    monkeypatch: pytest.MonkeyPatch, двери: list[Any]
) -> None:
    строки = tuple(_row(i, measure=ЧЕТЫРЕ_ЗНАКА) for i in range(1, 21))
    monkeypatch.setattr(plans, "get_request", lambda request_id, *, reach: _plan(строки))

    ответ = json.loads(
        _text(_call("start_plan_row", ПЛАН_ПАРТНЁРА["start_plan_row"], tenant="RS", role="admin"))
    )

    assert set(ответ) == {"request_id", "note", "status", "rows_by_status", "row"}
    assert ответ["row"]["id"] == ROW
    assert len(json.dumps(ответ, ensure_ascii=False)) < 1500


def test_отказ_двери_приходит_словами_а_не_типом(
    monkeypatch: pytest.MonkeyPatch, двери: list[Any]
) -> None:
    def отказ(*a: Any, **k: Any) -> None:
        raise ActionPlanError("План не на согласовании — принимать или возвращать нечего")

    monkeypatch.setattr(flow, "accept_plan", отказ)

    ответ = _call("accept_action_plan", {"request_id": REQUEST}, tenant="HQ", role="admin")

    assert ответ["result"]["isError"] is True
    assert "не на согласовании" in _text(ответ)


def test_без_автора_запись_закрыта_а_чтение_нет(двери: list[Any]) -> None:
    запись = handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "accept_action_plan", "arguments": {"request_id": REQUEST}},
        },
        tenant="HQ",
        role="admin",
        actor="",
    )
    assert запись is not None and запись["result"]["isError"] is True
    assert "автора" in _text(запись)
    assert [в for в in двери if в[0] == "accept_plan"] == []

    чтение = handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "get_action_plan", "arguments": {"request_id": REQUEST}},
        },
        tenant="HQ",
        role="admin",
        actor="",
    )
    assert чтение is not None and not чтение["result"].get("isError")


# ── Заполнение строки ───────────────────────────────────────────────────────


def test_заполнение_зовёт_частичную_дверь_только_с_названными_полями(
    двери: list[Any],
) -> None:
    _call(
        "fill_plan_row",
        {"request_id": REQUEST, "row_id": ROW, "measure": "новая"},
        tenant="RS",
        role="admin",
    )

    _, kwargs = next(в for в in двери if в[0] == "patch_row")
    assert kwargs["measure"] == "новая"
    assert not {"responsible", "reason", "own_due"} & set(kwargs)
    assert kwargs["args"] == (REQUEST, ROW)
    assert not [в for в in двери if в[0] == "save_row"]


def test_пустая_строка_стирает_поле_только_названная(двери: list[Any]) -> None:
    _call(
        "fill_plan_row",
        {"request_id": REQUEST, "row_id": ROW, "responsible": "", "own_due": ""},
        tenant="RS",
        role="admin",
    )

    _, kwargs = next(в for в in двери if в[0] == "patch_row")
    assert kwargs["responsible"] == ""
    assert kwargs["own_due"] is None
    assert "measure" not in kwargs


def test_заполнение_без_полей_отказано_до_двери(двери: list[Any]) -> None:
    ответ = _call(
        "fill_plan_row", {"request_id": REQUEST, "row_id": ROW}, tenant="RS", role="admin"
    )

    assert ответ["result"]["isError"] is True
    assert plans_tools.NOTHING_TO_FILL in _text(ответ)
    assert [в for в in двери if в[0] == "patch_row"] == []


def test_отказ_частичной_двери_приходит_словами(
    monkeypatch: pytest.MonkeyPatch, двери: list[Any]
) -> None:
    def отказ(*a: Any, **k: Any) -> None:
        raise ActionPlanError("Строки нет")

    monkeypatch.setattr(flow, "patch_row", отказ)

    ответ = _call(
        "fill_plan_row",
        {"request_id": REQUEST, "row_id": ROW, "measure": "x"},
        tenant="RS",
        role="admin",
    )

    assert ответ["result"]["isError"] is True
    assert "Строки нет" in _text(ответ)


# ── Язык ────────────────────────────────────────────────────────────────────


def _titles(аргументы: dict[str, Any]) -> Any:
    ответ = _call(
        "get_action_plan", {"request_id": REQUEST, **аргументы}, tenant="HQ", role="admin"
    )
    return ответ, None if ответ["result"].get("isError") else json.loads(_text(ответ))


def test_язык_пунктов_параметр_а_не_константа(двери: list[Any]) -> None:
    _, по_умолчанию = _titles({})
    _, русский = _titles({"lang": "ru"})
    _, английский = _titles({"lang": "en"})

    assert русский["rows"][0]["title"] == "Пол в пятнах"
    assert английский["rows"][0]["title"] == "Dirty floor"
    assert по_умолчанию["rows"][0]["title"] == "Dirty floor"


def test_незнакомый_язык_отказ_а_не_замена(двери: list[Any]) -> None:
    ответ, _ = _titles({"lang": "de"})

    assert ответ["result"]["isError"] is True
    assert "не заведён" in _text(ответ)


def test_ответ_записи_без_формулировки_пункта(двери: list[Any]) -> None:
    ответ = json.loads(
        _text(_call("start_plan_row", ПЛАН_ПАРТНЁРА["start_plan_row"], tenant="RS", role="admin"))
    )

    assert "title" not in ответ["row"]
