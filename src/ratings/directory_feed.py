"""Справочник пиццерий из рейтингов РС и РКО (D556, #981).

Рейтинги считает Dodo IS по каждой работающей пиццерии, поэтому их список
точек — учётный источник живых пиццерий. Витрина сайтов стран (`tools/units.py
sites`) им не была: четыре сайта (BY, HR, KG, TJ) не отдают городов вовсе, и у
Таджикистана на «Странах» стояло 2 точки из 9.

Точка заводится под латинским именем из свода пиццерий (`unit_profiles`, D538),
если код там есть; нет — под именем из рейтингов, оно и так латиницей. Ничего не
удаляется: точка, выпавшая из рейтингов, могла не получить оценку за один
период, а с ней в справочнике живёт история её проверок.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta

from src.db.directory import resolve_unit, upsert_unit
from src.db.errors import RatingsError
from src.db.ratings import live_units
from src.db.unit_profiles import by_country, set_unit_codes
from src.domain.tenants import HQ_TENANT
from src.domain.unit_match import Ref

#: Окно «живой» точки: оценка РС (полмесяца) или РКО (неделя) за последние 90 дней.
LIVE_WINDOW_DAYS = 90


@dataclass(frozen=True)
class FeedReport:
    """Итог прогона: сколько точек в рейтингах, сколько заведено, что пропущено и почему."""

    seen: int
    put: int
    skipped: tuple[str, ...]


def put_unit(
    name: str,
    *,
    code: str,
    aliases: tuple[str, ...],
    country: str,
    city: str | None,
    tenant: str,
) -> str | None:
    """Завести или обновить точку под `name` с кодом Dodo `code`. Отказ — причина строкой.

    Имя, уже занятое точкой с ДРУГИМ кодом, не перевешивается: это два разных
    места с одним названием, и решать, какое чьё, должен человек.
    """
    known = resolve_unit(name, tenant=tenant)
    if known is not None and known.code not in (None, code):
        return f"{country} {name}: имя занято точкой с другим кодом"
    if known is None:
        upsert_unit(name, code=code, aliases=aliases, country=country, city=city, tenant=tenant)
        return None
    if known.code is None:
        set_unit_codes([(known.id, code)])
    upsert_unit(known.name, aliases=aliases, country=country, city=city, tenant=tenant)
    return None


def _refs(country: str) -> dict[str, Ref]:
    try:
        profiles = by_country(country)
    except RatingsError:
        return {}
    return {
        p.dodo_id: Ref(p.country_code, p.name, p.dodo_id, p.city, p.address)
        for p in profiles
        if p.dodo_id
    }


def sync(
    *,
    today: date | None = None,
    countries: Iterable[str] = (),
    tenant: str = HQ_TENANT,
    dry_run: bool = False,
) -> FeedReport:
    """Завести в справочник все живые точки рейтингов (или только `countries`)."""
    since = (today or date.today()) - timedelta(days=LIVE_WINDOW_DAYS)
    only = {c.upper() for c in countries}
    units = [u for u in live_units(since) if not only or u[2] in only]
    refs: dict[str, dict[str, Ref]] = {}
    put = 0
    skipped: list[str] = []
    for code, rating_name, country in units:
        ref = refs.setdefault(country, _refs(country)).get(code)
        name = ref.clean_name if ref else rating_name.strip()
        aliases = tuple(a for a in (rating_name.strip(),) if a and a != name)
        if dry_run:
            put += 1
            continue
        problem = put_unit(
            name,
            code=code,
            aliases=aliases,
            country=country,
            city=ref.city if ref else None,
            tenant=tenant,
        )
        if problem:
            skipped.append(problem)
        else:
            put += 1
    return FeedReport(seen=len(units), put=put, skipped=tuple(skipped))
