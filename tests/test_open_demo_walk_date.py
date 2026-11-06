"""#1296: идущая проверка демо датирована сегодняшним днём, а не будущим.

`_walk` отдаёт `Visit` в `_build`, а тот сдвигает дату календаря демо к дню посева
(`shifted`). Дата, уже взятая как «сегодня», сдвигалась второй раз: 26 октября
проверка Northgate-1 в мини-аппе показывала 31-е.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from tools import seed_open_demo as seed


@pytest.mark.parametrize("сдвиг_дней", [0, 5, 400])
def test_идущая_проверка_демо_датирована_днём_посева(
    monkeypatch: pytest.MonkeyPatch, сдвиг_дней: int
) -> None:
    сегодня = seed.ANCHOR + timedelta(days=сдвиг_дней)

    class Дата(date):
        @classmethod
        def today(cls) -> Дата:
            return cls(сегодня.year, сегодня.month, сегодня.day)

    monkeypatch.setattr(seed, "date", Дата)
    собрано: list[tuple[int, Any]] = []

    def подмена(chat_id: int, visit: Any, *_a: Any, **_k: Any) -> None:
        собрано.append((chat_id, visit))

    monkeypatch.setattr(seed, "_build", подмена)

    seed._walk(Path("."))

    assert {chat for chat, _ in собрано} == {seed.WALK_CHAT, seed.WALK_CHAT_RU}
    for _, visit in собрано:
        день = seed.shifted(visit.date)
        assert день == сегодня, f"проверка обхода датирована {день}, а посев идёт {сегодня}"
