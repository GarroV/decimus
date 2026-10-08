"""Лист «Качество по пиццериям» таблиц контроля (`sheet-scores`, D324).

Выгрузка «Файл → Скачать → CSV» из Google-таблицы. Над данными — служебные
строки («Кол-во пиццерий», «Месяц»); заголовком считается строка подписей
периодов среди первых `HEADER_WINDOW`. Первые четыре колонки — по месту, а не
по имени: девелопер, страна, пиццерия, ссылка на рейтинг (из неё — id
пиццерии). Колонки правее — периоды одного типа: РС — полумесяцы
(«Сентябрь 2»), РКО — недели («05.05 — 11.05»); колонка без подписи периода
(дубль «Пиццерия») баллов не несёт. Девелопер и страна стоят в первой строке
объединённого блока и тянутся вниз. Года в подписях нет, его выводит
`assign_years`.
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
#: Сколько первых строк просматривать в поисках подписей периодов.
HEADER_WINDOW = 10
#: «Нет оценки» в ячейке периода: пусто или прочерк любой длины.
_NO_SCORE = frozenset({"", "-", "–", "—"})
#: Строка-заголовок «Девелопер, Страна, Пиццерия» под подписями периодов.
_HEADER_COUNTRY = frozenset({"страна", "country"})
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


def is_sheet_header(header: Sequence[str]) -> bool:
    """Строка подписей периодов: есть хоть одна, и все одного типа рейтинга.

    Остальные ячейки строки (пустые, дубль «Пиццерия») периоды не делают и
    лист не отменяют — их колонки просто не баллы.
    """
    labels = [parse_label(name) for name in header[FIXED_COLUMNS:] if name.strip()]
    types = {label.rating_type for label in labels if label is not None}
    return len(types) == 1


def find_header_row(table: Sequence[tuple[int, Sequence[str]]]) -> int | None:
    """Индекс строки подписей периодов среди первых `HEADER_WINDOW` строк.

    Над ней у настоящего листа служебные строки («Кол-во пиццерий», «Месяц»).
    """
    for index, (_, cells) in enumerate(table[:HEADER_WINDOW]):
        if is_sheet_header(cells):
            return index
    return None


def is_sheet_table(header: Sequence[str], rows: Sequence[tuple[int, Sequence[str]]]) -> bool:
    return find_header_row([(1, header), *rows]) is not None


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


@dataclass(frozen=True)
class _Column:
    index: int
    name: str
    period: PeriodRef


def _score(cell: str) -> float | None:
    clean = cell.strip().rstrip("%").strip().replace(",", ".")
    if clean in _NO_SCORE:
        return None
    value = float(clean)
    if not 0 <= value <= 100:
        raise ValueError(f"балл {value} вне 0–100")
    return value


def _column_issue(header_no: int, reason: str) -> Issue:
    return Issue(header_no, ISSUE_BAD_ROW, {"reason": reason, "unit": ""})


def _period_columns(
    header_no: int, head: Sequence[str], *, today: date
) -> tuple[list[_Column], list[Issue]]:
    """Колонки-периоды с годом. Повтор начала периода — замечание, колонка пропущена.

    Две колонки с одной датой начала — опечатка в подписи («10.08 — 16.08» и
    «10.08 — 23.08»): склеить их значило бы молча затереть одни баллы другими,
    поэтому берётся левая, правая уходит в журнал.
    """
    labelled = [
        (index, name, label)
        for index, name in enumerate(head)
        if index >= FIXED_COLUMNS and (label := parse_label(name)) is not None
    ]
    try:
        periods = assign_years([label for _, _, label in labelled], today=today)
    except ValueError as exc:
        raise RatingsFormatError(
            f"Дата периода в заголовке листа не существует: {exc}", ERR_BAD_PERIOD
        ) from exc
    columns: list[_Column] = []
    issues: list[Issue] = []
    first: dict[date, str] = {}
    for (index, name, _), period in zip(labelled, periods, strict=True):
        if period.begin_on in first:
            reason = (
                f"колонка «{name}» начинается тем же днём, что «{first[period.begin_on]}», "
                "— пропущена, проверьте подпись"
            )
            issues.append(_column_issue(header_no, reason))
            continue
        first[period.begin_on] = name
        columns.append(_Column(index, name, period))
    return columns, issues


def _stray_score_columns(
    header_no: int, head: Sequence[str], body: Sequence[tuple[int, list[str]]]
) -> list[Issue]:
    """Колонка без подписи периода, но с числами — в журнал, а не молча мимо.

    Дубль «Пиццерия» (имена) пропускается тихо; числа под нераспознанной
    подписью («Сентябрь 3») — потерянные баллы, их надо увидеть.
    """
    issues: list[Issue] = []
    for index in range(FIXED_COLUMNS, len(head)):
        if parse_label(head[index]) is not None:
            continue  # период; повтор начала уже в журнале у `_period_columns`
        if any(_is_number(cells[index]) for _, cells in body if index < len(cells)):
            name = head[index] or f"№{index + 1}"
            issues.append(
                _column_issue(header_no, f"колонка «{name}» не подписана периодом — пропущена")
            )
    return issues


def _is_number(cell: str) -> bool:
    try:
        return _score(cell) is not None
    except ValueError:
        return False


def parse_sheet_scores(data: bytes, *, today: date) -> Parsed:
    header, rows = read_table(data)
    table: list[tuple[int, list[str]]] = [(1, list(header)), *rows]
    at = find_header_row(table)
    if at is None:
        raise RatingsFormatError(
            f"Это не лист «Качество по пиццериям»: в первых {HEADER_WINDOW} строках нет строки "
            "с периодами рейтинга одного типа (РС «Сентябрь 2» или РКО «05.05 — 11.05») "
            "правее четырёх колонок девелопер, страна, пиццерия, ссылка",
            ERR_NOT_SHEET,
        )
    header_no, head = table[at]
    body = table[at + 1 :]
    columns, issues = _period_columns(header_no, head, today=today)
    issues.extend(_stray_score_columns(header_no, head, body))
    return _parse_body(body, columns, width=len(head), issues=issues)


def _parse_body(
    body: Sequence[tuple[int, list[str]]],
    columns: Sequence[_Column],
    *,
    width: int,
    issues: list[Issue],
) -> Parsed:
    """Строки пиццерий. Девелопер и страна — в первой строке объединённого блока,
    ниже пусто: последнее непустое значение тянется вниз."""
    scores: list[Score] = []
    developers: dict[str, str] = {}
    conflicted: set[str] = set()  # по одному замечанию на страну, не на строку
    skipped = 0
    developer = country_raw = ""
    for row_no, raw in body:
        cells = raw + [""] * (width - len(raw))
        if cells[1].casefold() in _HEADER_COUNTRY:
            continue  # строка «Девелопер, Страна, Пиццерия» под подписями периодов
        developer = cells[0] or developer
        country_raw = cells[1] or country_raw
        name, link_raw = cells[2], cells[3]
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
            issue = _note_developer(developers, conflicted, country, developer)
            if issue is not None:
                issues.append(Issue(row_no, ISSUE_DEVELOPER_CONFLICT, {**issue, "unit": name}))
        link = parse_rating_link(link_raw) if link_raw else None
        unit = UnitRef(link.unit_id if link else None, name, country)
        row_scores, bad = _row_scores(unit, cells, columns, row_no)
        scores.extend(row_scores)
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


def _note_developer(
    developers: dict[str, str], conflicted: set[str], country: str, developer: str
) -> dict[str, str] | None:
    """Первый девелопер страны остаётся; другой — одно замечание на страну."""
    known = developers.setdefault(country, developer)
    if known != developer and country not in conflicted:
        conflicted.add(country)
        return {"country": country, "kept": known, "ignored": developer}
    return None


def _row_scores(
    unit: UnitRef, cells: Sequence[str], columns: Sequence[_Column], row_no: int
) -> tuple[list[Score], list[str]]:
    scores: list[Score] = []
    bad: list[str] = []
    for column in columns:
        try:
            value = _score(cells[column.index])
        except ValueError:
            bad.append(column.name)
            continue
        if value is not None:
            scores.append(Score(unit, column.period, value, row_no=row_no))
    return scores, bad
