"""Реестр проверок: отбор строк и подписи периода — без прав и без оценок.

Права на действия с проверкой считает карточка (`app._card_context`), оценку —
движок. Здесь только то, что сужает список и называет выбранный период.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

from src.db.models import InspectionRow

from . import registry_period
from .registry_period import Period
from .texts import t


@dataclass(frozen=True)
class Filter:
    """Отбор строк реестра кодами: буква, вид, страна, город и часть названия."""

    grade: str = ""
    kind: str = ""
    country: str = ""
    city: str = ""
    q: str = ""

    @property
    def active(self) -> bool:
        return any((self.grade, self.kind, self.country, self.city, self.q))

    def params(self) -> dict[str, str]:
        return {
            "q": self.q,
            "country": self.country,
            "city": self.city,
            "grade": self.grade,
            "kind": self.kind,
        }

    def keeps(self, row: InspectionRow, place: tuple[str, str]) -> bool:
        """Подходит ли строка; `place` — страна и город точки по справочнику."""
        return (
            (not self.grade or row.grade == self.grade)
            and (not self.kind or row.kind == self.kind)
            and (not self.country or place[0] == self.country)
            and (not self.city or place[1] == self.city)
            and (not self.q or self.q.casefold() in row.unit_name.casefold())
        )


def period_title(period: Period, lang: str) -> str:
    """Подпись периода: «Октябрь 2026», «2026-10-01 — 2026-10-15» или «Всё время»."""
    if period.is_all:
        return t("registry.period.all", lang)
    месяц = period.month
    if месяц is not None:
        return f"{t(f'registry.month.{месяц.month}', lang)} {месяц.year}"
    начало = period.start.isoformat() if period.start else "…"
    конец = period.end.isoformat() if period.end else "…"
    return f"{начало} — {конец}"


def period_link(period: Period, step: int, select: Callable[..., str]) -> str | None:
    """Адрес соседнего периода; `None` — листать некуда (всё время, открытая граница)."""
    сосед = registry_period.shift(period, step)
    if сосед is None:
        return None
    return select(**{"period": "", **сосед.params()})


def period_quick(
    period: Period, today: date, lang: str, select: Callable[..., str]
) -> tuple[dict[str, object], ...]:
    """Быстрые выборы периода: всё время, этот месяц, прошлый.

    Адреса явные (с датами или `period=all`), а не «без параметров»: у «Проверок»
    без параметров — всё время, у «Главной» — месяц, и ссылка не должна
    зависеть от умолчания экрана.
    """
    этот = registry_period.month_of(today)
    прошлый = registry_period.month_of(today.replace(day=1) - timedelta(days=1))
    return (
        {
            "title": t("registry.period.all", lang),
            "href": select(**{"from": "", "to": "", "period": registry_period.ALL}),
            "on": period.is_all,
        },
        {
            "title": t("registry.period.this_month", lang),
            "href": select(period="", **этот.params()),
            "on": period == этот,
        },
        {
            "title": t("registry.period.last_month", lang),
            "href": select(period="", **прошлый.params()),
            "on": period == прошлый,
        },
    )


def period_quick_months(
    period: Period, today: date, lang: str, select: Callable[..., str]
) -> tuple[dict[str, object], ...]:
    """Быстрые выборы календаря (D477): прошлый, этот и следующий месяц.

    «Всё время» тут не предлагается: сеткой его не нарисовать. Адреса явные, с датами.
    """
    этот = registry_period.month_of(today)
    прошлый = registry_period.month_of(today.replace(day=1) - timedelta(days=1))
    следующий = registry_period.month_of((today.replace(day=28) + timedelta(days=4)).replace(day=1))
    return tuple(
        {
            "title": t(ключ, lang),
            "href": select(period="", **месяц.params()),
            "on": period == месяц,
        }
        for ключ, месяц in (
            ("registry.period.last_month", прошлый),
            ("registry.period.this_month", этот),
            ("calendar.period.next_month", следующий),
        )
    )
