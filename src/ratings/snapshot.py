"""Снимок рейтинга Dodo IS (JSON) — то, что Claude собирает в браузере сотрудника.

Формат и процедура сбора — `docs/14-ratings.md`. Часть снимка самостоятельна:
повтор части или порядок частей ничего не ломают. Пиццерия с битым элементом
уходит в журнал целиком — половина её истории хуже, чем никакой. Замечания
периодов РКО отбрасываются: нарушения РКО идут из выгрузки `rko-violations`, и
два источника посчитали бы их дважды.

Снимок — недоверенный вход: любое поле может быть не тем типом, огромным или
пропасть. Плохая пиццерия или период уходит в журнал, плохой документ — отказ
`RatingsFormatError` с кодом; необработанных исключений наружу нет. Ссылки из
снимка не берутся вовсе: их собирают из канонического шаблона и проверенных id.
"""

from __future__ import annotations

import json
import math
from datetime import date
from typing import Any, TypeGuard

from .countries import country_code, is_excluded
from .links import hex_id
from .model import (
    CATEGORY_REMARK,
    ERR_BAD_JSON,
    ERR_BAD_SNAPSHOT,
    ERR_BAD_VERSION,
    FORMAT_SNAPSHOT,
    ISSUE_BAD_ROW,
    ISSUE_COUNTRY_UNKNOWN,
    RKO,
    RS,
    CountryRef,
    Issue,
    Parsed,
    PeriodRef,
    RatingsFormatError,
    Remark,
    Score,
    UnitRef,
    Violation,
)

SNAPSHOT_VERSION = 1
IMF_REGION = 2
RATING_TYPE_BY_CODE = {1: RKO, 2: RS}
#: Предел части для MCP: тело 1 МБ, а клиент может экранировать кириллицу в
#: `\uXXXX` (до 3× в размере). Веб принимает снимок любого размера до 25 МБ.
MCP_CHUNK_BYTES = 300_000

#: Пределы полей недоверенного входа: длиннее — строка снимка не наша.
MAX_TEXT = 300
MAX_SHORT = 64
MAX_COUNT = 1_000_000
MAX_DEDUCTION = 1_000
MAX_CHUNKS = 10_000
#: Длина значения в журнале: в журнал не кладут мегабайты из чужого файла.
_CLIP = 120


class _BadUnit(ValueError):
    pass


def _clip(value: object) -> str:
    text = str(value)
    return text if len(text) <= _CLIP else text[: _CLIP - 1] + "…"


def _is_int(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


def _list(value: object, what: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise _BadUnit(f"{what} не списком")
    return value


def _text(value: object, what: str, *, limit: int = MAX_TEXT) -> str | None:
    """Необязательная строка: `None`, если нет; не строка или слишком длинная — плохая пиццерия."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise _BadUnit(f"{what} не строкой")
    if len(value) > limit:
        raise _BadUnit(f"{what} длиннее {limit} знаков")
    return value.strip() or None


def _date(value: object) -> date:
    if not isinstance(value, str) or len(value) < 10 or value[10:11] not in ("", "T", " "):
        raise _BadUnit("дата периода не ГГГГ-ММ-ДД")
    try:
        return date.fromisoformat(value[:10])
    except ValueError as exc:
        raise _BadUnit("дата периода не ГГГГ-ММ-ДД") from exc


def _number(value: object, what: str) -> float | None:
    if value is None:
        return None
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise _BadUnit(f"{what} не числом")
    try:
        number = float(value)
    except OverflowError as exc:
        raise _BadUnit(f"{what} вне допустимых значений") from exc
    if not math.isfinite(number):
        raise _BadUnit(f"{what} не конечное число")
    return number


def _period(raw: object) -> PeriodRef:
    if not isinstance(raw, dict):
        raise _BadUnit("период без описания")
    period_id = hex_id(raw.get("id"))
    rating_type = (
        RATING_TYPE_BY_CODE.get(raw["rating_type"]) if _is_int(raw.get("rating_type")) else None
    )
    if period_id is None or rating_type is None:
        raise _BadUnit("у периода нет id или типа рейтинга")
    begin, end = _date(raw.get("begin")), _date(raw.get("end"))
    if end < begin:
        raise _BadUnit("конец периода раньше начала")
    title_ru = _text(raw.get("alias"), "название периода") or f"{begin:%d.%m.%Y}–{end:%d.%m.%Y}"
    title_en = _text(raw.get("alias_en"), "английское название периода") or title_ru
    return PeriodRef(rating_type, begin, end, title_ru, title_en, dodo_id=period_id)


def _violation(item: object) -> Violation | None:
    if not isinstance(item, dict):
        raise _BadUnit("замечание без описания")
    if item.get("wow"):
        return None
    text = _text(item.get("name"), "название замечания")
    amount = item.get("amount", 1)
    if text is None:
        raise _BadUnit("у замечания нет названия")
    if not _is_int(amount) or not 1 <= amount <= MAX_COUNT:
        raise _BadUnit("число замечаний не целое от 1 до миллиона")
    criterion = item.get("criterion_id")
    if criterion is not None and (
        not isinstance(criterion, str | int) or isinstance(criterion, bool)
    ):
        raise _BadUnit("criterion_id не строкой и не числом")
    if criterion is not None and len(str(criterion)) > MAX_SHORT:
        raise _BadUnit("criterion_id слишком длинный")
    deduction = _number(item.get("deduction"), "вычет")
    if deduction is not None and abs(deduction) > MAX_DEDUCTION:
        raise _BadUnit("вычет вне допустимых значений")
    return Violation(
        text=text,
        category=CATEGORY_REMARK,
        auto_detected=bool(item.get("auto")),
        criterion_id=None if criterion is None else str(criterion),
        parent_name=_text(item.get("parent"), "родитель замечания"),
        deduction=deduction,
        amount=amount,
    )


def _history(
    raw: dict[str, Any],
) -> tuple[dict[str, PeriodRef], list[tuple[PeriodRef, float, str | None]]]:
    periods: dict[str, PeriodRef] = {}
    history: list[tuple[PeriodRef, float, str | None]] = []
    for item in _list(raw.get("history"), "history"):
        if not isinstance(item, dict):
            raise _BadUnit("элемент истории без описания")
        period = _period(item.get("period"))
        key = period.dodo_id or ""
        if key in periods:
            raise _BadUnit("период повторён в истории")
        periods[key] = period
        score = _number(item.get("score"), "балл")
        if score is None:
            continue
        if not 0 <= score <= 100:
            raise _BadUnit("балл вне 0–100")
        status = item.get("status")
        if status is not None and (not isinstance(status, str | int) or isinstance(status, bool)):
            raise _BadUnit("статус не строкой и не числом")
        if status is not None and len(str(status)) > MAX_SHORT:
            raise _BadUnit("статус слишком длинный")
        history.append((period, score, None if status is None else str(status)))
    return periods, history


def _unit(raw: dict[str, Any], unit: UnitRef) -> tuple[list[Score], list[Remark], int]:
    periods, history = _history(raw)
    remarks: list[Remark] = []
    counts: dict[str, int] = {}
    seen: set[str] = set()
    skipped = 0
    for block in _list(raw.get("remarks"), "remarks"):
        if not isinstance(block, dict):
            raise _BadUnit("замечания без описания")
        period_id = hex_id(block.get("period_id")) or ""
        period = periods.get(period_id)
        if period is None:
            raise _BadUnit("замечания к периоду, которого нет в истории")
        if period_id in seen:
            raise _BadUnit("замечания периода повторены")
        seen.add(period_id)
        checkups = block.get("checkups")
        if checkups is not None and (not _is_int(checkups) or not 0 <= checkups <= MAX_COUNT):
            raise _BadUnit("число проверок не целое от 0 до миллиона")
        items = _list(block.get("items"), "items")
        if period.rating_type != RS:
            skipped += 1
            continue
        if checkups is not None:
            counts[period_id] = checkups
        for item in items:
            violation = _violation(item)
            if violation is not None:
                remarks.append(Remark(unit, period, violation))
    scores = [
        Score(unit, period, score, status=status, checkups_count=counts.get(period.dodo_id or ""))
        for period, score, status in history
    ]
    return scores, remarks, skipped


def _load(data: bytes) -> dict[str, Any]:
    try:
        doc = json.loads(data.decode("utf-8-sig"))
    # ValueError: не UTF-8, не JSON, слишком длинное число; RecursionError: слишком вложенный.
    except (RecursionError, ValueError) as exc:
        raise RatingsFormatError(
            f"Снимок не читается как JSON: {type(exc).__name__}", ERR_BAD_JSON
        ) from exc
    if (
        not isinstance(doc, dict)
        or not _is_int(doc.get("version"))
        or doc["version"] != SNAPSHOT_VERSION
    ):
        raise RatingsFormatError(
            f"Снимок не той версии: ожидается version = {SNAPSHOT_VERSION} (docs/14-ratings.md)",
            ERR_BAD_VERSION,
            expected=str(SNAPSHOT_VERSION),
        )
    return doc


def _countries(raw: object) -> tuple[dict[int, tuple[str | None, object]], tuple[CountryRef, ...]]:
    by_id: dict[int, tuple[str | None, object]] = {}
    refs: list[CountryRef] = []
    for item in raw if isinstance(raw, list) else ():
        country_id = item.get("id") if isinstance(item, dict) else None
        if not _is_int(country_id):
            raise RatingsFormatError(
                "Страна снимка без числового id", ERR_BAD_SNAPSHOT, part="countries"
            )
        name = item.get("name")
        code = country_code(name) if isinstance(name, str) else None
        by_id[country_id] = (code, item.get("region"))
        if code is not None and not is_excluded(code) and item.get("region") == IMF_REGION:
            refs.append(CountryRef(code, country_id))
    return by_id, tuple(refs)


def _label(chunk: object) -> str | None:
    if not isinstance(chunk, dict):
        return None
    index, total = chunk.get("index"), chunk.get("of")
    if _is_int(index) and _is_int(total) and 1 <= index <= total <= MAX_CHUNKS:
        return f"часть {index} из {total}"
    return None


def parse_snapshot(data: bytes) -> Parsed:
    doc = _load(data)
    countries_raw, units_raw = doc.get("countries"), doc.get("units")
    if not isinstance(countries_raw, list) or not isinstance(units_raw, list):
        raise RatingsFormatError(
            "В снимке нет списков countries и units", ERR_BAD_SNAPSHOT, part="countries, units"
        )
    by_id, refs = _countries(countries_raw)
    scores: list[Score] = []
    remarks: list[Remark] = []
    issues: list[Issue] = []
    skipped = 0
    for row_no, raw in enumerate(units_raw, start=1):
        if not isinstance(raw, dict):
            issues.append(
                Issue(row_no, ISSUE_BAD_ROW, {"reason": "пиццерия не описанием", "unit": ""})
            )
            continue
        unit_id = hex_id(raw.get("dodo_id"))
        name = raw.get("name")
        if unit_id is None or not isinstance(name, str) or not name.strip() or len(name) > MAX_TEXT:
            issues.append(
                Issue(
                    row_no,
                    ISSUE_BAD_ROW,
                    {"reason": "у пиццерии нет id или имени", "unit": _clip(name or "")},
                )
            )
            continue
        country_id = raw.get("country_id")
        code, region = by_id.get(country_id, (None, None)) if _is_int(country_id) else (None, None)
        if code is None:
            issues.append(
                Issue(
                    row_no,
                    ISSUE_COUNTRY_UNKNOWN,
                    {"unit": _clip(name), "country": _clip(country_id)},
                )
            )
            continue
        if is_excluded(code) or region != IMF_REGION:
            skipped += 1
            continue
        try:
            unit_scores, unit_remarks, unit_skipped = _unit(
                raw, UnitRef(unit_id, name.strip(), code)
            )
        except _BadUnit as exc:
            issues.append(Issue(row_no, ISSUE_BAD_ROW, {"reason": str(exc), "unit": _clip(name)}))
            continue
        scores += unit_scores
        remarks += unit_remarks
        skipped += unit_skipped
    return Parsed(
        FORMAT_SNAPSHOT,
        scores=tuple(scores),
        remarks=tuple(remarks),
        countries=refs,
        issues=tuple(issues),
        skipped=skipped,
        label=_label(doc.get("chunk")),
    )
