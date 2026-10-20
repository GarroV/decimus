"""F-130 (#1006): опасные инструменты MCP выполняются только вторым вызовом с токеном.

Диспетчер проверяется на подменённых спецификациях со счётчиком вызовов —
важно не «что сделал инструмент», а «дошёл ли вызов до обработчика». Состав
помеченных инструментов закреплён по настоящему каталогу.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from src.mcp import confirm, rpc
from src.mcp.catalogue import TOOLS, find

ПОМЕЧЕННЫЕ = {
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
}


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
    обычный = replace(база, name="plain", input_schema=схема, handler=сч, confirm_effect="")
    каталог = {s.name: s for s in (опасный, другой, обычный)}
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


def test_каталог_помечает_ровно_нужный_набор() -> None:
    assert {s.name for s in TOOLS if s.confirm_effect} == ПОМЕЧЕННЫЕ


def test_схема_помеченных_принимает_токен_а_остальных_нет() -> None:
    for s in TOOLS:
        свойства = s.input_schema.get("properties", {})
        assert (confirm.TOKEN_ARGUMENT in свойства) == (s.name in ПОМЕЧЕННЫЕ), s.name  # type: ignore[operator]


def test_без_токена_не_выполняется_и_отдаёт_описание_и_токен(счётчик: _Счётчик) -> None:
    р = _вызвать("danger", {"unit": "A"})

    assert счётчик.вызовы == []
    assert not р.get("isError")
    данные = р["structuredContent"]
    assert _ждёт_подтверждения(данные)
    assert "X" in р["content"][0]["text"]


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


def test_непомеченный_выполняется_с_первого_вызова(счётчик: _Счётчик) -> None:
    р = _вызвать("plain", {"unit": "A"})

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
