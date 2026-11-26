"""JSON операционных метрик: точные окна, отсутствующие данные и native LFL."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import date
from typing import Any

from .performance import (
    CORE_METRICS,
    MEANS,
    METRICS,
    NativeLfl,
    Observation,
    Window,
    aggregate,
    comparison_json,
    comparison_windows,
    observation_json,
)


def _metrics(
    rows: Sequence[Observation], subject: str, windows: Mapping[str, Window]
) -> dict[str, Any]:
    lookup = {(r.subject_id, r.metric, r.period): r for r in rows}
    result = {}
    for metric in CORE_METRICS:
        current = lookup.get((subject, metric, windows["current"]))
        result[metric] = {
            "unit": METRICS[metric],
            "current": observation_json(current),
            **{
                key: comparison_json(current, lookup.get((subject, metric, windows[key])))
                for key in ("mom", "yoy")
            },
        }
    return result


def country_json(
    country: str,
    *,
    name: str,
    as_of: date,
    timezone: str,
    timezone_fallback: bool,
    rows: Sequence[Observation],
    lfl: Sequence[NativeLfl],
    names: Mapping[str, tuple[str, str]],
    loads: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """Нельзя дополнить пустую страну нулями или посчитать среднее средних."""
    windows = comparison_windows(as_of)
    data = [r for r in rows if r.country == country and r.period in windows.values()]
    # Источник может прямо дать country total, иначе сворачиваем unit с явным
    # expected_units. Реестр названий не является перечнем активных unit периода.
    for metric in CORE_METRICS:
        for period in windows.values():
            direct = [
                r
                for r in data
                if r.subject_id == country and r.metric == metric and r.period == period
            ]
            if direct:
                if metric in MEANS and direct[0].numerator is None:
                    data.remove(direct[0])
                    data.append(replace(direct[0], status="unavailable", reason="missing_weight"))
                continue
            units = [
                r
                for r in data
                if r.subject_id != country and r.metric == metric and r.period == period
            ]
            if len({r.currency for r in units}) > 1:
                data.append(
                    replace(
                        units[0],
                        subject_id=country,
                        value=None,
                        numerator=None,
                        denominator=None,
                        currency=None,
                        status="unavailable",
                        reason="currency_mismatch",
                    )
                )
                continue
            total = aggregate(units, expected_units=None)
            if total:
                data.append(total)
    unit_ids = {r.subject_id for r in data if r.subject_id != country}
    unit_ids.update(r.subject_id for r in lfl if r.country == country and r.subject_id != country)
    unit_ids.update(ident for ident, (cc, _) in names.items() if cc == country)
    return {
        "cc": country,
        "name": name,
        "as_of": as_of.isoformat(),
        "timezone": timezone,
        "timezone_fallback": timezone_fallback,
        "periods": {key: period.json() for key, period in windows.items()},
        "metrics": _metrics(data, country, windows),
        "lfl": [r.json() for r in lfl if r.country == country and r.subject_id == country],
        "loads": list(loads),
        "units": [
            {
                "dodo_id": ident,
                "name": names.get(ident, (country, ident))[1],
                "metrics": _metrics(data, ident, windows),
                "lfl": [r.json() for r in lfl if r.country == country and r.subject_id == ident],
            }
            for ident in sorted(
                unit_ids, key=lambda ident: (names.get(ident, (country, ident))[1], ident)
            )
        ],
    }
