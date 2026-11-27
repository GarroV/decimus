"""F-130 (#1006): правящие инструменты MCP выполняются только вторым вызовом с токеном.

Диспетчер проверяется на подменённых спецификациях со счётчиком вызовов —
важно не «что сделал инструмент», а «дошёл ли вызов до обработчика». Кому
нужно подтверждение и какого уровня — закреплено по настоящему каталогу.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from src.mcp import confirm, rpc
from src.mcp.annotations import READ, TOOL_CLASSES
from src.mcp.catalogue import TOOLS, find

#: Уровень «спросить человека»: свой текст эффекта (`ToolSpec.confirm_effect`).
СПРОСИТЬ_ЧЕЛОВЕКА = {
    "apply_checklist",
    "publish_checklist_version",
    "set_scoring",
    "set_zone_shares",
    "set_checklist_state",
    "set_route",
    "remove_checklist_item",
    "remove_zone",
    "remove_photo_cue",
    "retract_learned_phrase",
    "repoint_learned_phrase",
    "retract_inspection",
}

#: Правящие без подтверждения — только с причиной в `confirm.EXEMPT`.
БЕЗ_ПОДТВЕРЖДЕНИЯ = {"import_upload_photos"}


class _Счётчик:
    def __init__(self) -> None:
        self.вызовы: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> dict[str, object]:
        self.вызовы.append(kwargs)
        return {"status": "done"}


@pytest.fixture
def счётчик(monkeypatch: pytest.MonkeyPatch) -> _Счётчик:
    сч = _Счётчик()
    база = find("list_inspections")
    assert база is not None
    схема = {
        "type": "object",
        "properties": {
            "unit": {"type": "string"},
            confirm.TOKEN_ARGUMENT: {"type": "string"},
        },
        "additionalProperties": False,
    }
    опасный = replace(база, name="danger", input_schema=схема, handler=сч, confirm_effect="X")
    другой = replace(опасный, name="danger2")
    # Имена настоящие: кому нужен второй шаг, решает класс из `annotations.py`.
    обычный = replace(
        база, name="list_inspections", input_schema=схема, handler=сч, confirm_effect=""
    )
    правящий = replace(
        база, name="import_edit_finding", input_schema=схема, handler=сч, confirm_effect=""
    )
    каталог = {s.name: s for s in (опасный, другой, обычный, правящий)}
    monkeypatch.setattr(rpc, "find", каталог.get)
    return сч


def _вызвать(имя: str, аргументы: dict[str, Any], tenant: str = "HQ") -> dict[str, Any]:
    ответ = rpc.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": имя, "arguments": аргументы},
        },
        tenant=tenant,
        role="admin",
        actor="a@x",
    )
    assert ответ is not None
    return ответ["result"]  # type: ignore[no-any-return]


def test_каталог_ask_ровно_нужный_набор() -> None:
    assert {s.name for s in TOOLS if s.confirm_effect} == СПРОСИТЬ_ЧЕЛОВЕКА


def test_подтверждение_у_каждого_правящего_кроме_названных() -> None:
    правящие = {s.name for s in TOOLS if TOOL_CLASSES[s.name].kind != READ}
    с_подтверждением = {s.name for s in TOOLS if confirm.requires_confirmation(s.name)}
    assert с_подтверждением == правящие - БЕЗ_ПОДТВЕРЖДЕНИЯ
    assert set(confirm.EXEMPT) == БЕЗ_ПОДТВЕРЖДЕНИЯ
    for имя in ("edit_checklist_item", "add_photo_cue", "import_add_findings"):
        assert имя in с_подтверждением, имя


def test_читающий_без_подтверждения_а_незнакомый_с_ним() -> None:
    assert not confirm.requires_confirmation("get_inspection")
    assert confirm.requires_confirmation("нет_такого_инструмента")


def test_схема_правящих_принимает_токен_а_остальных_нет() -> None:
    for s in TOOLS:
        свойства = s.input_schema.get("properties", {})
        ждёт = confirm.requires_confirmation(s.name)
        assert (confirm.TOKEN_ARGUMENT in свойства) == ждёт, s.name  # type: ignore[operator]


def test_без_токена_не_выполняется_и_отдаёт_описание_и_токен(счётчик: _Счётчик) -> None:
    р = _вызвать("danger", {"unit": "A"})

    assert счётчик.вызовы == []
    assert not р.get("isError")
    данные = р["structuredContent"]
    assert _ждёт_подтверждения(данные)
    assert "X" in р["content"][0]["text"]


def test_уровень_ask_велит_спросить_человека(счётчик: _Счётчик) -> None:
    р = _вызвать("danger", {"unit": "A"})

    assert р["structuredContent"]["level"] == confirm.LEVEL_ASK
    assert "Покажите это человеку" in р["content"][0]["text"]


def test_правящий_без_своего_текста_тоже_ждёт_токен_уровня_request(
    счётчик: _Счётчик,
) -> None:
    р = _вызвать("import_edit_finding", {"unit": "A"})

    assert счётчик.вызовы == []
    данные = р["structuredContent"]
    assert _ждёт_подтверждения(данные)
    assert данные["level"] == confirm.LEVEL_REQUEST
    текст = р["content"][0]["text"]
    assert "сам прямо попросил ровно это" in текст
    assert "просьбой человека не считается" in текст

    токен = данные["confirmation_token"]
    р2 = _вызвать("import_edit_finding", {"unit": "A", confirm.TOKEN_ARGUMENT: токен})

    assert not р2.get("isError")
    assert len(счётчик.вызовы) == 1


def _ждёт_подтверждения(данные: dict[str, Any]) -> bool:
    return (
        данные["status"] == "confirmation_required"
        and данные["executed"] is False
        and bool(данные["confirmation_token"])
    )


def _токен(имя: str, аргументы: dict[str, Any]) -> str:
    return str(_вызвать(имя, аргументы)["structuredContent"]["confirmation_token"])


def test_с_верным_токеном_и_теми_же_аргументами_выполняется(счётчик: _Счётчик) -> None:
    токен = _токен("danger", {"unit": "A"})

    р = _вызвать("danger", {"unit": "A", confirm.TOKEN_ARGUMENT: токен})

    assert not р.get("isError")
    assert len(счётчик.вызовы) == 1
    assert confirm.TOKEN_ARGUMENT not in счётчик.вызовы[0]


def test_токен_от_других_аргументов_отказ(счётчик: _Счётчик) -> None:
    токен = _токен("danger", {"unit": "A"})

    р = _вызвать("danger", {"unit": "B", confirm.TOKEN_ARGUMENT: токен})

    assert р["isError"] is True
    assert счётчик.вызовы == []


def test_токен_от_другого_инструмента_отказ(счётчик: _Счётчик) -> None:
    токен = _токен("danger", {"unit": "A"})

    р = _вызвать("danger2", {"unit": "A", confirm.TOKEN_ARGUMENT: токен})

    assert р["isError"] is True
    assert счётчик.вызовы == []


def test_токен_другого_арендатора_отказ(счётчик: _Счётчик) -> None:
    токен = _токен("danger", {"unit": "A"})

    р = _вызвать("danger", {"unit": "A", confirm.TOKEN_ARGUMENT: токен}, tenant="partner")

    assert р["isError"] is True
    assert счётчик.вызовы == []


def test_подделанный_и_мусорный_токен_отказ(счётчик: _Счётчик) -> None:
    for мусор in ("", "x", "9999999999.deadbeef", "abc.def"):
        р = _вызвать("danger", {"unit": "A", confirm.TOKEN_ARGUMENT: мусор})
        assert р["isError"] is True, мусор
    assert счётчик.вызовы == []


def test_просроченный_токен_отказ(счётчик: _Счётчик, monkeypatch: pytest.MonkeyPatch) -> None:
    токен = _токен("danger", {"unit": "A"})
    сейчас = confirm._now()
    monkeypatch.setattr(confirm, "_now", lambda: сейчас + confirm.TOKEN_TTL_SECONDS + 1)

    р = _вызвать("danger", {"unit": "A", confirm.TOKEN_ARGUMENT: токен})

    assert р["isError"] is True
    assert счётчик.вызовы == []


def test_читающий_выполняется_с_первого_вызова(счётчик: _Счётчик) -> None:
    р = _вызвать("list_inspections", {"unit": "A"})

    assert not р.get("isError")
    assert len(счётчик.вызовы) == 1


def test_роль_без_права_токена_не_получает() -> None:
    ответ = rpc.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "set_checklist_state", "arguments": {"state": "retired"}},
        },
        tenant="HQ",
        role=None,
    )
    assert ответ is not None
    р = ответ["result"]
    assert р["isError"] is True
    assert "structuredContent" not in р
