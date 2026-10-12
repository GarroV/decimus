"""Заявка на обновление агрегаторов (D420): принять один раз, выполнить ботом, закрыть исходом.

Ядро — очередь, которая не плодит заявок и не теряет исход. Таблица подменена
памятью: настоящую (частичный уникальный индекс) проверяет `test_db_aggregators`
на базе, а здесь — что поведение поверх неё верно.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from src.bot import agg_loader
from src.db import agg_store
from src.db.agg_store import UpdateRequest
from src.db.migrate import MIGRATIONS_DIR
from src.ratings.aggregators import collect, queue

ДЕНЬ = date(2026, 10, 12)


class Очередь:
    """Таблица `agg.requests` в памяти с тем же правилом: открытая заявка одна."""

    def __init__(self) -> None:
        self.строки: list[UpdateRequest] = []

    def открытая(self) -> UpdateRequest | None:
        return next((r for r in self.строки if r.done_at is None), None)

    def поставить(self, aggregators: object, *, by: str) -> tuple[UpdateRequest, bool]:
        if (уже := self.открытая()) is not None:
            return уже, False
        заявка = UpdateRequest(
            len(self.строки) + 1,
            datetime.now(UTC),
            by,
            tuple(aggregators),  # type: ignore[call-overload]
            None,
            None,
            None,
        )
        self.строки.append(заявка)
        return заявка, True

    def закрыть(self, request_id: int, *, ok: bool, error: str | None = None) -> None:
        self.строки = [
            UpdateRequest(
                r.id,
                r.requested_at,
                r.requested_by,
                r.aggregators,
                datetime.now(UTC),
                "ok" if ok else "failed",
                error,
            )
            if r.id == request_id
            else r
            for r in self.строки
        ]


@pytest.fixture
def очередь(monkeypatch: pytest.MonkeyPatch) -> Очередь:
    q = Очередь()
    monkeypatch.setattr(agg_store, "open_request", q.открытая)
    monkeypatch.setattr(agg_store, "request_update", q.поставить)
    monkeypatch.setattr(agg_store, "finish_request", q.закрыть)
    return q


def test_повторная_заявка_не_плодит_вторую(очередь: Очередь) -> None:
    первая = queue.ask(["wolt"], by="mcp:HQ")
    вторая = queue.ask(["glovo"], by="anna")

    assert первая.created and not вторая.created
    assert вторая.request.id == первая.request.id and вторая.request.aggregators == ("wolt",)
    assert len(очередь.строки) == 1


def test_пустой_список_значит_все_и_имена_приводятся(очередь: Очередь) -> None:
    assert queue.ask(None, by="a").request.aggregators == ()
    очередь.строки.clear()
    assert queue.ask([" Wolt ", "wolt", "GLOVO"], by="a").request.aggregators == ("wolt", "glovo")


def test_незнакомый_агрегатор_отказ_без_заявки(очередь: Очередь) -> None:
    with pytest.raises(queue.UnknownAggregator, match="foody"):
        queue.ask(["wolt", "foody"], by="a")
    assert очередь.строки == []


def test_яндекс_еда_на_паузе_не_просится(очередь: Очередь) -> None:
    """Бот его не собирает (D397) — заявка обещала бы то, чего не будет."""
    with pytest.raises(queue.UnknownAggregator):
        queue.ask(["yandex_eda"], by="a")


def test_бот_собирает_названных_и_закрывает_заявку_удачей(очередь: Очередь) -> None:
    queue.ask(["wolt", "glovo"], by="a")
    звали: list[tuple[date, tuple[str, ...]]] = []

    def сборщик(today: date, *, only: tuple[str, ...]) -> tuple[collect.Outcome, ...]:
        звали.append((today, only))
        return tuple(collect.Outcome(k, True, 3, 3, None) for k in only)

    assert queue.fulfil(today=ДЕНЬ, run=сборщик) is True

    assert звали == [(ДЕНЬ, ("wolt", "glovo"))]
    (строка,) = очередь.строки
    assert строка.done_at is not None and строка.outcome == "ok" and строка.error is None
    # закрытая заявка не мешает следующей
    assert queue.ask(["wolt"], by="b").created is True


def test_сбой_агрегатора_виден_в_исходе_заявки(очередь: Очередь) -> None:
    queue.ask(None, by="a")

    def сборщик(today: date, *, only: tuple[str, ...]) -> tuple[collect.Outcome, ...]:
        return (
            collect.Outcome("wolt", True, 3, 3, None),
            collect.Outcome("glovo", False, 0, 0, "HTTP 503"),
        )

    queue.fulfil(today=ДЕНЬ, run=сборщик)

    (строка,) = очередь.строки
    assert строка.outcome == "failed" and строка.error == "glovo: HTTP 503"


def test_упавший_сборщик_не_оставляет_заявку_висеть(очередь: Очередь) -> None:
    queue.ask(["wolt"], by="a")

    def сборщик(today: date, *, only: tuple[str, ...]) -> tuple[collect.Outcome, ...]:
        raise RuntimeError("секрет в тексте не должен уйти в заявку")

    assert queue.fulfil(today=ДЕНЬ, run=сборщик) is True

    (строка,) = очередь.строки
    assert строка.outcome == "failed" and строка.error == "RuntimeError"


def test_пустая_очередь_сборщика_не_зовёт(очередь: Очередь) -> None:
    def сборщик(today: date, *, only: tuple[str, ...]) -> tuple[collect.Outcome, ...]:
        raise AssertionError("очередь пуста")

    assert queue.fulfil(today=ДЕНЬ, run=сборщик) is False


def test_заход_бота_берёт_заявку_и_не_ждёт_суток(
    очередь: Очередь, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue.ask(["wolt"], by="a")
    собрано: list[tuple[str, ...]] = []

    def сборщик(today: date, *, only: tuple[str, ...] = ()) -> tuple[collect.Outcome, ...]:
        собрано.append(only)
        return tuple(collect.Outcome(k, True, 1, 1, None) for k in only)

    monkeypatch.setattr(collect, "run_all", сборщик)
    monkeypatch.setattr(agg_store, "last_run", lambda: datetime.now(UTC))  # сутки не вышли

    agg_loader._tick(scheduled=False)

    assert собрано == [("wolt",)]
    assert очередь.строки[0].outcome == "ok"


def test_заход_без_заявки_расписание_идёт_по_часу(
    очередь: Очередь, monkeypatch: pytest.MonkeyPatch
) -> None:
    собрано: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        collect, "run_all", lambda today, only=(): собрано.append(tuple(only)) or ()
    )
    monkeypatch.setattr(agg_store, "last_run", lambda: None)  # сбора не было никогда

    agg_loader._tick(scheduled=False)  # минутный заход расписание не смотрит
    assert собрано == []
    agg_loader._tick(scheduled=True)  # часовой — смотрит
    assert собрано == [()]


def test_миграция_держит_одну_открытую_заявку_индексом() -> None:
    """Повтор «уже в очереди» держится на базе, а не на проверке в коде: две просьбы
    одновременно (веб и Claude) иначе обе увидели бы пустую очередь."""
    sql = (MIGRATIONS_DIR / "0052_agg_requests.sql").read_text(encoding="utf-8")
    assert "create unique index requests_one_open_idx" in sql
    assert "where done_at is null" in sql
