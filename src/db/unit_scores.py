"""Оценки последних проверок пиццерий — для плитки «Стабильно ниже порога» (D658).

Только чтение процента, который записал движок (`inspections.pct`): пересчёта нет
(CLAUDE.md, «Оценку не считать заново»). Берутся принятые проверки (`finalized`,
не снятые) и не исторические (`origin <> 'legacy'`, D332 — их оценка перенесена
из старого отчёта и в сравнении с нынешней методикой не участвует). Охват —
вошедшего: партнёр читает проверки своего пространства и своих стран (D283).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from .reach import Reach
from .reach import require_reach as _require_reach
from .reading import reading as _reading

_RECENT_SQL = """
select code, name, country, pct
from (
    select u.code, u.name, u.country, i.pct,
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
      and (%(until)s::date is null or i.inspection_date <= %(until)s::date)
) последние
where n <= %(n)s
order by code, n
"""


@dataclass(frozen=True)
class UnitPcts:
    """Последние проценты пиццерии (код Dodo), новые первыми."""

    code: str
    name: str
    country: str
    pcts: tuple[float, ...]


def recent_pcts(
    *, reach: Reach, countries: Sequence[str], until: date | None, n: int
) -> tuple[UnitPcts, ...]:
    """Последние `n` принятых проверок каждой пиццерии стран `countries` на `until` включительно."""
    охват = _require_reach(reach)
    out: dict[str, tuple[str, str, list[float]]] = {}
    with _reading("последние оценки проверок") as conn, conn.cursor() as cur:
        cur.execute(
            _RECENT_SQL,
            {**охват.params(), "slice": list(countries), "until": until, "n": n},
        )
        for code, name, country, pct in cur.fetchall():
            out.setdefault(str(code), (str(name), str(country or ""), []))[2].append(float(pct))
    return tuple(
        UnitPcts(code, name, country, tuple(p)) for code, (name, country, p) in out.items()
    )
