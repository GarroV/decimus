"""Расход модели (D537): итоги, срезы и деньги экрана из сумм базы — без Flask и базы."""

from __future__ import annotations

from datetime import date

import pytest

from src.db.model_usage import UsageRow
from src.recognize.pricing import Price
from src.web import usage_view as v

PRICES = {"m": Price(input_per_1m=1.0, output_per_1m=2.0)}


def _row(
    dim: str,
    key: str,
    model: str = "m",
    *,
    i: int = 0,
    o: int = 0,
    calls: int = 1,
    failed: int = 0,
    label: str = "",
    audio: float = 0.0,
) -> UsageRow:
    return UsageRow(dim, key, label, model, calls, failed, i, o, audio)


def test_итог_берётся_из_среза_дней_а_не_сложением_всех_срезов() -> None:
    rows = (
        _row("day", "2026-10-01", i=1_000_000, o=500_000, calls=4, failed=1),
        _row("kind", "recognize", i=1_000_000, o=500_000, calls=4),
        _row("person", "u1", i=1_000_000, o=500_000, calls=4),
    )
    total = v.totals(rows, prices=PRICES)
    assert (total.calls, total.failed, total.tokens) == (4, 1, 1_500_000)
    assert total.cost == pytest.approx(1.0 + 1.0)


def test_модель_без_цены_не_входит_в_сумму_и_итог_помечен_неполным() -> None:
    rows = (
        _row("day", "2026-10-01", "m", i=1_000_000),
        _row("day", "2026-10-01", "чужая", i=1_000_000),
    )
    total = v.totals(rows, prices=PRICES)
    assert total.cost == pytest.approx(1.0)
    assert total.cost_partial is True


def test_ни_одной_цены_стоимость_неизвестна_а_не_ноль() -> None:
    total = v.totals((_row("day", "2026-10-01", "чужая", i=10),), prices=PRICES)
    assert total.cost is None
    assert v.money(total.cost) == "—"


def test_изменение_к_прошлому_периоду() -> None:
    now = v.Sum(calls=15, input_tokens=150, cost=3.0)
    before = v.Sum(calls=10, input_tokens=100, cost=2.0)
    d = v.delta(now, before)
    assert d.calls == pytest.approx(0.5) and d.tokens == pytest.approx(0.5)
    assert d.cost == pytest.approx(0.5)
    # Нет базы сравнения — не «+∞» и не 0, а пусто.
    assert v.delta(now, v.Sum()).calls is None
    assert v.delta(now, None).calls is None
    assert v.percent(0.5) == "+50%" and v.percent(-0.25) == "-25%" and v.percent(None) == "—"


def test_дни_ограниченного_периода_идут_подряд_с_пустыми_и_высота_от_максимума() -> None:
    rows = (_row("day", "2026-10-02", i=100), _row("day", "2026-10-04", i=50))
    bars = v.by_day(rows, start=date(2026, 10, 1), end=date(2026, 10, 4), prices=PRICES)
    assert [b.day for b in bars] == ["2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04"]
    assert [b.height for b in bars] == [0.0, 1.0, 0.0, 0.5]
    assert bars[1].number == 2


def test_дни_за_всё_время_только_с_данными() -> None:
    rows = (_row("day", "2026-01-05", i=1), _row("day", "2026-10-04", i=1))
    bars = v.by_day(rows, start=None, end=None, prices=PRICES)
    assert [b.day for b in bars] == ["2026-01-05", "2026-10-04"]


def test_модели_одного_среза_складываются_и_сортировка_по_токенам() -> None:
    rows = (
        _row("kind", "translate", "m", i=10, calls=1),
        _row("kind", "translate", "m2", i=30, calls=2),
        _row("kind", "recognize", "m", i=100, calls=1),
    )
    lines = v.by_kind(rows, prices=PRICES)
    assert [x.key for x in lines] == ["recognize", "translate"]
    assert lines[1].sum.calls == 3 and lines[1].sum.tokens == 40
    assert lines[0].share == 1.0 and lines[1].share == pytest.approx(0.4)


def test_люди_подпись_логин_или_telegram_или_пусто() -> None:
    rows = (
        _row("person", "u1", i=3, label="anna"),
        _row("person", "tg:77", i=2),
        _row("person", "", i=1),
    )
    labels = {x.key: x.label for x in v.by_person(rows, prices=PRICES)}
    assert labels == {"u1": "anna", "tg:77": "Telegram 77", "": ""}


def test_форматы_денег_и_чисел() -> None:
    assert v.money(12.345) == "$12.35"
    assert v.money(0.05) == "$0.05"
    assert v.money(0.00421) == "< $0.01"
    assert v.money(0.0099) == "< $0.01"
    assert v.money(0.0) == "$0.00"
    assert v.money(None) == "—"
    assert v.number(1234567) == "1 234 567"
