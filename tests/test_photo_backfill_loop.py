"""#459, ревью #514: фоновая дозагрузка не умирает ни от сбоя, ни от конфигурации.

Упавшая задача asyncio молчит до отмены — дозагрузка встала бы навсегда и
незаметно. Поэтому проверяется сам цикл `backfill_forever`, а не один проход.
"""

from __future__ import annotations

from typing import Any

import pytest

from src import db
from src.bot import photo_backfill
from src.bot.photo_backfill import BackfillResult

pytestmark = pytest.mark.asyncio


class _Хватит(Exception):
    """Останавливает бесконечный цикл после нужного числа кругов."""


def _подменить(monkeypatch: pytest.MonkeyPatch, ответы: list[Any], кругов: int) -> list[bool]:
    """Проходы отвечают по очереди из `ответы`; сон после `кругов` кругов — стоп."""
    вызовы: list[bool] = []
    сон = {"n": 0}

    async def проход(fetch: Any, **kw: Any) -> BackfillResult:
        вызовы.append(kw.get("max_age_sec", "частый") is None)
        ответ = ответы.pop(0)
        if isinstance(ответ, BaseException):
            raise ответ
        return ответ  # type: ignore[no-any-return]

    async def спать(_: float) -> None:
        сон["n"] += 1
        if сон["n"] >= кругов:
            raise _Хватит

    monkeypatch.setattr(photo_backfill, "backfill_once", проход)
    monkeypatch.setattr(photo_backfill.asyncio, "sleep", спать)
    return вызовы


ПУСТО = BackfillResult(0, 0, 0, storage_down=False)


async def test_исключение_прохода_не_убивает_задачу(monkeypatch: pytest.MonkeyPatch) -> None:
    вызовы = _подменить(monkeypatch, [RuntimeError("сбой"), ПУСТО, ПУСТО], кругов=2)

    with pytest.raises(_Хватит):
        await photo_backfill.backfill_forever(bot=None)  # type: ignore[arg-type]

    assert len(вызовы) == 3, "после исключения прохода задача не пошла на второй круг"


async def test_незаданная_конфигурация_перепроверяется_на_следующем_круге(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ответы: list[Any] = [db.ConfigError("нет S3_BUCKET"), ПУСТО, ПУСТО]
    вызовы = _подменить(monkeypatch, ответы, кругов=2)

    with pytest.raises(_Хватит):
        await photo_backfill.backfill_forever(bot=None)  # type: ignore[arg-type]

    assert len(вызовы) == 3, "после ConfigError дозагрузка больше не пробовала"


async def test_редкий_проход_по_застарелым_идёт_раз_в_сутки(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    вызовы = _подменить(monkeypatch, [ПУСТО] * 4, кругов=3)

    with pytest.raises(_Хватит):
        await photo_backfill.backfill_forever(bot=None)  # type: ignore[arg-type]

    assert вызовы == [False, True, False, False], "редкий проход не раз в сутки"
