"""Справочник пиццерий из рейтингов РС и РКО (D556, #981) — правила без базы."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import pytest

from src.ratings import directory_feed as feed


@dataclass(frozen=True)
class _Profile:
    country_code: str
    name: str
    dodo_id: str | None
    city: str | None = None
    address: str | None = None


@dataclass(frozen=True)
class _Known:
    id: str
    name: str
    code: str | None


_TJ1, _TJ9, _RS1 = "a" * 32, "b" * 32, "c" * 32


@pytest.fixture
def база(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state: dict[str, Any] = {"since": None, "upserts": [], "codes": [], "known": {}}

    def live_units(since: date) -> list[tuple[str, str, str]]:
        state["since"] = since
        return [(_TJ1, "Dushanbe-1", "TJ"), (_TJ9, "Khujand-1", "TJ"), (_RS1, "Beograd-1", "RS")]

    monkeypatch.setattr(feed, "live_units", live_units)
    monkeypatch.setattr(
        feed,
        "by_country",
        lambda c: (_Profile("TJ", "Dushanbe-1 (Rudaki)", _TJ1, "dushanbe"),) if c == "TJ" else (),
    )
    monkeypatch.setattr(feed, "resolve_unit", lambda name, tenant: state["known"].get(name))
    monkeypatch.setattr(feed, "upsert_unit", lambda name, **kw: state["upserts"].append((name, kw)))
    monkeypatch.setattr(feed, "set_unit_codes", lambda codes: state["codes"].extend(codes))
    return state


def test_все_живые_точки_заводятся_имя_из_свода_иначе_из_рейтингов(база: dict[str, Any]) -> None:
    итог = feed.sync(today=date(2026, 10, 19))

    assert база["since"] == date(2026, 7, 21)
    assert (итог.seen, итог.put, итог.skipped) == (3, 3, ())
    по_коду = {kw["code"]: (name, kw) for name, kw in база["upserts"]}
    assert set(по_коду) == {_TJ1, _TJ9, _RS1}
    имя, kw = по_коду[_TJ1]
    assert kw["country"] == "TJ" and kw["city"] == "dushanbe"
    assert "Dushanbe-1" in kw["aliases"] and имя != "Dushanbe-1"
    assert по_коду[_TJ9][0] == "Khujand-1" and по_коду[_TJ9][1]["city"] is None


def test_страна_отбором_и_проверка_без_записи(база: dict[str, Any]) -> None:
    итог = feed.sync(today=date(2026, 10, 19), countries=("tj",), dry_run=True)

    assert (итог.seen, итог.put) == (2, 2)
    assert база["upserts"] == [] and база["codes"] == []


def test_имя_с_чужим_кодом_не_перевешивается_а_без_кода_получает_код(
    база: dict[str, Any],
) -> None:
    база["known"] = {
        "Khujand-1": _Known("u9", "Khujand-1", "f" * 32),
        "Beograd-1": _Known("u1", "Beograd-1", None),
    }

    итог = feed.sync(today=date(2026, 10, 19))

    assert итог.put == 2 and len(итог.skipped) == 1 and "Khujand-1" in итог.skipped[0]
    assert база["codes"] == [("u1", _RS1)]
