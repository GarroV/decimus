"""MCP `import_ratings` (D320): Claude загружает файл и части снимка. Только токен УК."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from src.mcp import ratings_tools
from src.mcp.catalogue import KIND_RATINGS, find
from src.mcp.errors import ToolError
from src.mcp.rpc import RATINGS_CLOSED, handle
from src.ratings.importer import ImportReport
from src.ratings.model import RatingsFormatError


@pytest.fixture
def грузы(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    журнал: list[dict[str, Any]] = []

    def грузить(data: bytes, **kw: Any) -> ImportReport:
        журнал.append({"data": data, **kw})
        return ImportReport(
            7,
            "snapshot",
            "duplicate",
            label="часть 2 из 3",
            loaded_at=datetime(2026, 10, 8, 10, 0),
            chunk_index=2,
            chunk_of=3,
        )

    monkeypatch.setattr(ratings_tools, "import_file", грузить)
    return журнал


def _call(tenant: str, arguments: dict[str, Any]) -> dict[str, Any]:
    answer = handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "import_ratings", "arguments": arguments},
        },
        tenant=tenant,
        checklist=None,
        source=None,
        may_retract=False,
    )
    assert answer is not None
    return answer


def test_инструмент_своего_вида() -> None:
    spec = find("import_ratings")
    assert spec is not None and spec.kind == KIND_RATINGS
    assert spec.handler.__module__ == "src.mcp.ratings_tools"


def test_описание_берёт_размер_части_из_константы() -> None:
    from src.ratings.snapshot import MCP_CHUNK_BYTES

    spec = find("import_ratings")
    assert spec is not None and str(MCP_CHUNK_BYTES) in spec.description


def test_токен_уК_грузит(грузы: list[dict[str, Any]]) -> None:
    ответ = _call("HQ", {"kind": "snapshot", "content": '{"version": 1}'})
    текст = str(ответ["result"])
    assert "duplicate" in текст
    assert "chunk_index" in текст and "2026-10-08T10:00:00" in текст
    assert "уже загружен 2026-10-08T10:00:00" in текст
    assert грузы[0]["channel"] == "mcp" and грузы[0]["actor"] == "mcp:HQ"
    assert грузы[0]["data"] == b'{"version": 1}'


def test_токен_партнёра_отказ_до_двери(грузы: list[dict[str, Any]]) -> None:
    ответ = _call("GE", {"kind": "snapshot", "content": "{}"})
    assert RATINGS_CLOSED in str(ответ)
    assert грузы == []


def test_заслон_обработчика_не_пускает_партнёра(грузы: list[dict[str, Any]]) -> None:
    with pytest.raises(ToolError, match="УК"):
        ratings_tools.import_ratings(tenant="GE", kind="snapshot", content="{}")
    assert грузы == []


def test_незнакомый_вид_отказ(грузы: list[dict[str, Any]]) -> None:
    with pytest.raises(ToolError, match="rko-violations"):
        ratings_tools.import_ratings(tenant="HQ", kind="xlsx", content="x")


def test_неразобранный_файл_отказ_с_кодом_и_причиной(monkeypatch: pytest.MonkeyPatch) -> None:
    def ломать(*_a: Any, **_k: Any) -> ImportReport:
        raise RatingsFormatError("нет колонок: Link", "missing_columns")

    monkeypatch.setattr(ratings_tools, "import_file", ломать)
    with pytest.raises(ToolError, match=r"missing_columns.*Link"):
        ratings_tools.import_ratings(tenant="HQ", kind="rko-violations", content="a,b")
    ответ = _call("HQ", {"kind": "rko-violations", "content": "a,b"})
    assert ответ["result"]["isError"] is True
