"""Дозагрузка истории карт возобновляется по частям и переживает перезапуск бота (#616).

База подменена словарём «что уже легло»: проверяется порядок работы, а не SQL.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.bot import maps_loader
from src.ratings import maps, pointer

СЕГОДНЯ = date(2026, 10, 15)
ФИЛИАЛЫ = ["u1", "u2", "u3"]


class _Склад:
    """Что уже лежит в базе: (филиал, окно) → дней покрыто."""

    def __init__(self) -> None:
        self.покрыто: set[str] = set()
        self.запросы: list[tuple[str, date, date]] = []
        self.отзывов_нет: set[str] = set()

    def uuids(self) -> list[str]:
        return list(ФИЛИАЛЫ)

    def covered(self, uuid: str, start: date, end: date) -> int:
        return pointer.HISTORY_WINDOW_DAYS if f"{uuid}|{start}" in self.покрыто else 0

    def history(self, _fetch: object, uuid: str, start: date, end: date) -> tuple[()]:
        self.запросы.append((uuid, start, end))
        if uuid not in self.отзывов_нет:
            self.покрыто.add(f"{uuid}|{start}")
        return ()

    def save(self, _companies: list, _ratings: list) -> tuple[int, int]:
        return (0, 0)


@pytest.fixture
def склад(monkeypatch: pytest.MonkeyPatch) -> _Склад:
    s = _Склад()
    monkeypatch.setattr(maps.maps_store, "company_uuids", s.uuids)
    monkeypatch.setattr(maps.maps_store, "covered_days", s.covered)
    monkeypatch.setattr(maps.maps_store, "save", s.save)
    monkeypatch.setattr(maps.pointer, "history", s.history)
    return s


def _шаг(склад: _Склад, бюджет: int, было: set | None = None) -> maps.BackfillStep:
    return maps.backfill_step(
        2, today=СЕГОДНЯ, max_requests=бюджет, fetch=lambda _p: {}, attempted=было
    )


def _до_конца(склад: _Склад, бюджет: int, было: set | None = None) -> None:
    for _ in range(100):  # предел: сломанное возобновление не должно вешать набор
        if _шаг(склад, бюджет, было).done:
            return
    pytest.fail("дозагрузка не закрылась за 100 шагов — окна запрашиваются заново")


def test_шаг_не_выходит_за_бюджет_запросов_и_говорит_что_не_закончил(склад: _Склад) -> None:
    итог = _шаг(склад, 2)

    assert len(склад.запросы) == 2
    assert итог.requests == 2
    assert not итог.done


def test_следующий_шаг_продолжает_с_места_обрыва_а_не_с_начала(склад: _Склад) -> None:
    _шаг(склад, 2)
    уже = list(склад.запросы)

    # «Перезапуск»: память шага пуста, продолжает база
    _до_конца(склад, 2)

    окон = round(2 * 30 / pointer.HISTORY_WINDOW_DAYS)
    assert len(склад.запросы) == len(ФИЛИАЛЫ) * окон
    assert len(set(склад.запросы)) == len(склад.запросы)  # ни одно окно не запрошено дважды
    assert склад.запросы[: len(уже)] == уже


def test_закрытая_история_не_тратит_запросов(склад: _Склад) -> None:
    _до_конца(склад, 100)
    склад.запросы.clear()

    итог = _шаг(склад, 100)

    assert итог.requests == 0
    assert итог.done
    assert склад.запросы == []


def test_окно_без_данных_у_филиала_не_запрашивается_заново_в_тот_же_день(склад: _Склад) -> None:
    """Филиал открылся недавно: окна старше его открытия не покроются никогда."""
    склад.отзывов_нет.add("u2")
    попытки: set = set()

    _до_конца(склад, 100, попытки)
    первый_круг = len(склад.запросы)
    итог = _шаг(склад, 100, попытки)

    assert итог.requests == 0
    assert итог.done
    assert len(склад.запросы) == первый_круг


def test_цикл_бота_досчитывает_историю_порциями_и_замолкает(
    склад: _Склад, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(maps_loader, "HISTORY_REQUESTS_PER_CYCLE", 2)
    monkeypatch.setattr(maps_loader, "HISTORY_MONTHS", 2)
    monkeypatch.setattr(maps_loader, "_today", lambda: СЕГОДНЯ)
    состояние = maps_loader.HistoryState()

    кругов = 0
    while not maps_loader.history_cycle(состояние, fetch=lambda _p: {}):
        кругов += 1
        assert кругов < 50
    всего = len(склад.запросы)

    assert кругов > 1  # порциями, а не одним махом
    assert maps_loader.history_cycle(состояние, fetch=lambda _p: {})
    assert len(склад.запросы) == всего  # закрытая история часа не тратит


def test_новый_день_сбрасывает_память_попыток() -> None:
    состояние = maps_loader.HistoryState()
    состояние.attempted.add("x")
    состояние.day = СЕГОДНЯ - timedelta(days=1)
    состояние.done = True

    состояние.roll(СЕГОДНЯ)

    assert not состояние.attempted
    assert not состояние.done
