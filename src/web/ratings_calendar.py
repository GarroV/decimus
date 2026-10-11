"""Период раздела «Рейтинги»: «‹ 2026 Q3 ›», по щелчку — календарь «с — по».

Правило владельца (скилл `interface-logic`, п. 3): период — один календарь «с —
по» и стрелки, без рядов кнопок. Прежняя сетка кварталов, месяцев и списка
периодов РС (D357) снята 11.10.2026: «нахуя нам столько кнопок настроек
календаря?». Месяц, квартал и период РС по-прежнему узнаются — отрезок, совпавший
с ними, становится ими (`periods.range_period`).

Стрелка листает на длину выбранного периода и ведёт только туда, где есть
данные. Ни одного вычисления оценок — только ключи периодов (`periods`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from src.ratings import periods as rp

from .texts import t


@dataclass(frozen=True)
class Calendar:
    title: str
    prev: str | None
    next: str | None
    begin: date
    end: date


def _rs_title(p: rp.RatingPeriod, lang: str) -> str:
    return p.title_ru if lang == "ru" else p.title_en


def _title(period: rp.ReportPeriod, rs: tuple[rp.RatingPeriod, ...], lang: str) -> str:
    if period.kind == rp.KIND_MONTH:
        return f"{t(f'ratings.month.{period.begin.month}', lang)} {period.begin.year}"
    if period.kind == rp.KIND_QUARTER:
        return f"{period.begin.year} Q{(period.begin.month - 1) // 3 + 1}"
    found = next((p for p in rs if f"rs:{p.id}" == period.key), None)
    if found:
        return _rs_title(found, lang)
    return f"{period.begin:%d.%m.%Y} — {period.end:%d.%m.%Y}"


def build(
    selected: rp.ReportPeriod,
    data_months: tuple[date, ...],
    rs_periods: tuple[rp.RatingPeriod, ...],
    lang: str,
) -> Calendar:
    first = min(data_months, default=None)
    last = max(data_months, default=None)

    def reachable(period: rp.ReportPeriod | None) -> str | None:
        """Сосед, в котором есть хоть один месяц с данными."""
        if period is None or first is None or last is None:
            return None
        if period.end < first or period.begin > rp.month_period(last.year, last.month).end:
            return None
        return period.key

    return Calendar(
        title=_title(selected, rs_periods, lang),
        prev=reachable(rp.previous_period(selected, rs_periods=rs_periods)),
        next=reachable(rp.next_period(selected, rs_periods=rs_periods)),
        begin=selected.begin,
        end=selected.end,
    )
