"""Справочник пиццерий к каноническим именам «Город-N» по-английски (D233, #440).

    make units-canon                 # сухой прогон: всё в транзакции и откат
    make units-canon ARGS="--apply"  # то же, с записью

Что делает с каждой точкой арендатора:

- имя уже каноническое — ничего;
- канон свободен — точка ПЕРЕИМЕНОВЫВАЕТСЯ (id тот же, поэтому история
  проверок остаётся при ней), старое имя становится синонимом, страна и город
  дописываются из словаря, если их не было;
- канон занят другой точкой — дубль печатается и не трогается: удалять точки
  роли приложения нельзя, а бот ищет каноническое имя и на дубль больше не
  попадает; строку убирает администратор (#440);
- имени «Город-N» из написанного не вывести (район, адрес) — печатается и не
  трогается: номер точки в наших данных не содержится, выдумывать его нельзя.

Сухой прогон выполняет ВСЁ то же самое и откатывает транзакцию: так видны и
план, и отказы базы (права, ограничения) до того, как что-либо записано.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psycopg

from src.db.config import check_environment
from src.db.directory import DEFAULT_TENANT
from src.db.units import normalize_unit_name
from src.domain.unit_name import canonical_unit

_UNITS_SQL = """
select u.id, u.name, u.country, u.city,
       (select count(*) from inspections i where i.unit_id = u.id)
from units u where u.tenant_code = %s order by u.name
"""

_RENAME_SQL = """
update units set name = %(name)s, name_normalized = %(key)s,
    country = coalesce(country, %(country)s), city = coalesce(city, %(city)s)
where id = %(id)s
"""

_ALIAS_SQL = """
insert into unit_aliases (tenant_code, alias_normalized, unit_id, alias)
values (%s, %s, %s, %s)
on conflict (tenant_code, alias_normalized) do update
    set unit_id = excluded.unit_id, alias = excluded.alias
"""


def _alias(cur: psycopg.Cursor[Any], tenant: str, unit_id: Any, alias: str) -> None:
    cur.execute(_ALIAS_SQL, (tenant, normalize_unit_name(alias), unit_id, alias))


def plan_and_apply(cur: psycopg.Cursor[Any], tenant: str) -> list[str]:
    """Привести справочник к канону в открытой транзакции; вернуть строки отчёта."""
    cur.execute(_UNITS_SQL, (tenant,))
    строки = cur.fetchall()
    по_ключу = {normalize_unit_name(r[1]): r for r in строки}
    отчёт: list[str] = []
    for unit_id, name, _country, _city, проверок in строки:
        канон = canonical_unit(name)
        if канон is None:
            отчёт.append(f"  без номера, не тронута: {name}")
            continue
        if канон.name == name:
            continue
        занята = по_ключу.get(normalize_unit_name(канон.name))
        if занята is not None and занята[0] != unit_id:
            # Удалять точки роли приложения нельзя, и так задумано. Бот ищет
            # каноническое имя, поэтому на дубль он больше не попадает; строку
            # убирает администратор (#440).
            отчёт.append(f"  дубль ({проверок} пров.), оставлен: {name} → уже есть {канон.name}")
            continue
        cur.execute(
            _RENAME_SQL,
            {
                "id": unit_id,
                "name": канон.name,
                "key": normalize_unit_name(канон.name),
                "country": канон.country,
                "city": канон.city,
            },
        )
        _alias(cur, tenant, unit_id, name)
        по_ключу[normalize_unit_name(канон.name)] = (unit_id, канон.name, None, None, проверок)
        отчёт.append(f"  переименована ({проверок} пров.): {name} → {канон.name}")
    return отчёт


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="записать, а не откатить")
    parser.add_argument("--tenant", default=DEFAULT_TENANT)
    args = parser.parse_args(argv)
    with psycopg.connect(check_environment().dsn) as conn:
        with conn.cursor() as cur:
            отчёт = plan_and_apply(cur, args.tenant)
        if args.apply:
            conn.commit()
        else:
            conn.rollback()
    print("\n".join(отчёт) or "  всё уже по канону")
    изменено = sum(1 for s in отчёт if "переименована" in s)
    режим = "записано" if args.apply else "сухой прогон, ничего не записано"
    print(f"изменений: {изменено}; {режим}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
