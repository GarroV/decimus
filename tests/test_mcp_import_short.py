"""#1016: ответ записи загрузки короткий — затронутая находка и оценка, без списка."""

from __future__ import annotations

from typing import Any

import pytest

from src.mcp import imports

ПОЛНЫЙ: dict[str, Any] = {
    "id": "i1",
    "mode": "current",
    "status": "draft",
    "note": "read",
    "pct": 97.5,
    "grade": "A",
    "counts": {"D1": 2},
    "deductions": [{"x": 1}],
    "by_zone": {"hall": 1},
    "unit": "U",
    "findings": [{"n": 1, "code": "CLN05"}, {"n": 2, "code": "CLN06"}],
}


def test_короткий_ответ_без_списка_вычетов_и_зон(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(imports, "_view", lambda *a, **k: dict(ПОЛНЫЙ))

    ответ = imports._short_view("i1", tenant="HQ", note="finding #2 added", n=2, warnings=["w"])

    assert "findings" not in ответ
    assert "deductions" not in ответ
    assert "by_zone" not in ответ
    assert ответ["finding"] == {"n": 2, "code": "CLN06"}
    assert ответ["findings_total"] == 2
    assert ответ["warnings"] == ["w"]
    assert (ответ["pct"], ответ["grade"], ответ["counts"]) == (97.5, "A", {"D1": 2})


def test_у_снятия_нет_затронутой_находки(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(imports, "_view", lambda *a, **k: dict(ПОЛНЫЙ))

    assert imports._short_view("i1", tenant="HQ", note="removed")["finding"] is None
