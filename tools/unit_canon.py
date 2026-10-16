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
- имени «Город-N» из написанного не вывести (район, адрес: «Bishkek — 7 Manas Ave»,
  «Gwarimpa») — номер берётся из открытого API Dodo IS (D517, #909):
  `publicapi.dodois.io/{страна}/api/v1/unitinfo/all`. Номер и UUID
  берутся из свода пиццерий `agg.units` (первый источник), API — для адреса и
  для точек, которых в своде нет. Точка ищется по `units.code`, иначе по
  алиасу и по адресу (правила и ступени —
  `src/domain/unit_match.py`). Найденная ровно одна: точка переименовывается в
  номер («Bishkek-8»), прежнее имя становится синонимом, `code` := UUID. Не
  найдена, найдено несколько, одну точку API нашли две записи или API страны не
  ответил — печатается списком с причиной и не трогается: номер угадывать
  нельзя, ошибка склеила бы историю двух пиццерий;

Закрытые точки Dodo IS (`State = 0`) тоже находятся: проверки у них есть.

Сухой прогон выполняет ВСЁ то же самое и откатывает транзакцию: так видны и
план, и отказы базы (права, ограничения) до того, как что-либо записано.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psycopg

from src.db.config import check_environment
from src.db.directory import DEFAULT_TENANT
from src.db.space import SYSTEM_SPACE, acting_space, apply_space
from src.db.units import normalize_unit_name
from src.domain.unit_match import (
    DodoUnit,
    Match,
    claimed_twice,
    match_unit,
    merge_registry,
    official_name,
    parse_dodo_units,
)
from src.domain.unit_name import canonical_unit
from tools.units import САЙТЫ

#: Открытый список точек страны в Dodo IS: без ключа, по коду страны строчными.
DODO_API = "https://publicapi.dodois.io/{cc}/api/v1/unitinfo/all"
API_ATTEMPTS = 3
API_TIMEOUT_SEC = 60

_UNITS_SQL = """
select u.id, u.name, u.country, u.city, u.code,
       (select count(*) from inspections i where i.unit_id = u.id)
from units u where u.tenant_code = %s order by u.name
"""

_REGISTRY_SQL = "select dodo_id, country_code, name, working from agg.units"

_RENAME_SQL = """
update units set name = %(name)s, name_normalized = %(key)s,
    country = coalesce(country, %(country)s), city = coalesce(city, %(city)s),
    code = coalesce(code, %(code)s)
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


@dataclass(frozen=True)
class Entry:
    """Строка отчёта: вид нужен итогу, текст — человеку."""

    kind: str
    text: str


RENAMED = "переименована"
RENAMED_API = "переименована по Dodo IS"
DUPLICATE = "дубль"
AMBIGUOUS = "неоднозначно"
NOT_FOUND = "не найдена"
NO_API = "нет API"

#: Что из отчёта — отказ, а не работа: его печатает итог отдельной строкой.
REFUSALS = (DUPLICATE, AMBIGUOUS, NOT_FOUND, NO_API)

FetchApi = Callable[[str], list[DodoUnit]]


def fetch_dodo_units(country: str) -> list[DodoUnit]:
    """Пиццерии страны из API Dodo IS; отказ после повторов — исключение, не пустой список."""
    cc = country.lower()
    last: Exception | None = None
    for _ in range(API_ATTEMPTS):
        try:
            request = Request(  # noqa: S310
                DODO_API.format(cc=cc), headers={"Accept": "application/json"}
            )
            with urlopen(request, timeout=API_TIMEOUT_SEC) as answer:  # noqa: S310
                payload = json.loads(answer.read())
            return parse_dodo_units(country, payload)
        except (URLError, OSError, ValueError) as exc:
            last = exc
    raise RuntimeError(f"API Dodo IS {cc}: {last}")


def _load_api(
    countries: set[str], fetch: FetchApi
) -> tuple[dict[str, list[DodoUnit]], dict[str, str]]:
    """Точки по странам и причины, по которым страна не загрузилась."""
    loaded: dict[str, list[DodoUnit]] = {}
    failed: dict[str, str] = {}
    for country in sorted(countries):
        if country not in САЙТЫ:
            failed[country] = "страны нет в словаре tools/units.py"
            continue
        try:
            loaded[country] = fetch(country)
        except RuntimeError as exc:
            failed[country] = str(exc)
    return loaded, failed


def _is_unit_number(unit: tuple[Any, ...]) -> bool:
    """Имя уже «Город-N» с известным городом: номер из API ему не нужен."""
    канон = canonical_unit(unit[1])
    return канон is not None and канон.city is not None


def _candidates(
    cur: psycopg.Cursor[Any], countries: set[str], fetch: FetchApi
) -> tuple[dict[str, list[DodoUnit]], dict[str, str]]:
    """Точки по странам: свод `agg.units` первым, API Dodo IS — адрес и недостающее."""
    api, не_загружены = _load_api(countries, fetch)
    cur.execute(_REGISTRY_SQL)
    свод: dict[str, list[tuple[str, str, str, bool]]] = {}
    for uuid, country, name, working in cur.fetchall():
        свод.setdefault(country, []).append((uuid, country, name, working))
    return (
        {c: merge_registry(свод.get(c, []), api.get(c, [])) for c in countries},
        не_загружены,
    )


def _refusal(name: str, проверок: int, причина: str) -> str:
    return f"  не тронута ({проверок} пров.): {name} — {причина}"


def plan_and_apply(
    cur: psycopg.Cursor[Any], tenant: str, fetch: FetchApi = fetch_dodo_units
) -> list[Entry]:
    """Привести справочник к канону в открытой транзакции; вернуть строки отчёта."""
    cur.execute(_UNITS_SQL, (tenant,))
    строки = cur.fetchall()
    по_ключу = {normalize_unit_name(r[1]): r for r in строки}
    по_коду = {r[4]: r for r in строки if r[4]}
    без_номера = [r for r in строки if not _is_unit_number(r)]
    кандидаты, не_загружены = _candidates(cur, {r[2] for r in без_номера if r[2]}, fetch)
    совпадения = claimed_twice(
        {r[0]: match_unit(r[1], r[4], кандидаты[r[2]]) for r in без_номера if r[2]}
    )
    отчёт: list[Entry] = []
    for unit_id, name, country, _city, _code, проверок in строки:
        канон = canonical_unit(name)
        if канон is not None and канон.city is not None:
            if канон.name == name:
                continue
            имя, город, uuid, страна, вид = канон.name, канон.city, None, канон.country, RENAMED
        elif unit_id in совпадения:
            найдено: Match = совпадения[unit_id]
            if найдено.unit is None:
                причина = найдено.reason
                if country in не_загружены and "не найдена" in причина:
                    отчёт.append(Entry(NO_API, _refusal(name, проверок, не_загружены[country])))
                    continue
                сомнительно = "неоднозначно" in причина or "две записи" in причина
                вид_отказа = AMBIGUOUS if сомнительно else NOT_FOUND
                отчёт.append(Entry(вид_отказа, _refusal(name, проверок, причина)))
                continue
            имя, город = official_name(найдено.unit)
            uuid, страна, вид = найдено.unit.uuid, найдено.unit.country, RENAMED_API
        else:
            отчёт.append(Entry(NOT_FOUND, _refusal(name, проверок, "страна записи не задана")))
            continue
        занята = по_ключу.get(normalize_unit_name(имя))
        if занята is not None and занята[0] != unit_id:
            # Удалять точки роли приложения нельзя, и так задумано. Бот ищет
            # каноническое имя, поэтому на дубль он больше не попадает; строку
            # убирает администратор (#440).
            текст = f"  дубль ({проверок} пров.), оставлен: {name} → уже есть {имя}"
            отчёт.append(Entry(DUPLICATE, текст))
            continue
        if uuid is not None and uuid in по_коду and по_коду[uuid][0] != unit_id:
            текст = f"  дубль ({проверок} пров.), оставлен: {name} → UUID уже у {по_коду[uuid][1]}"
            отчёт.append(Entry(DUPLICATE, текст))
            continue
        cur.execute(
            _RENAME_SQL,
            {
                "id": unit_id,
                "name": имя,
                "key": normalize_unit_name(имя),
                "country": страна,
                "city": город,
                "code": uuid,
            },
        )
        _alias(cur, tenant, unit_id, name)
        по_ключу[normalize_unit_name(имя)] = (unit_id, имя, None, None, uuid, проверок)
        if uuid is not None:
            по_коду[uuid] = по_ключу[normalize_unit_name(имя)]
        отчёт.append(Entry(вид, f"  переименована ({проверок} пров.): {name} → {имя}"))
    return отчёт


def summary(отчёт: list[Entry]) -> str:
    """Одна строка итога: сколько переименовано и сколько оставлено с причиной."""
    считано = Counter(e.kind for e in отчёт)
    переименовано = считано[RENAMED] + считано[RENAMED_API]
    отказы = ", ".join(f"{вид} {считано[вид]}" for вид in REFUSALS)
    по_dodo = считано[RENAMED_API]
    return f"изменений: {переименовано} (из них по Dodo IS {по_dodo}); не тронуто: {отказы}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="записать, а не откатить")
    parser.add_argument("--tenant", default=DEFAULT_TENANT)
    args = parser.parse_args(argv)
    with psycopg.connect(check_environment().dsn) as conn:
        apply_space(conn)
        with conn.cursor() as cur:
            отчёт = plan_and_apply(cur, args.tenant)
        if args.apply:
            conn.commit()
        else:
            conn.rollback()
    порядок = {RENAMED: 0, RENAMED_API: 1, DUPLICATE: 2, AMBIGUOUS: 3, NOT_FOUND: 4, NO_API: 5}
    print(
        "\n".join(e.text for e in sorted(отчёт, key=lambda e: порядок[e.kind]))
        or "  всё уже по канону"
    )
    режим = "записано" if args.apply else "сухой прогон, ничего не записано"
    print(f"{summary(отчёт)}; {режим}")
    return 1 if any(e.kind == NO_API for e in отчёт) else 0


if __name__ == "__main__":
    with acting_space(SYSTEM_SPACE):
        raise SystemExit(main())
