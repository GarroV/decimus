"""Три CSV-выгрузки рейтинга Dodo IS и узнавание формата по заголовку.

Формат узнаётся по набору колонок, имя файла не важно. Строка, которую не
удалось разобрать, не теряется: она уходит в журнал загрузки (`Issue`), а файл
целиком отвергается, только если узнать его нельзя.

Не храним: «Пользователь»/«Менеджер» (персональные данные), «Ответы клиента»
(D322).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from .countries import country_code, is_excluded
from .csvio import read_table
from .links import (
    backoffice_checkup_id,
    checkup_backoffice_url,
    checkup_rating_url,
    hex_id,
    parse_rating_link,
)
from .model import (
    CATEGORY_OTHER,
    CATEGORY_VIOLATION,
    ERR_MISSING_COLUMNS,
    ERR_UNKNOWN_FORMAT,
    FORMAT_RKO_EVALUATIONS,
    FORMAT_RKO_VIOLATIONS,
    FORMAT_RS_CHECKUPS,
    FORMAT_SHEET_SCORES,
    FORMAT_SNAPSHOT,
    ISSUE_BAD_ROW,
    ISSUE_COUNTRY_UNKNOWN,
    RKO,
    RS,
    Checkup,
    Evaluation,
    Issue,
    Parsed,
    RatingsFormatError,
    UnitRef,
    Violation,
)

_REQUIRED: dict[str, frozenset[str]] = {
    FORMAT_RKO_VIOLATIONS: frozenset(
        {
            "Страна",
            "Пиццерия",
            "Выявленные нарушения",
            "Другие проблемы",
            "Дата заказа",
            "Link",
            "KnowledgeBaseLink",
            "CheckupType",
        }
    ),
    FORMAT_RKO_EVALUATIONS: frozenset(
        {"CheckupId", "Ссылка на проверку", "Страна", "Дата и время оценки (UTC)"}
    ),
    FORMAT_RS_CHECKUPS: frozenset(
        {
            "Пиццерия",
            "Ссылка на отчет в беке",
            "Ссылка на отчет в БЗ",
            "Фактическая дата + время",
            "Страна",
            "Формат проверки",
        }
    ),
}
#: Колонка приёмки: в живом файле «Результат оценки», в части выгрузок — с
#: припиской «(Принято/Отклонено)». Ищется по началу имени.
_RESULT_PREFIX = "Результат оценки"
_AUTO_MARKS = ("(ML)", "(ИИ)", "(AI)")
_CHANNELS = {"доставка": "delivery", "ресторан": "restaurant"}
_RS_FORMATS = {"инспекция": "inspection", "онлайн": "online"}
_ACCEPTANCE = {"принято": "accepted", "отклонено": "rejected"}
_DATETIME = "%Y-%m-%d %H:%M:%S"
_UNKNOWN = (
    "Формат файла не узнан по заголовку. Ожидаются выгрузки rko-violations, "
    "rko-evaluations, rs-checkups, лист «Качество по пиццериям» (sheet-scores) "
    "или снимок рейтинга (JSON) — docs/14-ratings.md"
)


class _BadRow(ValueError):
    """Строка не разобрана — в журнал, файл продолжается."""


def csv_format(header: Sequence[str]) -> str | None:
    names = set(header)
    for fmt, required in _REQUIRED.items():
        if required <= names:
            return fmt
    return None


def detect_format(data: bytes) -> str:
    if data.lstrip(b"\xef\xbb\xbf \t\r\n").startswith(b"{"):
        return FORMAT_SNAPSHOT
    header, _ = read_table(data)
    fmt = csv_format(header)
    if fmt is not None:
        return fmt
    from .sheet import is_sheet_header  # лист зовёт csvio, не formats: цикла нет

    if is_sheet_header(header):
        return FORMAT_SHEET_SCORES
    raise RatingsFormatError(_UNKNOWN, ERR_UNKNOWN_FORMAT)


def _rows(data: bytes, fmt: str) -> tuple[tuple[str, ...], list[tuple[int, dict[str, str]]]]:
    header, rows = read_table(data)
    missing = _REQUIRED[fmt] - set(header)
    if missing:
        columns = ", ".join(sorted(missing))
        raise RatingsFormatError(
            f"В файле {fmt} нет колонок: {columns}",
            ERR_MISSING_COLUMNS,
            format=fmt,
            columns=columns,
        )
    return header, [(row_no, dict(zip(header, cells, strict=False))) for row_no, cells in rows]


def _when(value: str) -> datetime | None:
    value = value.strip()
    if not value:
        return None
    try:
        return datetime.strptime(value, _DATETIME).replace(tzinfo=UTC)
    except ValueError as exc:
        raise _BadRow(f"дата «{value}» не по образцу ГГГГ-ММ-ДД чч:мм:сс") from exc


def _country(row: dict[str, str], row_no: int, issues: list[Issue]) -> str | None:
    raw = row.get("Страна", "")
    code = country_code(raw)
    if code is None:
        issues.append(
            Issue(row_no, ISSUE_COUNTRY_UNKNOWN, {"country": raw, "unit": row.get("Пиццерия", "")})
        )
    return code


def _split(cell: str, category: str) -> tuple[Violation, ...]:
    counts: dict[str, int] = {}
    for part in cell.split(";"):
        text = part.strip()
        if text:
            counts[text] = counts.get(text, 0) + 1
    return tuple(
        Violation(text=text, category=category, auto_detected=text.endswith(_AUTO_MARKS), amount=n)
        for text, n in counts.items()
    )


def _checkup(
    row: dict[str, str],
    row_no: int,
    *,
    rating_type: str,
    country: str,
    back_col: str,
    rating_col: str,
    when_col: str,
    channel: str,
    duration: int | None = None,
    violations: tuple[Violation, ...] = (),
) -> Checkup:
    checkup_id = backoffice_checkup_id(row.get(back_col, ""))
    link = parse_rating_link(row.get(rating_col, ""))
    name = row.get("Пиццерия", "").strip()
    if checkup_id is None or link is None or not name:
        raise _BadRow("нет id проверки, id пиццерии или имени пиццерии")
    if link.checkup_id not in (None, checkup_id):
        raise _BadRow("id проверки в двух ссылках расходится")
    if link.rating_type not in (None, rating_type):
        raise _BadRow("ссылка ведёт в рейтинг другого типа")
    return Checkup(
        rating_type=rating_type,
        dodo_id=checkup_id,
        unit=UnitRef(link.unit_id, name, country),
        occurred_at=_when(row.get(when_col, "")),
        channel=channel,
        period_dodo_id=link.period_id,
        # Ссылки собираются заново из проверенных id: ячейка файла недоверенная,
        # а дальше URL попадает в href страницы.
        backoffice_url=checkup_backoffice_url(checkup_id),
        rating_url=checkup_rating_url(link.unit_id, rating_type, checkup_id, link.period_id),
        duration_min=duration,
        violations=violations,
        row_no=row_no,
    )


def _bad(row_no: int, row: dict[str, str], exc: Exception) -> Issue:
    return Issue(row_no, ISSUE_BAD_ROW, {"reason": str(exc), "unit": row.get("Пиццерия", "")})


def parse_rko_violations(data: bytes) -> Parsed:
    _, rows = _rows(data, FORMAT_RKO_VIOLATIONS)
    checkups: list[Checkup] = []
    issues: list[Issue] = []
    skipped = 0
    for row_no, row in rows:
        country = _country(row, row_no, issues)
        if country is None:
            continue
        if is_excluded(country):
            skipped += 1
            continue
        try:
            channel = _CHANNELS.get(row.get("CheckupType", "").casefold())
            if channel is None:
                raise _BadRow(f"неизвестный тип проверки «{row.get('CheckupType', '')}»")
            violations = _split(row.get("Выявленные нарушения", ""), CATEGORY_VIOLATION) + _split(
                row.get("Другие проблемы", ""), CATEGORY_OTHER
            )
            checkups.append(
                _checkup(
                    row,
                    row_no,
                    rating_type=RKO,
                    country=country,
                    back_col="Link",
                    rating_col="KnowledgeBaseLink",
                    when_col="Дата заказа",
                    channel=channel,
                    violations=violations,
                )
            )
        except _BadRow as exc:
            issues.append(_bad(row_no, row, exc))
    return Parsed(
        FORMAT_RKO_VIOLATIONS, checkups=tuple(checkups), issues=tuple(issues), skipped=skipped
    )


def parse_rko_evaluations(data: bytes) -> Parsed:
    header, rows = _rows(data, FORMAT_RKO_EVALUATIONS)
    result_col = next((h for h in header if h.startswith(_RESULT_PREFIX)), None)
    if result_col is None:
        raise RatingsFormatError(
            f"В файле {FORMAT_RKO_EVALUATIONS} нет колонки «{_RESULT_PREFIX}»",
            ERR_MISSING_COLUMNS,
            format=FORMAT_RKO_EVALUATIONS,
            columns=_RESULT_PREFIX,
        )
    evaluations: list[Evaluation] = []
    issues: list[Issue] = []
    skipped = 0
    for row_no, row in rows:
        country = _country(row, row_no, issues)
        if country is None:
            continue
        if is_excluded(country):
            skipped += 1
            continue
        try:
            checkup_id = hex_id(row.get("CheckupId", ""))
            acceptance = _ACCEPTANCE.get(row.get(result_col, "").casefold())
            if checkup_id is None or acceptance is None:
                raise _BadRow("нет id проверки или результат не «Принято»/«Отклонено»")
            evaluations.append(
                Evaluation(
                    checkup_id,
                    country,
                    acceptance,
                    _when(row.get("Дата и время оценки (UTC)", "")),
                    row_no=row_no,
                )
            )
        except _BadRow as exc:
            issues.append(_bad(row_no, row, exc))
    return Parsed(
        FORMAT_RKO_EVALUATIONS,
        evaluations=tuple(evaluations),
        issues=tuple(issues),
        skipped=skipped,
    )


def _minutes(value: str) -> int | None:
    value = value.strip()
    if not value:
        return None
    if not value.isdigit():
        raise _BadRow(f"продолжительность «{value}» не целое число минут")
    return int(value)


def parse_rs_checkups(data: bytes) -> Parsed:
    _, rows = _rows(data, FORMAT_RS_CHECKUPS)
    checkups: list[Checkup] = []
    issues: list[Issue] = []
    skipped = 0
    for row_no, row in rows:
        country = _country(row, row_no, issues)
        if country is None:
            continue
        if is_excluded(country):
            skipped += 1
            continue
        try:
            fmt = _RS_FORMATS.get(row.get("Формат проверки", "").casefold())
            if fmt is None:
                raise _BadRow(f"неизвестный формат проверки «{row.get('Формат проверки', '')}»")
            checkups.append(
                _checkup(
                    row,
                    row_no,
                    rating_type=RS,
                    country=country,
                    back_col="Ссылка на отчет в беке",
                    rating_col="Ссылка на отчет в БЗ",
                    when_col="Фактическая дата + время",
                    channel=fmt,
                    duration=_minutes(row.get("Продолжительность проверки, мин", "")),
                )
            )
        except _BadRow as exc:
            issues.append(_bad(row_no, row, exc))
    return Parsed(
        FORMAT_RS_CHECKUPS, checkups=tuple(checkups), issues=tuple(issues), skipped=skipped
    )
