"""#1017: пакет находок — записанные остаются, отказанные возвращаются с индексом."""

from __future__ import annotations

from typing import Any

import pytest

from src.mcp import import_batch as batch
from src.mcp.errors import ToolError


@pytest.fixture
def подмена(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    записано: list[str] = []

    def одна(**k: Any) -> tuple[int, list[str]]:
        if k["text"] == "плохая":
            raise ToolError("Движок не принял")
        записано.append(k["text"])
        return len(записано), (["was in previous"] if k["text"] == "повтор" else [])

    monkeypatch.setattr(batch, "_only_import", lambda ident, tenant: (None, object()))
    monkeypatch.setattr(batch, "_require_inspection_id", lambda x: x)
    monkeypatch.setattr(batch, "add_one", одна)
    monkeypatch.setattr(
        batch,
        "_short_view",
        lambda ident, tenant, note, warnings=(): {"note": note, "warnings": list(warnings)},
    )
    return записано


def _пакет(*находки: Any) -> dict[str, Any]:
    return batch.import_add_findings(  # type: ignore[return-value]
        tenant="HQ",
        store=object(),
        actor="a",
        inspection_id="i1",
        findings=list(находки),  # type: ignore[arg-type]
    )


def test_смешанный_пакет_пишет_годные_и_возвращает_отказ_с_индексом(подмена: list[str]) -> None:
    ответ = _пакет({"text": "ок"}, {"text": "плохая"}, {"text": "повтор"}, {"code": "X"})

    assert подмена == ["ок", "повтор"]
    assert ответ["added"] == [{"index": 0, "n": 1}, {"index": 2, "n": 2}]
    assert [r["index"] for r in ответ["refused"]] == [1, 3]
    assert "Движок не принял" in ответ["refused"][0]["reason"]
    assert "нет text" in ответ["refused"][1]["reason"]
    assert ответ["warnings"] == ["#2: was in previous"]
    assert "findings" not in ответ


def test_пустой_и_слишком_большой_пакет_отказ(подмена: list[str]) -> None:
    with pytest.raises(ToolError):
        _пакет()
    with pytest.raises(ToolError, match="не больше"):
        _пакет(*[{"text": "x"}] * 51)
    assert подмена == []
