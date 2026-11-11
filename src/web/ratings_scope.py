"""D746: one saved personal country preference shared with the Countries screen."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

from src.db.ratings_read import CountryRow
from src.ratings import report

from . import country_filter


@dataclass(frozen=True)
class Scope:
    selection: report.Selection
    choices: report.Choices
    available: tuple[CountryRow, ...]
    saved: tuple[str, ...]
    mode: str


def resolve(args: Mapping[str, str], *, today: date) -> Scope:
    """Personal preference narrows presentation; it never grants inspection access."""
    selection, found = report.select(args, today=today)
    saved = country_filter.saved()
    mode = args.get("scope")
    if mode not in ("mine", "all"):
        mode = "mine" if saved else "all"
    available = found.countries
    if mode == "mine" and saved:
        codes = country_filter.narrow(tuple(row.code for row in available), saved)
        countries = tuple(row for row in available if row.code in codes)
        scoped = report.Choices(
            tuple(sorted({row.developer for row in countries if row.developer})),
            countries,
            found.rs_periods,
        )
        # Preserve a valid explicit selection; invalid ones use existing selection policy.
        group = selection.group
        value = selection.value
        if group == report.GROUP_COUNTRY and value not in codes:
            group, value = report.GROUP_IMF, None
        elif group == report.GROUP_DEVELOPER and value not in scoped.developers:
            group, value = report.GROUP_IMF, None
        selection = report.Selection(group, value, selection.period)
        found = scoped
    return Scope(selection, found, available, saved, mode)
