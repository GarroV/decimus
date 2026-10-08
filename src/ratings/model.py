"""Общие типы рейтингов РС и РКО: что разборщики отдают импортёру.

Ни одного похода в базу и ни одного разбора — только форма данных. Типы
рейтинга и форматы — коды, не формулировки (конституция, принцип 5).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime

RS = "rs"
RKO = "rko"
RATING_TYPES = (RS, RKO)

FORMAT_RKO_VIOLATIONS = "rko-violations"
FORMAT_RKO_EVALUATIONS = "rko-evaluations"
FORMAT_RS_CHECKUPS = "rs-checkups"
FORMAT_SNAPSHOT = "snapshot"
FORMAT_SHEET_SCORES = "sheet-scores"
FORMATS = (
    FORMAT_RKO_VIOLATIONS,
    FORMAT_RKO_EVALUATIONS,
    FORMAT_RS_CHECKUPS,
    FORMAT_SNAPSHOT,
    FORMAT_SHEET_SCORES,
)

CATEGORY_VIOLATION = "violation"
CATEGORY_OTHER = "other"
CATEGORY_REMARK = "remark"

ISSUE_UNIT_UNMATCHED = "unit_unmatched"
ISSUE_COUNTRY_UNKNOWN = "country_unknown"
ISSUE_BAD_ROW = "bad_row"


ERR_NOT_UTF8 = "not_utf8"
ERR_EMPTY = "empty"
ERR_UNKNOWN_FORMAT = "unknown_format"
ERR_MISSING_COLUMNS = "missing_columns"
ERR_NOT_SHEET = "not_sheet"
ERR_BAD_PERIOD = "bad_period"


class RatingsFormatError(ValueError):
    """Файл не разобран целиком: формат не узнан или нарушен.

    `str(exc)` — русский текст для журнала и MCP. Веб показывает по `code` ключ
    `texts_ratings` на языке интерфейса, `params` подставляются в него (P15).
    """

    def __init__(self, message: str, code: str, **params: str) -> None:
        super().__init__(message)
        self.code = code
        self.params: Mapping[str, str] = params


@dataclass(frozen=True)
class UnitRef:
    dodo_id: str | None
    name: str
    country: str | None


@dataclass(frozen=True)
class PeriodRef:
    rating_type: str
    begin_on: date
    end_on: date
    title_ru: str
    title_en: str
    dodo_id: str | None = None


@dataclass(frozen=True)
class Violation:
    text: str
    category: str
    auto_detected: bool = False
    criterion_id: str | None = None
    parent_name: str | None = None
    deduction: float | None = None
    amount: int = 1


@dataclass(frozen=True)
class Checkup:
    rating_type: str
    dodo_id: str
    unit: UnitRef
    occurred_at: datetime | None
    channel: str
    period_dodo_id: str | None
    backoffice_url: str
    rating_url: str
    duration_min: int | None = None
    violations: tuple[Violation, ...] = ()
    row_no: int = 0


@dataclass(frozen=True)
class Evaluation:
    dodo_id: str
    country: str
    acceptance: str
    evaluated_at: datetime | None
    row_no: int = 0


@dataclass(frozen=True)
class Score:
    unit: UnitRef
    period: PeriodRef
    score: float
    status: str | None = None
    checkups_count: int | None = None
    row_no: int = 0


@dataclass(frozen=True)
class Remark:
    unit: UnitRef
    period: PeriodRef
    violation: Violation


@dataclass(frozen=True)
class CountryRef:
    code: str
    dodo_id: int | None = None


@dataclass(frozen=True)
class Issue:
    row_no: int
    reason: str
    detail: Mapping[str, str]


@dataclass(frozen=True)
class Parsed:
    format: str
    checkups: tuple[Checkup, ...] = ()
    evaluations: tuple[Evaluation, ...] = ()
    scores: tuple[Score, ...] = ()
    remarks: tuple[Remark, ...] = ()
    countries: tuple[CountryRef, ...] = ()
    developers: Mapping[str, str] = field(default_factory=dict)
    issues: tuple[Issue, ...] = ()
    #: Строки, отброшенные по правилу (страны вне IMF, D318), — не ошибка.
    skipped: int = 0
    #: Подпись для журнала, например «часть 2 из 3» у снимка.
    label: str | None = None
