"""Правила оповещений о подключениях (D641): когда писать владельцу, а когда молчать."""

from __future__ import annotations

import pytest

from src.domain import health_alerts as rules


@pytest.mark.parametrize(
    ("light", "red_only", "expected"),
    [
        ("green", True, "ok"),
        ("red", True, "red"),
        ("yellow", True, None),  # проба: «не удалось проверить» — шум лимитов
        ("grey", True, None),
        ("yellow", False, "yellow"),  # сбор и вход Dodo IS: жёлтое оповещает
        ("red", False, "red"),
        ("grey", False, None),
    ],
)
def test_уровень_из_цвета(light: str, red_only: bool, expected: str | None) -> None:
    assert rules.level_of(light, red_only=red_only) == expected


@pytest.mark.parametrize(
    ("previous", "current", "expected"),
    [
        (None, "ok", None),  # кода в базе не было и всё в порядке — тишина
        ("ok", "ok", None),
        (None, "red", "alert"),  # новый код сразу сломан — это сообщение
        ("ok", "red", "alert"),
        ("ok", "yellow", "alert"),
        ("yellow", "red", "alert"),  # ухудшение — снова сообщение
        ("red", "yellow", "alert"),
        ("red", "red", None),  # повтора нет
        ("yellow", "yellow", None),
        ("red", "ok", "done"),
        ("yellow", "ok", "done"),
    ],
)
def test_решение_по_смене_состояния(
    previous: str | None, current: str, expected: str | None
) -> None:
    assert rules.decide(previous, current, baseline=False) == expected


@pytest.mark.parametrize("current", ["ok", "yellow", "red"])
def test_первый_заход_только_фиксирует(current: str) -> None:
    assert rules.decide(None, current, baseline=True) is None
    assert rules.decide("ok", current, baseline=True) is None
