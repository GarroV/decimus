"""Лист «Качество по пиццериям» таблиц контроля (`sheet-scores`, D324).

Первые четыре колонки — по месту, а не по имени: девелопер, страна, пиццерия,
ссылка на рейтинг (из неё — id пиццерии). Дальше — периоды одного типа: РС —
полумесяцы («Сентябрь 2»), РКО — недели («05.05 — 11.05»). Года в подписях нет,
его выводит `assign_years`.
"""

from __future__ import annotations

import calendar
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from .countries import country_code, is_excluded
from .csvio import read_table
from .links import parse_rating_link
from .model import (
    ERR_BAD_PERIOD,
    ERR_NOT_SHEET,
    FORMAT_SHEET_SCORES,
    ISSUE_BAD_ROW,
    ISSUE_COUNTRY_UNKNOWN,
    ISSUE_DEVELOPER_CONFLICT,
    RKO,
    RS,
    Issue,
    Parsed,
    PeriodRef,
    RatingsFormatError,
    Score,
    UnitRef,
)

FIXED_COLUMNS = 4
MONTHS_RU = (
    "январь",
    "февраль",
    "март",
    "апрель",
    "май",
    "июнь",
    "июль",
    "август",
    "сентябрь",
    "октябрь",
    "ноябрь",
    "декабрь",
)
MONTHS_EN = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
_RS_LABEL = re.compile(
    r"^(?P<month>[а-яё]+)\s+(?P<part>[12])(?:\s+часть)?(?:\s+(?P<year>\d{4}))?$", re.I
)
_RKO_LABEL = re.compile(
    r"^(?P<d1>\d{1,2})\.(?P<m1>\d{1,2})(?:\.(?P<y1>\d{4}))?\s*[—–-]\s*"
    r"(?P<d2>\d{1,2})\.(?P<m2>\d{1,2})(?:\.\d{4})?$"
)


@dataclass(frozen=True)
class Label:
    rating_type: str
    begin_month: int
    begin_day: int
    end_month: int
    #: 0 — последний день месяца (второй полумесяц РС), считается от года.
    end_day: int
    year: int | None


def parse_label(text: str) -> Label | None:
    clean = " ".join(text.split())
    found = _RS_LABEL.match(clean)
    if found:
        name = found["month"].casefold()
        if name not in MONTHS_RU:
            return None
        month = MONTHS_RU.index(name) + 1
        first = found["part"] == "1"
        year = int(found["year"]) if found["year"] else None
        return Label(RS, month, 1 if first else 16, month, 15 if first else 0, year)
    found = _RKO_LABEL.match(clean)
    if found:
        d1, m1, d2, m2 = (int(found[k]) for k in ("d1", "m1", "d2", "m2"))
        if not (1 <= m1 <= 12 and 1 <= m2 <= 12 and 1 <= d1 <= 31 and 1 <= d2 <= 31):
            return None
        return Label(RKO, m1, d1, m2, d2, int(found["y1"]) if found["y1"] else None)
    return None


def _period_names(header: Sequence[str]) -> list[str]:
    return [name for name in header[FIXED_COLUMNS:] if name]


def is_sheet_header(header: Sequence[str]) -> bool:
    names = _period_names(header)
    labels = [parse_label(name) for name in names]
    if not names or any(label is None for label in labels):
        return False
    return len({label.rating_type for label in labels if label}) == 1


def _period(label: Label, year: int) -> PeriodRef:
    begin = date(year, label.begin_month, label.begin_day)
    if label.rating_type == RS:
        last = calendar.monthrange(year, label.begin_month)[1]
        end = date(year, label.end_month, label.end_day or last)
        part = 1 if label.begin_day == 1 else 2
        month = label.begin_month - 1
        return PeriodRef(
            RS,
            begin,
            end,
            f"{MONTHS_RU[month].capitalize()} {part} часть {year}",
            f"{MONTHS_EN[month]} part {part} {year}",
        )
    wraps = (label.end_month, label.end_day) < (label.begin_month, label.begin_day)
    end = date(year + 1 if wraps else year, label.end_month, label.end_day)
    title = f"{begin:%d.%m}–{end:%d.%m.%Y}"
    return PeriodRef(RKO, begin, end, title, title)


def assign_years(labels: Sequence[Label], *, today: date) -> list[PeriodRef]:
    """Год к подписи: колонки идут по времени, последняя — не позже `today`.

    Справа налево год уменьшается, когда начало периода «прыгает» вперёд
    (декабрь левее января). Подпись с годом задаёт год сама.
    """
    result: list[PeriodRef] = []
    year = today.year
    later: tuple[int, int] | None = None
    for label in reversed(labels):
        start = (label.begin_month, label.begin_day)
        if label.year is not None:
            year = label.year
        elif later is None:
            if start > (today.month, today.day):
                year -= 1
        elif start > later:
            year -= 1
        later = start
        result.append(_period(label, year))
    return list(reversed(result))


def _score(cell: str) -> float | None:
    clean = cell.strip().rstrip("%").strip().replace(",", ".")
    if not clean:
        return None
    value = float(clean)
    if not 0 <= value <= 100:
        raise ValueError(f"балл {value} вне 0–100")
    return value


def parse_sheet_scores(data: bytes, *, today: date) -> Parsed:
    header, rows = read_table(data)
    if not is_sheet_header(header):
        raise RatingsFormatError(
            "Это не лист «Качество по пиццериям»: после четырёх колонок (девелопер, страна, "
            "пиццерия, ссылка) ожидаются периоды рейтинга одного типа",
            ERR_NOT_SHEET,
        )
    columns = [
        (index, name) for index, name in enumerate(header) if index >= FIXED_COLUMNS and name
    ]
    labels = [label for _, name in columns if (label := parse_label(name)) is not None]
    try:
        periods = assign_years(labels, today=today)
    except ValueError as exc:
        raise RatingsFormatError(
            f"Дата периода в заголовке листа не существует: {exc}", ERR_BAD_PERIOD
        ) from exc
    scores: list[Score] = []
    issues: list[Issue] = []
    developers: dict[str, str] = {}
    conflicted: set[str] = set()  # по одному замечанию на страну, не на строку
    skipped = 0
    for row_no, cells in rows:
        cells = cells + [""] * (len(header) - len(cells))
        developer, country_raw, name, link_raw = cells[:FIXED_COLUMNS]
        country = country_code(country_raw)
        if country is None:
            issues.append(
                Issue(row_no, ISSUE_COUNTRY_UNKNOWN, {"country": country_raw, "unit": name})
            )
            continue
        if is_excluded(country):
            skipped += 1
            continue
        if not name:
            issues.append(
                Issue(row_no, ISSUE_BAD_ROW, {"reason": "нет имени пиццерии", "unit": ""})
            )
            continue
        if developer:
            known = developers.setdefault(country, developer)
            if known != developer and country not in conflicted:
                conflicted.add(country)
                issues.append(
                    Issue(
                        row_no,
                        ISSUE_DEVELOPER_CONFLICT,
                        {"country": country, "kept": known, "ignored": developer, "unit": name},
                    )
                )
        link = parse_rating_link(link_raw) if link_raw else None
        unit = UnitRef(link.unit_id if link else None, name, country)
        bad: list[str] = []
        for (index, column), period in zip(columns, periods, strict=True):
            try:
                value = _score(cells[index])
            except ValueError:
                bad.append(column)
                continue
            if value is not None:
                scores.append(Score(unit, period, value, row_no=row_no))
        if bad:
            issues.append(
                Issue(
                    row_no,
                    ISSUE_BAD_ROW,
                    {"reason": "не балл в колонках: " + ", ".join(bad), "unit": name},
                )
            )
    return Parsed(
        FORMAT_SHEET_SCORES,
        scores=tuple(scores),
        developers=developers,
        issues=tuple(issues),
        skipped=skipped,
    )
