"""Период реестра проверок: «с — по» по дате обхода, по умолчанию текущий месяц.

Правило владельца (скилл `interface-logic`): период — календарём, с стрелками
← → рядом. Стрелка листает на длину выбранного: целый календарный месяц — на
месяц, произвольный отрезок — на его же длину. «Всё время» — явный выбор
(`period=all`), а не отсутствие параметров: без параметров экран открывается
текущим месяцем, и ссылка на «всё» обязана говорить это словами.

Только разбор адреса и арифметика дат — ни одной оценки. Отбор идёт в базе
(`queries.list_inspections(date_from=, date_to=)`), а не поверх прочитанной
страницы: реестр читается с пределом, и отбор поверх него терял бы проверки.
"""

from __future__ import annotations

from calendar import monthrange
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta

#: Значение `period`, которое снимает отбор по датам.
ALL = "all"


@dataclass(frozen=True)
class Period:
    """Отрезок по дате обхода, обе границы включительно; `None` — без границы."""

    start: date | None
    end: date | None

    @property
    def is_all(self) -> bool:
        return self.start is None and self.end is None

    @property
    def month(self) -> date | None:
        """Первое число месяца, если отрезок — ровно один календарный месяц."""
        if self.start is None or self.end is None or self.start.day != 1:
            return None
        последний = monthrange(self.start.year, self.start.month)[1]
        if self.end == self.start.replace(day=последний):
            return self.start
        return None

    def params(self) -> dict[str, str]:
        """Параметры адреса этого периода (пустые значения не попадают)."""
        if self.is_all:
            return {"period": ALL}
        return {
            "from": self.start.isoformat() if self.start else "",
            "to": self.end.isoformat() if self.end else "",
        }


def month_of(day: date) -> Period:
    """Календарный месяц, в котором лежит `day`."""
    начало = day.replace(day=1)
    return Period(начало, начало.replace(day=monthrange(day.year, day.month)[1]))


def _parse(value: str | None) -> date | None:
    try:
        return date.fromisoformat((value or "").strip()[:10])
    except ValueError:
        return None


def read(args: Mapping[str, str], *, today: date) -> Period:
    """Период из адреса. Непонятная дата не роняет страницу — она просто не граница.

    Перепутанные местами границы меняются местами: человек, выбравший «с 20
    по 5», хотел отрезок, а не пустой экран.
    """
    if (args.get("period") or "").strip() == ALL:
        return Period(None, None)
    начало, конец = _parse(args.get("from")), _parse(args.get("to"))
    if начало is None and конец is None:
        return month_of(today)
    if начало is not None and конец is not None and начало > конец:
        начало, конец = конец, начало
    return Period(начало, конец)


def shift(period: Period, step: int) -> Period | None:
    """Соседний отрезок той же длины; `None` — листать некуда (открытая граница)."""
    if period.start is None or period.end is None:
        return None
    месяц = period.month
    if месяц is not None:
        год, номер = divmod(месяц.month - 1 + step, 12)
        return month_of(date(месяц.year + год, номер + 1, 1))
    длина = (period.end - period.start).days + 1
    сдвиг = timedelta(days=длина * step)
    return Period(period.start + сдвиг, period.end + сдвиг)
