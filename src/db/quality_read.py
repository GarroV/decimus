"""Чтения для экрана «Качество» (docs/21-quality.md): РКО, РС и проверки по месяцам.

Только чтение. Баллы РКО и РС — из `ratings.scores`, проверки — процент, который записал
движок (`inspections.pct`): пересчёта нет (CLAUDE.md, «Оценку не считать заново»).
Месяц периода рейтинга — по дате его начала (неделя РКО и полумесяц РС ложатся в месяц, в
котором начались). Карты, агрегаторы и Dodo IS читают свои модули (`maps_store`,
`agg_store`, `dodois_metrics`): здесь только то, чего больше нигде нет.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .ratings_read import _rows
from .reach import Reach
from .reach import require_reach as _require_reach
from .reading import reading as _reading


@dataclass(frozen=True)
class PeriodScore:
    """Оценка пиццерии за один период рейтинга внутри месяца."""

    unit: str
    name: str
    country: str
    rating_type: str
    score: Decimal
    #: Проверок РКО за неделю по собираемости (отчёты зала и доставки); `None` — листа нет.
    collected: int | None
    #: Число проверок, которое принёс сам рейтинг (`checkups_count`); `None` — не принёс.
    checkups: int | None


_SCORES_SQL = (
    "select s.unit_dodo_id, u.name, u.country_code, p.rating_type, s.score, "
    "c.restaurant_reports + c.delivery_reports, s.checkups_count "
    "from ratings.scores s join ratings.periods p on p.id = s.period_id "
    "join ratings.units u on u.dodo_id = s.unit_dodo_id "
    "left join ratings.collection c "
    "on c.unit_dodo_id = s.unit_dodo_id and c.period_id = s.period_id "
    "where u.country_code = any(%s) and p.begin_on >= %s and p.begin_on < %s "
    "order by s.unit_dodo_id, p.begin_on"
)


def next_month(month: date) -> date:
    """Первое число следующего месяца."""
    return date(month.year + (month.month == 12), month.month % 12 + 1, 1)


def period_scores(countries: Sequence[str], month: date) -> tuple[PeriodScore, ...]:
    """Оценки РКО (недели) и РС (полумесяцы) пиццерий стран, начавшихся в месяце `month`."""
    if not countries:
        return ()
    rows = _rows(_SCORES_SQL, (list(countries), month, next_month(month)))
    return tuple(
        PeriodScore(
            str(r[0]),
            str(r[1]),
            str(r[2]),
            str(r[3]),
            Decimal(r[4]),
            None if r[5] is None else int(r[5]),
            None if r[6] is None else int(r[6]),
        )
        for r in rows
    )


_AUDIT_SQL = """
select code, pct
from (
    select u.code, i.pct,
           row_number() over (
               partition by u.id order by i.inspection_date desc, i.pushed_at desc
           ) as n
    from inspections i
    join units u on u.id = i.unit_id
    where i.status = 'finalized' and i.retracted_at is null and i.origin <> 'legacy'
      and u.code is not null and u.merged_into is null
      and (%(tenants)s::text[] is null or i.tenant_code = any(%(tenants)s))
      and (%(countries)s::text[] is null or u.country = any(%(countries)s))
      and u.country = any(%(slice)s)
      and i.inspection_date >= %(begin)s::date and i.inspection_date < %(end)s::date
) последние
where n = 1
"""


def audit_pcts(reach: Reach, countries: Sequence[str], month: date) -> dict[str, Decimal]:
    """Процент последней принятой проверки decimus в месяце, по коду пиццерии (32 hex).

    Исторические проверки (`origin = 'legacy'`, D332) не участвуют: их оценка перенесена
    из старого отчёта. Охват — вошедшего: партнёр читает проверки своего пространства."""
    охват = _require_reach(reach)
    if not countries:
        return {}
    with _reading("проверки для «Качества»") as conn, conn.cursor() as cur:
        cur.execute(
            _AUDIT_SQL,
            {**охват.params(), "slice": list(countries), "begin": month, "end": next_month(month)},
        )
        return {str(code): Decimal(pct) for code, pct in cur.fetchall()}
