"""Справочник сведений о пиццериях (`unit_profiles`, миграция 0046): запись и чтение.

Запись — целиком одним заходом: свод — полный список, и пиццерия, которой в
новом своде нет, уходит из справочника. Почта партнёра — личные данные (D375):
читается только теми, кому экран её показывает, и в журнал не пишется.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from .config import check_environment
from .errors import RatingsError
from .pool import connection

_INSERT = """
insert into unit_profiles (country_code, name_normalized, name, dodo_id, stage, status, city,
    address, partner, partner_email, restaurant_on, delivery_on, revenue_on, closed_on,
    total_area, seats, extra)
values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""
_SELECT = """
select country_code, name_normalized, name, dodo_id, stage, status, city, address, partner,
    partner_email, restaurant_on, delivery_on, revenue_on, closed_on, total_area, seats, extra
from unit_profiles
"""
_BY_CODE = _SELECT + "where dodo_id = %s"
_BY_COUNTRY = _SELECT + "where country_code = %s order by name"


@dataclass(frozen=True)
class Profile:
    """Сведения о пиццерии из свода. `stage`: open / paused / pipeline / closed."""

    country_code: str
    name: str
    stage: str
    status: str
    city: str | None = None
    address: str | None = None
    partner: str | None = None
    partner_email: str | None = None
    restaurant_on: date | None = None
    delivery_on: date | None = None
    revenue_on: date | None = None
    closed_on: date | None = None
    total_area: Decimal | None = None
    seats: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    dodo_id: str | None = None
    name_normalized: str = ""


def save(profiles: Sequence[Profile]) -> int:
    """Заменить справочник целиком. Повтор кода у двух строк — код у второй снимается."""
    seen: set[str] = set()
    rows = []
    for p in profiles:
        code = p.dodo_id if p.dodo_id and p.dodo_id not in seen else None
        if code:
            seen.add(code)
        rows.append(
            (p.country_code, p.name_normalized, p.name, code, p.stage, p.status, p.city, p.address,
             p.partner, p.partner_email, p.restaurant_on, p.delivery_on, p.revenue_on, p.closed_on,
             p.total_area, p.seats, Jsonb(p.extra))
        )  # fmt: skip
    try:
        with connection(check_environment().dsn) as conn, conn.transaction():
            conn.execute("delete from unit_profiles")
            with conn.cursor() as cur:
                cur.executemany(_INSERT, rows)
    except psycopg.Error as exc:
        raise RatingsError(f"Свод не лёг в справочник ({exc.__class__.__name__})") from exc
    return len(rows)


def hq_units() -> tuple[tuple[str, str | None, tuple[str, ...], str | None], ...]:
    """Точки справочника HQ: (id, страна, имя и синонимы, код)."""
    sql = """
        select u.id::text, u.country,
               array_agg(a.alias) filter (where a.alias is not null) || u.name, u.code
        from units u left join unit_aliases a on a.unit_id = u.id
        where u.tenant_code = 'HQ' group by u.id
    """
    try:
        with connection(check_environment().dsn) as conn:
            rows = conn.execute(sql).fetchall()
    except psycopg.Error as exc:
        raise RatingsError(f"Точки справочника не прочитались ({exc.__class__.__name__})") from exc
    return tuple((str(r[0]), r[1], tuple(r[2] or ()), r[3]) for r in rows)


def set_unit_codes(codes: Sequence[tuple[str, str]]) -> int:
    """Проставить точкам HQ код Dodo: (id точки, код). Код, уже занятый другой
    точкой, не переносится — это повод разобраться руками, а не молча перевесить."""
    try:
        with connection(check_environment().dsn) as conn, conn.transaction():
            done = 0
            for unit_id, code in codes:
                cur = conn.execute(
                    "update units set code = %s where tenant_code = 'HQ' and id = %s "
                    "and code is distinct from %s and not exists "
                    "(select 1 from units o where o.tenant_code = 'HQ' and o.code = %s)",
                    (code, unit_id, code, code),
                )
                done += cur.rowcount
    except psycopg.Error as exc:
        raise RatingsError(f"Коды точек не легли ({exc.__class__.__name__})") from exc
    return done


def _read(sql: str, params: tuple[Any, ...]) -> tuple[Profile, ...]:
    try:
        with connection(check_environment().dsn) as conn:
            rows = conn.execute(sql, params).fetchall()
    except psycopg.Error as exc:
        raise RatingsError(
            f"Сведения о пиццериях не прочитались ({exc.__class__.__name__})"
        ) from exc
    return tuple(
        Profile(
            country_code=r[0], name_normalized=r[1], name=r[2], dodo_id=r[3], stage=r[4],
            status=r[5], city=r[6], address=r[7], partner=r[8], partner_email=r[9],
            restaurant_on=r[10],
            delivery_on=r[11], revenue_on=r[12], closed_on=r[13], total_area=r[14], seats=r[15],
            extra=dict(r[16] or {}),
        )
        for r in rows
    )  # fmt: skip


def by_code(dodo_id: str) -> Profile | None:
    found = _read(_BY_CODE, (dodo_id,))
    return found[0] if found else None


def by_country(country_code: str) -> tuple[Profile, ...]:
    return _read(_BY_COUNTRY, (country_code,))


_UPSERT = """
insert into unit_profiles (country_code, name_normalized, name, dodo_id, stage, status, city,
    address, partner, partner_email, restaurant_on, delivery_on, revenue_on, closed_on,
    total_area, seats, extra)
values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
on conflict (country_code, name_normalized) do update set
    name = excluded.name,
    dodo_id = coalesce(excluded.dodo_id, unit_profiles.dodo_id),
    stage = excluded.stage,
    status = excluded.status,
    city = coalesce(excluded.city, unit_profiles.city),
    address = coalesce(excluded.address, unit_profiles.address),
    partner = coalesce(excluded.partner, unit_profiles.partner),
    restaurant_on = coalesce(excluded.restaurant_on, unit_profiles.restaurant_on),
    delivery_on = coalesce(excluded.delivery_on, unit_profiles.delivery_on),
    loaded_at = now()
"""


def upsert(profile: Profile) -> None:
    """Добавить или дополнить ОДНУ строку справочника, остальные не трогая (D536).

    `save` заменяет справочник целиком из свода; эта дверь — для пиццерии, которую
    завели с экрана «Страны»: адрес и партнёр, названные при заведении, ложатся
    рядом со сводом. Пустое поле новой записи прежнее значение не стирает. Код
    Dodo, уже занятый другой строкой, — отказ, а не молчаливый перенос.
    """
    row = (
        profile.country_code, profile.name_normalized, profile.name, profile.dodo_id or None,
        profile.stage, profile.status, profile.city, profile.address, profile.partner,
        profile.partner_email, profile.restaurant_on, profile.delivery_on, profile.revenue_on,
        profile.closed_on, profile.total_area, profile.seats, Jsonb(profile.extra),
    )  # fmt: skip
    try:
        with connection(check_environment().dsn) as conn, conn.transaction():
            conn.execute(_UPSERT, row)
    except psycopg.Error as exc:
        raise RatingsError(
            f"Сведения о пиццерии не легли в справочник ({exc.__class__.__name__})"
        ) from exc
