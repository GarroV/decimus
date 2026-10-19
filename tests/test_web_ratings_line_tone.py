"""Цвет графиков РС и РКО по значению (D552, #974)."""

from __future__ import annotations

from src.web import ratings_line as rl


def test_тон_значения_по_порогам_80_и_90() -> None:
    assert [rl.tone(v) for v in (79.9, 80.0, 89.9, 90.0, 100.0)] == [
        "bad",
        "mid",
        "mid",
        "good",
        "good",
    ]


def test_полосы_покрывают_график_без_зазоров_и_только_нужные_зоны() -> None:
    sc = rl.scale([78.0, 92.0], threshold=85.0)

    assert [b.tone for b in sc.bands] == ["good", "mid", "bad"]
    assert sc.bands[0].top == 0.0
    for upper, lower in zip(sc.bands, sc.bands[1:], strict=False):
        assert round(upper.top + upper.height, 2) == lower.top
    assert round(sc.bands[-1].top + sc.bands[-1].height, 2) == rl.HEIGHT

    высокая = rl.scale([95.0, 97.0], threshold=85.0)
    assert [b.tone for b in высокая.bands] == ["good"]
