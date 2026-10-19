"""Расход модели (D537): из сумм базы — то, что рисует экран «Расход модели».

Чистый слой без Flask и базы: на входе строки `model_usage_read` (суммы по срезам и
моделям), на выходе итоги, срезы и оценка стоимости. Деньги считаются ЗДЕСЬ по
`recognize/model_prices.json`, а не в базе: поправка цены пересчитывает и прошлое.

**Стоимость — оценка, и «неизвестно» не равно «ноль».** Модель без цены в файле в
сумму не входит, а итог помечается неполным (`cost_partial`); если цены нет ни у одной
модели с расходом, стоимость — `None`, и экран показывает только токены.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from src.db.model_usage import DIM_DAY, DIM_INSPECTION, DIM_KIND, DIM_PERSON, UsageRow
from src.recognize.pricing import Price, estimate_cost

#: Предел столбиков по дням: «всё время» не должно рисовать годы по одному дню.
MAX_DAYS = 366
_TG_PREFIX = "tg:"


@dataclass(frozen=True)
class Sum:
    """Сумма расхода по любому срезу."""

    calls: int = 0
    failed: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    audio_seconds: float = 0.0
    #: Оценка в долларах по моделям с ценой; `None` — не нашлось ни одной цены.
    cost: float | None = None
    #: Часть расхода — по моделям без цены: сумма неполная.
    cost_partial: bool = False

    @property
    def tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def _sum(rows: list[UsageRow], prices: dict[str, Price] | None) -> Sum:
    cost: float | None = None
    partial = False
    for r in rows:
        if not (r.input_tokens or r.output_tokens or r.audio_seconds):
            continue
        one = estimate_cost(
            r.model,
            input_tokens=r.input_tokens,
            output_tokens=r.output_tokens,
            audio_seconds=r.audio_seconds,
            prices=prices,
        )
        if one is None:
            partial = True
        else:
            cost = (cost or 0.0) + one
    return Sum(
        calls=sum(r.calls for r in rows),
        failed=sum(r.failed for r in rows),
        input_tokens=sum(r.input_tokens for r in rows),
        output_tokens=sum(r.output_tokens for r in rows),
        audio_seconds=sum(r.audio_seconds for r in rows),
        cost=cost,
        cost_partial=partial and cost is not None,
    )


def totals(rows: tuple[UsageRow, ...], *, prices: dict[str, Price] | None = None) -> Sum:
    """Итог периода: каждый вызов лежит ровно в одном дне, поэтому берётся срез `day`."""
    return _sum([r for r in rows if r.dim == DIM_DAY], prices)


def change(now: float | None, before: float | None) -> float | None:
    """Изменение к прошлому периоду, доли (0,25 — на четверть больше). Нет базы — `None`."""
    if now is None or before is None or before <= 0:
        return None
    return (now - before) / before


@dataclass(frozen=True)
class Delta:
    """Изменение трёх показателей к прошлому периоду."""

    calls: float | None
    tokens: float | None
    cost: float | None


def delta(now: Sum, before: Sum | None) -> Delta:
    if before is None:
        return Delta(None, None, None)
    return Delta(
        change(now.calls, before.calls),
        change(now.tokens, before.tokens),
        change(now.cost, before.cost),
    )


@dataclass(frozen=True)
class Line:
    """Строка списка: ключ среза, подпись и сумма. `share` — доля токенов среза от максимума."""

    key: str
    label: str
    sum: Sum
    share: float = 0.0


def _grouped(rows: tuple[UsageRow, ...], dim: str, prices: dict[str, Price] | None) -> list[Line]:
    by_key: dict[str, list[UsageRow]] = defaultdict(list)
    labels: dict[str, str] = {}
    for r in rows:
        if r.dim != dim:
            continue
        by_key[r.key].append(r)
        labels.setdefault(r.key, r.label)
    lines = [Line(k, labels[k], _sum(v, prices)) for k, v in by_key.items()]
    lines.sort(key=lambda x: (-x.sum.tokens, -x.sum.calls, x.key))
    top = max((x.sum.tokens for x in lines), default=0)
    return [Line(x.key, x.label, x.sum, x.sum.tokens / top if top else 0.0) for x in lines]


def by_kind(rows: tuple[UsageRow, ...], *, prices: dict[str, Price] | None = None) -> list[Line]:
    return _grouped(rows, DIM_KIND, prices)


def by_inspection(
    rows: tuple[UsageRow, ...], *, prices: dict[str, Price] | None = None
) -> list[Line]:
    return _grouped(rows, DIM_INSPECTION, prices)


def by_person(rows: tuple[UsageRow, ...], *, prices: dict[str, Price] | None = None) -> list[Line]:
    """Люди: подпись — логин; без учётки — «Telegram <id>» (ключ `tg:<id>`), иначе пусто."""
    out = []
    for line in _grouped(rows, DIM_PERSON, prices):
        label = line.label or (
            f"Telegram {line.key.removeprefix(_TG_PREFIX)}"
            if line.key.startswith(_TG_PREFIX)
            else ""
        )
        out.append(Line(line.key, label, line.sum, line.share))
    return out


@dataclass(frozen=True)
class DayBar:
    """Столбик дня: токены и высота в долях максимума."""

    day: str
    sum: Sum
    height: float = 0.0
    #: Для подписи под столбиком: число месяца.
    number: int = field(default=0)


def by_day(
    rows: tuple[UsageRow, ...],
    *,
    start: date | None,
    end: date | None,
    prices: dict[str, Price] | None = None,
) -> list[DayBar]:
    """Дни периода по порядку; у ограниченного периода — и дни без вызовов (пустой столбик)."""
    got = {line.key: line.sum for line in _grouped(rows, DIM_DAY, prices)}
    if start is not None and end is not None and (end - start).days < MAX_DAYS:
        days = [(start + timedelta(days=n)).isoformat() for n in range((end - start).days + 1)]
    else:
        days = sorted(got)[-MAX_DAYS:]
    top = max((got[d].tokens for d in days if d in got), default=0)
    return [
        DayBar(
            d,
            got.get(d, Sum()),
            got[d].tokens / top if d in got and top else 0.0,
            date.fromisoformat(d).day,
        )
        for d in days
    ]


def money(value: float | None) -> str:
    """Сумма в долларах для экрана; `None` — прочерк. Малые суммы — с точностью до сотых цента."""
    if value is None:
        return "—"
    return f"${value:,.2f}" if value >= 1 else f"${value:.4f}"


def number(value: int | float) -> str:
    """Число с пробелом между тысячами."""
    return f"{round(value):,}".replace(",", " ")


def percent(value: float | None) -> str:
    """Изменение в процентах со знаком; нет базы сравнения — прочерк."""
    if value is None:
        return "—"
    return f"{value * 100:+.0f}%"
