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
    #: Границы периода и статус публикации оценки — для строки «Периоды РКО и РС», когда
    #: периодов из Dodo IS нет (#1604); `None` — источник их не принёс.
    begin_on: date | None = None
    end_on: date | None = None
    status: str | None = None


_SCORES_SQL = (
    "select s.unit_dodo_id, u.name, u.country_code, p.rating_type, s.score, "
    "c.restaurant_reports + c.delivery_reports, s.checkups_count, "
    "p.begin_on, p.end_on, s.status "
    "from ratings.scores s join ratings.periods p on p.id = s.period_id "
    "join ratings.units u on u.dodo_id = s.unit_dodo_id "
    "left join ratings.collection c "
    "on c.unit_dodo_id = s.unit_dodo_id and c.period_id = s.period_id "
    "where u.country_code = any(%s) and case when p.rating_type = 'rko' "
    "then p.begin_on < %s and coalesce(p.end_on, p.begin_on + 6) >= %s "
    "else p.begin_on >= %s and p.begin_on < %s end "
    "order by s.unit_dodo_id, p.begin_on"
)


def next_month(month: date) -> date:
    """Первое число следующего месяца."""
    return date(month.year + (month.month == 12), month.month % 12 + 1, 1)


def period_scores(countries: Sequence[str], month: date) -> tuple[PeriodScore, ...]:
    """Оценки РКО (все недели, задевшие месяц, D735) и РС (начавшиеся в месяце) пиццерий стран."""
    if not countries:
        return ()
    after = next_month(month)
    rows = _rows(_SCORES_SQL, (list(countries), after, month, month, after))
    return tuple(
        PeriodScore(
            str(r[0]),
            str(r[1]),
            str(r[2]),
            str(r[3]),
            Decimal(r[4]),
            None if r[5] is None else int(r[5]),
            None if r[6] is None else int(r[6]),
            r[7],
            r[8],
            r[9],
        )
        for r in rows
    )


_AUDIT_SQL = """
select code, pct, inspection_id
from (
    select u.code, i.pct, i.id as inspection_id,
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


def _audit_rows(
    reach: Reach, countries: Sequence[str], month: date
) -> list[tuple[str, Decimal, str]]:
    охват = _require_reach(reach)
    if not countries:
        return []
    with _reading("проверки для «Качества»") as conn, conn.cursor() as cur:
        cur.execute(
            _AUDIT_SQL,
            {**охват.params(), "slice": list(countries), "begin": month, "end": next_month(month)},
        )
        return [(str(code), Decimal(pct), str(iid)) for code, pct, iid in cur.fetchall()]


def audit_inspections(reach: Reach, countries: Sequence[str], month: date) -> dict[str, str]:
    """Идентификатор той же последней проверки, чей процент в `audit_pcts`: ссылка из ячейки
    «Проверка» (#1603)."""
    return {code: iid for code, _, iid in _audit_rows(reach, countries, month)}


def audit_pcts(reach: Reach, countries: Sequence[str], month: date) -> dict[str, Decimal]:
    """Процент последней принятой проверки decimus в месяце, по коду пиццерии (32 hex).

    Исторические проверки (`origin = 'legacy'`, D332) не участвуют: их оценка перенесена
    из старого отчёта. Охват — вошедшего: партнёр читает проверки своего пространства."""
    return {code: pct for code, pct, _ in _audit_rows(reach, countries, month)}
