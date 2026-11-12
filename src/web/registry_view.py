"""Реестр проверок: отбор строк и подписи периода — без прав и без оценок.

Права на действия с проверкой считает карточка (`app._card_context`), оценку —
движок. Здесь только то, что сужает список и называет выбранный период.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING

from src.db.models import InspectionRow

from . import registry_period
from .dates import human_day
from .registry_period import Period
from .texts import t

if TYPE_CHECKING:
    from .inspections import Registry

#: «Пиццерии без проверки» на «Проверках» скрыты (D549): руководство не поняло,
#: «за период или вообще», а признак «ни разу не проверялась» живёт в карточке
#: страны. Код, тексты и тесты остались — вернуть одной строкой.
UNCHECKED_SHOWN = False


@dataclass(frozen=True)
class Filter:
    """Отбор строк реестра кодами: буква, вид, страна, город и часть названия."""

    grade: str = ""
    kind: str = ""
    country: str = ""
    city: str = ""
    q: str = ""
    # «Пиццерии без проверки» (D532): вместо проверок — точки без проверки за период.
    unchecked: bool = False

    @property
    def active(self) -> bool:
        return any((self.grade, self.kind, self.country, self.city, self.q, self.unchecked))

    def params(self) -> dict[str, str]:
        return {
            "q": self.q,
            "country": self.country,
            "city": self.city,
            "grade": self.grade,
            "kind": self.kind,
            "unchecked": "1" if self.unchecked else "",
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
    """Подпись периода: «Октябрь 2026», «2026», «1 — 15 окт 2026» или «Всё время».

    Месяц — словом (#963, #978): ISO-даты в шапке и на кнопке периода читались
    как служебная строка и не помещались в кнопку. Общее у краёв не повторяется:
    «1 сен — 31 окт 2026», а не «1 сен 2026 — 31 окт 2026».
    """
    if period.is_all:
        return t("registry.period.all", lang)
    if period.year is not None:
        return str(period.year)
    месяц = period.month
    if месяц is not None:
        return f"{t(f'registry.month.{месяц.month}', lang)} {месяц.year}"
    return _range_title(period.start, period.end, lang)


#: Неразрывный пробел внутри даты: перенос в узкой кнопке — только у тире.
_NBSP = "\u00a0"


def _range_title(start: date | None, end: date | None, lang: str) -> str:
    def край(day: date | None, *, year: bool = True, month: bool = True) -> str:
        if day is None:
            return "…"
        if not month:
            return str(day.day)
        if not year:
            return f"{day.day} {t(f'date.mon.{day.month}', lang)}".replace(" ", _NBSP)
        return human_day(day, lang).replace(" ", _NBSP)

    if start is None or end is None or start.year != end.year:
        return f"{край(start)} — {край(end)}"
    return f"{край(start, year=False, month=start.month != end.month)} — {край(end)}"


def period_link(period: Period, step: int, select: Callable[..., str]) -> str | None:
    """Адрес соседнего периода; `None` — листать некуда (всё время, открытая граница)."""
    сосед = registry_period.shift(period, step)
    if сосед is None:
        return None
    return select(**{"period": "", **сосед.params()})


def period_quick(
    period: Period, today: date, lang: str, select: Callable[..., str]
) -> tuple[dict[str, object], ...]:
    """Быстрые выборы периода: всё время, месяц, год и «Произвольный период».

    «Произвольный период» выбран, когда ни один из остальных не подошёл; он не
    ведёт по адресу (`custom`), а открывает поля «С» и «По» (`period.js`).

    Адреса явные (с датами или `period=all`), а не «без параметров»: у «Проверок»
    без параметров — всё время, у «Главной» — месяц, и ссылка не должна
    зависеть от умолчания экрана.
    """
    этот = registry_period.month_of(today)
    прошлый = registry_period.month_of(today.replace(day=1) - timedelta(days=1))
    этот_год = registry_period.year_of(today)
    прошлый_год = registry_period.year_of(date(today.year - 1, 1, 1))
    готовые = (
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
        {
            "title": t("registry.period.this_year", lang),
            "href": select(period="", **этот_год.params()),
            "on": period == этот_год,
        },
        {
            "title": t("registry.period.last_year", lang),
            "href": select(period="", **прошлый_год.params()),
            "on": period == прошлый_год,
        },
    )
    return (
        *готовые,
        {
            "title": t("registry.period.custom", lang),
            "href": "",
            "custom": True,
            "on": not any(q["on"] for q in готовые),
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


def place_totals(
    registry: Registry, current: Filter, place: Callable[[InspectionRow], tuple[str, str]]
) -> dict[tuple[str, str], int]:
    """Принятые периода по месту `{(страна, город): число}` — с отбором, но без места.

    Буква, вид и название режут счёт, страна и город нет: по ним он и разбит, и
    щелчок по стране оставляет остальной отбор. Счёт приходит из базы
    (`Registry.place_counts`) целиком; нет его — считается по строкам, что есть.
    """
    if registry.place_counts is not None:
        return {(страна, город): число for страна, город, число in registry.place_counts}
    без_места = Filter(grade=current.grade, kind=current.kind, q=current.q)
    итог: dict[tuple[str, str], int] = {}
    for row in registry.rows:
        if без_места.keeps(row, ("", "")):
            итог[place(row)] = итог.get(place(row), 0) + 1
    return итог


#: Классы записей в строке «На приёмке» — по убыванию тяжести. Прочие уровни
#: (`D0`, `R`, `NC`) нарушениями не считаются.
REVIEW_CLASSES = ("D3", "D2", "D1")


def review_classes_lines(
    rows: tuple[InspectionRow, ...],
    counts: Mapping[str, Mapping[str, int]] | None,
    lang: str,
) -> dict[str, str]:
    """Что внутри ждущей проверки: «D3: 1 · D2: 2 · D1: 4» или «без нарушений».

    Числа записей по классу берутся из тех же записей, что у карточки, — оценка
    не считается. Нет данных (`counts is None`) — пусто: строка молчит, а не
    говорит «без нарушений» там, где просто не прочиталось.
    """
    if counts is None:
        return {}
    строки: dict[str, str] = {}
    for row in rows:
        by_class = counts.get(row.id, {})
        части = [f"{код}: {by_class[код]}" for код in REVIEW_CLASSES if by_class.get(код)]
        строки[row.id] = " · ".join(части) if части else t("registry.review.no_findings", lang)
    return строки


def filters_changed(current: Filter, period: Period) -> int:
    """Сколько полей отбора не по умолчанию: период (умолчание — всё время) и пять отборов."""
    изменено = (current.grade, current.kind, current.country, current.city, current.q)
    return sum(1 for value in изменено if value) + (0 if period.is_all else 1)
