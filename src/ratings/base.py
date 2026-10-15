"""Листы общей таблицы контроля «база рейтингов» (D464).

Каждый лист — выгрузка CSV с заголовком в первой строке; формат узнаётся по
заголовку (`formats._REQUIRED`). Периоды подписаны без года: РС — «Сентябрь 1»,
РКО — «05.01 — 11.01». Год берётся из даты самой строки, где она есть
(нарушения), иначе — последний год, в котором такой период уже начался.
Колонка «Месяц» в листах не читается: в ней бывают опечатки, а периоду верят.

Не храним: имя бизнес-девелопера из листов (ключ — страна и пиццерия; девелопер
страны ведётся справочником стран) и колонку «Cluster» (кластер — у страны).

Строка, которую не удалось разобрать, уходит в журнал, а не роняет файл. Две
строки одного периода пиццерии с разными значениями — признак того, что год в
подписи неясен: обе в журнал, ни одна не пишется.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from datetime import date, timedelta
from typing import TypeVar

from src.domain.unit_name import fold_unit_name, unit_name_skeleton

from .countries import is_excluded
from .csvio import read_table
from .formats import _bad, _BadRow, _country, _rows
from .links import parse_rating_link
from .model import (
    CATEGORY_REMARK,
    FORMAT_BASE_COLLECTION,
    FORMAT_BASE_RKO_VIOLATIONS,
    FORMAT_BASE_RS_VIOLATIONS,
    FORMAT_BASE_SCORES,
    ISSUE_BAD_ROW,
    RKO,
    RS,
    Collection,
    Issue,
    Parsed,
    PeriodRef,
    Remark,
    Score,
    ScoreFlags,
    UnitRef,
    Violation,
)
from .sheet import Label, parse_label, period_of, score_of

#: Запас на разницу часовых поясов: период, начавшийся «сегодня» по часам таблицы.
_TODAY_SLACK = timedelta(days=3)
_TYPES = {"рс": RS, "рко": RKO}
_YES = frozenset({"да", "yes", "true", "1"})
_NO = frozenset({"нет", "no", "false", "0", ""})
#: Дата ячейки из Apps Script: «Tue Sep 08 2026 08:38:00 GMT+0300 (…)».
_JS_DATE = re.compile(r"^[A-Za-z]{3} (?P<mon>[A-Za-z]{3}) (?P<day>\d{1,2}) (?P<year>\d{4}) ")
_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
_COUNT = re.compile(r"^\d{1,6}$")
#: Разделитель названий в ячейках «Название Д3 / Критичного / Обнуления».
_SEP = ", "

_T = TypeVar("_T")

#: Вместо id в справочнике ссылок: у имени разные id в ссылках РКО и РС или в разных строках.
AMBIGUOUS = ""


def row_date(cell: str) -> date | None:
    """Календарная дата из ячейки «Дата» листов нарушений; не разобралась — `None`."""
    found = _JS_DATE.match(cell.strip())
    if found is None or found["mon"].casefold() not in _MONTHS:
        return None
    month = _MONTHS.index(found["mon"].casefold()) + 1
    try:
        return date(int(found["year"]), month, int(found["day"]))
    except ValueError:
        return None


def _year_from_today(label: Label, today: date) -> int:
    """Последний год, в котором период с такой датой начала уже начался."""
    for year in range(today.year, today.year - 3, -1):
        try:
            if date(year, label.begin_month, label.begin_day) <= today + _TODAY_SLACK:
                return year
        except ValueError:  # 29 февраля в невисокосном году
            continue
    raise _BadRow("нет года, в котором период с такой датой начала мог начаться")


def _year_near(label: Label, seen: date) -> int:
    """Год, в котором период подписи ближе всего к дате строки.

    «Дата» листа нарушений — время оценки, а не проверки: она бывает днём позже конца
    недели, и у недели через Новый год это другой календарный год, чем у её начала
    («28.12 — 03.01» с датой 4 января — неделя декабря прошлого года). Берётся год,
    в котором строка лежит в периоде или ближе всего к нему.
    """
    best: tuple[int, int] | None = None
    for year in (seen.year - 1, seen.year, seen.year + 1):
        try:
            period = period_of(label, year)
        except ValueError:  # 29 февраля в невисокосном году
            continue
        gap = max((period.begin_on - seen).days, (seen - period.end_on).days, 0)
        if best is None or gap < best[0]:
            best = (gap, year)
    if best is None:
        raise _BadRow("нет года, в котором период с такой датой начала существует")
    return best[1]


def period_for(text: str, *, rating_type: str, today: date, seen: date | None = None) -> PeriodRef:
    """Период по подписи листа. `seen` — дата строки: она главнее вывода от «сегодня».

    Подпись не периода, период другого типа или несуществующая дата — `_BadRow`.
    """
    label = parse_label(text)
    if label is None:
        raise _BadRow(f"подпись периода «{text}» не узнана")
    if label.rating_type != rating_type:
        raise _BadRow(f"период «{text}» не относится к этому типу рейтинга")
    year = label.year or (_year_near(label, seen) if seen else _year_from_today(label, today))
    try:
        return period_of(label, year)
    except ValueError as exc:
        raise _BadRow(f"период «{text}» не существует в {year} году") from exc


def _unit(row: dict[str, str], country: str) -> UnitRef:
    name = row.get("Пиццерия", "").strip()
    if not name:
        raise _BadRow("нет имени пиццерии")
    return UnitRef(None, name, country)


def _flag(cell: str, column: str) -> bool:
    value = cell.strip().casefold()
    if value in _YES:
        return True
    if value in _NO:
        return False
    raise _BadRow(f"в колонке «{column}» не «Да» и не «Нет»: «{cell.strip()}»")


def _collapse(text: str) -> str | None:
    """«X, X, Y» → «X, Y»: названия флагов таблица склеивает через «, » и часто повторяет."""
    parts = dict.fromkeys(part for part in (" ".join(p.split()) for p in text.split(_SEP)) if part)
    return _SEP.join(parts) or None


def _named(row: dict[str, str], flag: str, name: str) -> tuple[bool, str | None]:
    return _flag(row.get(flag, ""), flag), _collapse(row.get(name, ""))


def _build(
    data: bytes,
    fmt: str,
    make: Callable[[dict[str, str], int, str], _T | None],
) -> tuple[list[_T], list[Issue], int]:
    """Общий обход: страна, отсечка стран вне IMF, `make` собирает запись или `_BadRow`."""
    _, rows = _rows(data, fmt)
    items: list[_T] = []
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
            item = make(row, row_no, country)
        except (_BadRow, ValueError) as exc:
            issues.append(_bad(row_no, row, exc))
            continue
        if item is None:
            skipped += 1
        else:
            items.append(item)
    return items, issues, skipped


def _key(unit: UnitRef, period: PeriodRef) -> tuple[str, str, str, date]:
    return (unit.country or "", unit.name.casefold(), period.rating_type, period.begin_on)


def _dedupe(
    items: Sequence[_T],
    key: Callable[[_T], tuple[str, str, str, date]],
    same: Callable[[_T], object],
    row_no: Callable[[_T], int],
    issues: list[Issue],
    unit_name: Callable[[_T], str],
) -> list[_T]:
    """Повтор периода пиццерии: одинаковые строки — одна; разные — ни одной, в журнал."""
    groups: dict[tuple[str, str, str, date], list[_T]] = {}
    for item in items:
        groups.setdefault(key(item), []).append(item)
    kept: list[_T] = []
    for group in groups.values():
        if len({same(item) for item in group}) == 1:
            kept.append(group[0])
            continue
        issues.append(
            Issue(
                row_no(group[0]),
                ISSUE_BAD_ROW,
                {
                    "reason": "период пиццерии повторён с разными значениями — год в подписи "
                    "неясен, строки не записаны",
                    "unit": unit_name(group[0]),
                },
            )
        )
    return kept


def parse_base_scores(data: bytes, *, today: date) -> Parsed:
    def make(row: dict[str, str], row_no: int, country: str) -> Score | None:
        kind = _TYPES.get(row.get("Тип проверки", "").strip().casefold())
        if kind is None:
            raise _BadRow(f"неизвестный тип проверки «{row.get('Тип проверки', '')}»")
        period = period_for(row.get("Период", ""), rating_type=kind, today=today)
        value = score_of(row.get("Балл", ""))
        if value is None:
            return None  # оценки нет — это не ошибка и не нулевой балл
        d3, d3_name = _named(row, "Нарушение Д3", "Название Д3")
        critical, critical_name = _named(row, "Критическое нарушение", "Название Критичного")
        zeroing, zeroing_name = _named(row, "Обнуление", "Название Обнуления")
        flags = ScoreFlags(d3, d3_name, critical, critical_name, zeroing, zeroing_name)
        return Score(_unit(row, country), period, value, row_no=row_no, flags=flags)

    scores, issues, skipped = _build(data, FORMAT_BASE_SCORES, make)
    scores = _dedupe(
        scores,
        lambda s: _key(s.unit, s.period),
        lambda s: (s.score, s.flags),
        lambda s: s.row_no,
        issues,
        lambda s: s.unit.name,
    )
    return Parsed(FORMAT_BASE_SCORES, scores=tuple(scores), issues=tuple(issues), skipped=skipped)


def _count(cell: str, column: str) -> int:
    if not _COUNT.match(cell.strip()):
        raise _BadRow(f"в колонке «{column}» не целое число: «{cell.strip()}»")
    return int(cell.strip())


def parse_base_collection(data: bytes, *, today: date) -> Parsed:
    def make(row: dict[str, str], row_no: int, country: str) -> Collection:
        period = period_for(row.get("Период", ""), rating_type=RKO, today=today)
        return Collection(
            _unit(row, country),
            period,
            restaurant=_count(row.get("Отчеты_Ресторан", ""), "Отчеты_Ресторан"),
            delivery=_count(row.get("Отчеты_Доставка", ""), "Отчеты_Доставка"),
            row_no=row_no,
        )

    items, issues, skipped = _build(data, FORMAT_BASE_COLLECTION, make)
    items = _dedupe(
        items,
        lambda c: _key(c.unit, c.period),
        lambda c: (c.restaurant, c.delivery),
        lambda c: c.row_no,
        issues,
        lambda c: c.unit.name,
    )
    return Parsed(
        FORMAT_BASE_COLLECTION, collections=tuple(items), issues=tuple(issues), skipped=skipped
    )


def _violations(data: bytes, fmt: str, rating_type: str, today: date) -> Parsed:
    def make(row: dict[str, str], row_no: int, country: str) -> Remark | None:
        text = row.get("Нарушение", "").strip()
        if not text:
            return None
        period = period_for(
            row.get("Период", ""),
            rating_type=rating_type,
            today=today,
            seen=row_date(row.get("Дата", "")),
        )
        return Remark(_unit(row, country), period, Violation(text, CATEGORY_REMARK), row_no)

    remarks, issues, skipped = _build(data, fmt, make)
    return Parsed(fmt, sheet_remarks=tuple(remarks), issues=tuple(issues), skipped=skipped)


def parse_base_rko_violations(data: bytes, *, today: date) -> Parsed:
    return _violations(data, FORMAT_BASE_RKO_VIOLATIONS, RKO, today)


def parse_base_rs_violations(data: bytes, *, today: date) -> Parsed:
    return _violations(data, FORMAT_BASE_RS_VIOLATIONS, RS, today)


def parse_directory(data: bytes) -> dict[str, str]:
    """Справочник ссылок «Пиццерия, Ссылка для РКО, Ссылка для РС» → имя → id Dodo IS.

    Ключ — имя после `fold_unit_name` (D472: «İzmir-4» и «Izmir-4» — одна пиццерия).
    Имя, за которым стоят разные id (в двух ссылках строки или в двух строках), и два
    имени с одним id получают `AMBIGUOUS` вместо id: ошибиться пиццерией хуже, чем
    оставить строку несопоставленной, и загрузка пишет такое имя в журнал, а не молчит.
    Id сравниваются без учёта регистра.
    """
    header, rows = read_table(data)
    if "Пиццерия" not in header:
        return {}
    ids: dict[str, set[str]] = {}
    for _, cells in rows:
        row = dict(zip(header, cells, strict=False))
        key = fold_unit_name(row.get("Пиццерия", ""))
        if not key:
            continue
        found = {
            link.unit_id
            for column in ("Ссылка для РКО", "Ссылка для РС")
            if (link := parse_rating_link(row.get(column, ""))) is not None
        }
        ids.setdefault(key, set()).update(found)
    return shared_ids_ambiguous({key: one_id(found) for key, found in ids.items() if found})


def directory_id(directory: Mapping[str, str], name: str) -> str | None:
    """id пиццерии из справочника по имени из листа оценок (#808).

    Сначала точное имя после `fold_unit_name`. Не нашлось — то же имя на другом алфавите:
    в справочнике «Новополоцк-1», в листе «Novopolotsk-1». Если по такому ключу сошлись
    имена с разными id, это `AMBIGUOUS`: ошибиться пиццерией хуже, чем не найти.
    """
    exact = directory.get(fold_unit_name(name))
    if exact is not None:
        return exact
    key = unit_name_skeleton(name)
    if not key:
        return None
    found = {dodo_id for known, dodo_id in directory.items() if unit_name_skeleton(known) == key}
    if not found:
        return None
    return next(iter(found)) if len(found) == 1 else AMBIGUOUS


def shared_ids_ambiguous(directory: dict[str, str]) -> dict[str, str]:
    """Id, на который ссылаются два разных имени, не достаётся ни одному из них.

    В настоящем справочнике у «Новополоцк-1» обе ссылки несут id «Полоцк-1»: кто из
    двух придёт в загрузку первым, забрал бы чужой id.
    """
    owners: dict[str, int] = {}
    for dodo_id in directory.values():
        if dodo_id != AMBIGUOUS:
            owners[dodo_id.casefold()] = owners.get(dodo_id.casefold(), 0) + 1
    return {
        key: AMBIGUOUS if dodo_id == AMBIGUOUS or owners[dodo_id.casefold()] > 1 else dodo_id
        for key, dodo_id in directory.items()
    }


def one_id(found: set[str]) -> str:
    """Единственный id из набора; несколько разных — `AMBIGUOUS`."""
    unique = {dodo_id.casefold(): dodo_id for dodo_id in found}
    return next(iter(unique.values())) if len(unique) == 1 else AMBIGUOUS
