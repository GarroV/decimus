"""#1017: пакет находок — записанные остаются, отказанные возвращаются с индексом."""

from __future__ import annotations

from contextlib import nullcontext
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest

from src.mcp import import_batch as batch
from src.mcp.errors import ToolError


@pytest.fixture
def подмена(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    записано: list[str] = []

    def одна(**k: Any) -> tuple[int, list[str], None]:
        if k["text"] == "плохая":
            raise ToolError("Движок не принял")
        записано.append(k["text"])
        return len(записано), (["was in previous"] if k["text"] == "повтор" else []), None

    monkeypatch.setattr(
        batch, "_only_import", lambda ident, tenant: (None, SimpleNamespace(origin="import"))
    )
    monkeypatch.setattr(batch, "_require_inspection_id", lambda x: x)
    monkeypatch.setattr(batch, "add_one", одна)
    monkeypatch.setattr(batch, "prior_inspection", lambda detail: None)
    monkeypatch.setattr(
        batch,
        "_short_view",
        lambda ident, tenant, note, warnings=(), repeat_candidates=(): {
            "note": note,
            "warnings": list(warnings),
        },
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


# --- #1019: подсказка о повторе ----------------------------------------------


def _одна_через_движок(monkeypatch: pytest.MonkeyPatch, прошлая: Any, *, repeat: bool = False):
    """add_one с подменой записи в базу: проверяем только решение о кандидате."""
    from src.db import imports as db
    from src.mcp import imports

    monkeypatch.setattr(imports, "_db", lambda **_: nullcontext())
    monkeypatch.setattr(imports, "_engine", lambda args: None)
    monkeypatch.setattr(db, "add_finding", lambda *a, **k: (7, None))
    return imports.add_one(
        tenant="HQ",
        store=object(),  # type: ignore[arg-type]
        ident="i1",
        шапка=SimpleNamespace(origin="import"),
        text="грязно",
        code="CLN13",
        level="D1",
        zone="hall",
        repeat=repeat,
        прошлая=прошлая,
    )


def test_прошлая_проверка_с_этим_пунктом_даёт_кандидата(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.db.models import PreviousInspection

    прошлая = PreviousInspection(date=date(2026, 9, 1), codes=frozenset({"CLN13"}))
    assert _одна_через_движок(monkeypatch, прошлая) == (7, [], date(2026, 9, 1))


def test_прошлой_проверки_нет_или_повтор_уже_задан_кандидата_нет(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.db.models import PreviousInspection

    прошлая = PreviousInspection(date=date(2026, 9, 1), codes=frozenset({"CLN13"}))
    # проверка ПОСЛЕ даты черновика в прошлую не попадает: запрос вернул None
    assert _одна_через_движок(monkeypatch, None)[2] is None
    assert _одна_через_движок(monkeypatch, прошлая, repeat=True)[2] is None
    чужой = PreviousInspection(date=date(2026, 9, 1), codes=frozenset({"OTHER"}))
    assert _одна_через_движок(monkeypatch, чужой)[2] is None


def test_пакет_отдаёт_repeat_candidates_и_слова(
    подмена: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def одна(**k: Any) -> tuple[int, list[str], date | None]:
        return 3, [], date(2026, 9, 1)

    monkeypatch.setattr(batch, "add_one", одна)
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        batch, "_short_view", lambda ident, **k: captured.update(k) or {"warnings": k["warnings"]}
    )
    _пакет({"text": "a"})
    assert captured["repeat_candidates"] == [{"n": 3, "date": "2026-09-01"}]
    assert "2026-09-01" in captured["warnings"][0]
