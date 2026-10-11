"""Блоки «Стандарты · РС» и «Клиентский опыт · РКО» на «Главной» (D378).

Образец — главная Swarm (`QualityWidgets.tsx`): крупная цифра, движение к
прошлому месяцу, сравнение с IMF, плашки и график по месяцам. Отличия — по
решениям decimus:

* среднее группы — среднее средних пиццерий (D353, `summary.group_average`),
  а не простое среднее всех точек корзины, как в Swarm;
* линии нормы нет, пока контролинг её не задал (D379): ни 90 / 94.6 из таблиц
  Swarm, ни 85 (порог Top / Bottom) нормой не считаются. Плашка «ниже порога»
  говорит именно о пороге Top / Bottom и так и подписана;
* IMF рисуется пунктиром у всех, партнёру тоже (D378).

Расчёт — чистые функции над фактами рейтинга; в базу ходит только `load`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from src.db import ratings_read as read
from src.ratings.model import RKO, RS
from src.ratings.summary import Fact, group_average, unit_averages

#: Сколько месяцев на графике: горизонт блока свой, он подписан на блоке.
MONTHS = 8

#: Размер графика в единицах `viewBox`; рисуется шаблоном, растягивается CSS.
WIDTH = 320
HEIGHT = 120
PAD_LEFT = 28
PAD_RIGHT = 6
PAD_TOP = 8
PAD_BOTTOM = 18


@dataclass(frozen=True)
class Gauge:
    """Что показывает блок одного рейтинга.

    `value` — средняя подборки за последний месяц, где у неё есть оценки
    (`month`); `delta` — к предыдущему такому месяцу. `rated` — пиццерий с
    оценкой в этом месяце, `below` — из них ниже порога Top / Bottom.
    """

    kind: str
    months: tuple[date, ...]
    series: tuple[float | None, ...]
    imf_series: tuple[float | None, ...]
    month: date | None
    value: float | None
    delta: float | None
    imf: float | None
    rated: int
    below: int
    threshold: float


def month_window(until: date, n: int = MONTHS) -> tuple[date, ...]:
    """Первые числа `n` месяцев по месяц `until` включительно, старые первыми."""
    out = []
    year, month = until.year, until.month
    for _ in range(n):
        out.append(date(year, month, 1))
        year, month = (year - 1, 12) if month == 1 else (year, month - 1)
    return tuple(reversed(out))


def _in_month(facts: Sequence[Fact], month: date) -> list[Fact]:
    return [f for f in facts if f.begin_on.replace(day=1) == month]


def monthly(
    facts: Sequence[Fact], kind: str, countries: Sequence[str], months: Sequence[date]
) -> tuple[float | None, ...]:
    """Средняя группы за каждый месяц: периоды, начавшиеся в месяце, по пиццериям (D353).

    Месяц без оценок — `None`: линия на нём рвётся, а не дорисовывается.
    """
    return tuple(group_average(_in_month(facts, m), kind, countries) for m in months)


def _last(series: Sequence[float | None]) -> int | None:
    for i in range(len(series) - 1, -1, -1):
        if series[i] is not None:
            return i
    return None


def gauge(
    facts: Sequence[Fact],
    kind: str,
    *,
    countries: Sequence[str],
    imf: Sequence[str],
    months: Sequence[date],
    threshold: float,
) -> Gauge:
    """Собрать блок рейтинга `kind` для подборки `countries` на фоне IMF."""
    series = monthly(facts, kind, countries, months)
    imf_series = monthly(facts, kind, imf, months)
    last = _last(series)
    if last is None:
        return Gauge(
            kind, tuple(months), series, imf_series, None, None, None, None, 0, 0, threshold
        )
    before = _last(series[:last])
    value = series[last]
    delta = None
    previous = series[before] if before is not None else None
    if value is not None and previous is not None:
        delta = round(value - previous, 1) + 0.0  # + 0.0 убирает «-0.0»
    month = months[last]
    where = {f.unit: f.country for f in facts}
    averages = {
        unit: avg
        for unit, avg in unit_averages(_in_month(facts, month), kind).items()
        if where[unit] in countries
    }
    return Gauge(
        kind=kind,
        months=tuple(months),
        series=series,
        imf_series=imf_series,
        month=month,
        value=value,
        delta=delta,
        imf=imf_series[last],
        rated=len(averages),
        below=sum(1 for avg in averages.values() if avg < threshold),
        threshold=threshold,
    )


@dataclass(frozen=True)
class Chart:
    """Геометрия графика: ломаные (по куску на непрерывный отрезок) и деления."""

    width: int
    height: int
    line: tuple[str, ...]
    imf: tuple[str, ...]
    ticks: tuple[tuple[float, str], ...]
    labels: tuple[tuple[float, date], ...]
    dots: tuple[tuple[float, float], ...]


def _nice_step(span: float) -> float:
    for step in (1, 2, 5, 10, 20, 25, 50):
        if span / step <= 5:
            return float(step)
    return 100.0


def chart(g: Gauge) -> Chart | None:
    """Ломаные подборки и IMF в координатах `viewBox`. Данных нет — `None`."""
    values = [v for v in (*g.series, *g.imf_series) if v is not None]
    if not values:
        return None
    step = _nice_step(max(max(values) - min(values), 1.0))
    low = (min(values) // step) * step
    high = (max(values) // step + 1) * step
    inner_w = WIDTH - PAD_LEFT - PAD_RIGHT
    inner_h = HEIGHT - PAD_TOP - PAD_BOTTOM
    n = len(g.months)

    def x(i: int) -> float:
        return round(PAD_LEFT + (inner_w * i / (n - 1) if n > 1 else inner_w / 2), 1)

    def y(v: float) -> float:
        return round(PAD_TOP + inner_h * (high - v) / (high - low), 1)

    def paths(series: Sequence[float | None]) -> tuple[str, ...]:
        out: list[str] = []
        run: list[str] = []
        for i, v in enumerate(series):
            if v is None:
                if len(run) > 1:
                    out.append(" ".join(run))
                run = []
                continue
            run.append(f"{'M' if not run else 'L'}{x(i)} {y(v)}")
        if len(run) > 1:
            out.append(" ".join(run))
        return tuple(out)

    ticks = []
    v = low
    while v <= high + 1e-9:
        ticks.append((y(v), f"{v:g}"))
        v += step
    return Chart(
        width=WIDTH,
        height=HEIGHT,
        line=paths(g.series),
        imf=paths(g.imf_series),
        ticks=tuple(ticks),
        labels=tuple((x(i), m) for i, m in enumerate(g.months)),
        # Одиночный месяц между пропусками ломаной не даёт — точка его показывает.
        dots=tuple((x(i), y(v)) for i, v in enumerate(g.series) if v is not None),
    )


@dataclass(frozen=True)
class Ratings:
    """Оба блока и значения стран — для таблицы «Мои страны» (в месяце блока)."""

    rs: Gauge
    rko: Gauge
    by_country: dict[str, tuple[float | None, float | None]]


def by_country(
    facts: Sequence[Fact], g: Gauge, countries: Sequence[str]
) -> dict[str, float | None]:
    """Средняя каждой страны в месяце блока `g` — тем же правилом D353."""
    if g.month is None:
        return {code: None for code in countries}
    month = _in_month(facts, g.month)
    return {code: group_average(month, g.kind, [code]) for code in countries}


def load(countries: Sequence[str] | None, *, until: date) -> Ratings | None:
    """Блоки РС и РКО подборки по месяц `until`. Стран IMF в базе нет — `None`."""
    imf = tuple(row.code for row in read.countries() if row.is_imf)
    if not imf:
        return None
    months = month_window(until)
    end = date(until.year + until.month // 12, until.month % 12 + 1, 1)
    facts = [
        Fact(*row)
        for row in read.score_facts(countries=imf, begin=months[0], end=end)
        if row[5] < end
    ]
    threshold = read.settings()["top_threshold"]
    mine = list(imf) if countries is None else [code for code in countries if code in imf]
    rs, rko = (
        gauge(facts, kind, countries=mine, imf=imf, months=months, threshold=threshold)
        for kind in (RS, RKO)
    )
    rs_by, rko_by = by_country(facts, rs, mine), by_country(facts, rko, mine)
    return Ratings(rs, rko, {code: (rs_by[code], rko_by[code]) for code in mine})


#: Сколько месяцев назад искать последнюю оценку пиццерии для колонки таблицы.
LATEST_MONTHS = 6


def latest_by_unit(facts: Sequence[Fact]) -> dict[str, tuple[float | None, float | None]]:
    """Последняя оценка каждой пиццерии: `{код Dodo: (РС, РКО)}` (D398).

    «Последняя» — по началу периода рейтинга; у пиццерии без оценки нужного вида
    в окне там `None`, и таблица рисует прочерк, а не ноль.
    """
    newest: dict[tuple[str, str], Fact] = {}
    for fact in facts:
        key = (fact.unit, fact.rating_type)
        seen = newest.get(key)
        if seen is None or (fact.begin_on, fact.period_id) > (seen.begin_on, seen.period_id):
            newest[key] = fact
    units = {unit for unit, _ in newest}
    return {
        unit: (
            newest[(unit, RS)].score if (unit, RS) in newest else None,
            newest[(unit, RKO)].score if (unit, RKO) in newest else None,
        )
        for unit in units
    }


def load_latest(
    countries: Sequence[str] | None, *, until: date
) -> dict[str, tuple[float | None, float | None]]:
    """Последние оценки пиццерий охвата на дату `until`; стран IMF в базе нет — пусто."""
    imf = tuple(row.code for row in read.countries() if row.is_imf)
    mine = imf if countries is None else tuple(code for code in countries if code in imf)
    if not mine:
        return {}
    months = month_window(until, LATEST_MONTHS)
    end = date(until.year + until.month // 12, until.month % 12 + 1, 1)
    facts = [
        Fact(*row)
        for row in read.score_facts(countries=mine, begin=months[0], end=end)
        if row[5] < end
    ]
    return latest_by_unit(facts)
