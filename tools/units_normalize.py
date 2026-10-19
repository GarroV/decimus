"""Привести справочник пиццерий `units` к эталону `unit_profiles` (#316, #909).

    make units-normalize                                  # сухой прогон по базе: только чтение
    make units-normalize ARGS="--from-dir выгрузка/"      # сухой прогон по выгрузке CSV, без базы
    make units-normalize ARGS="--apply --backup копия.json"   # записать одной транзакцией
    make units-normalize ARGS="--retire"                  # + снять дубли с историей
    make units-normalize ARGS="--map site_map.csv"        # ручная карта «имя с сайта → имя эталона»

Эталон — `unit_profiles`: у каждой пиццерии там имя с номером («Bishkek-8»), адрес и
код Dodo. Точки `units` заведены с сайтов стран («Bishkek — 7 Manas Ave»), руками на
кириллице («Тбилиси-1») или по факту проверки; здесь они связываются с эталоном
(правила и доверие — `src/domain/unit_match.py`) и получают его имя, код и город.

Что делает с точкой:

- переименовывает в имя эталона, дописывает код `dodo_id` и город; старое имя остаётся
  синонимом, поэтому бот и поиск находят точку по-старому, а история — при ней;
- сливает ПУСТОЙ дубль (две точки на одну строку эталона): синонимы и имя дубля
  переходят оставляемой точке, дубль удаляется. Дубль, на который ссылаются проверки,
  история переносов, предписания, поездки или рейтинги, НЕ сливается: удаление стёрло
  бы или переписало историю. Он печатается как «заблокирован» — решает человек;
- СНИМАЕТ дубль, на который ссылается только история переносов (`--retire`, D538):
  проверок у него нет — они переехали на точку эталона, — но `inspection_moves` (только на
  добавление) его держит, и удалить нельзя. Строка остаётся с `units.merged_into`: в списках
  её нет, имя становится синонимом точки эталона, поиск по имени и id ведёт на неё;
- несопоставленное и неоднозначное (несколько кандидатов) не трогает, а печатает.

Сухой прогон ничего не пишет. `--apply` — одна транзакция: сначала снимок строк до
правки в JSON (`--backup`), потом правки; повторный запуск ничего не меняет. Слияние
удаляет строки `units`, а роли приложения это не выдано: запись идёт под
`DATABASE_ADMIN_URL`, если он задан.

`--map` — ручное сопоставление имён с сайтов стран (CSV: country, old_name, target_name,
dodo_id, basis). По каждой строке: точки с именем target_name нет — old_name переименовывается
в target_name, получает код dodo_id, старое имя остаётся синонимом; точка с таким именем
есть — old_name вливается в неё (пустой дубль удаляется, дубль с историей переносов снимается).
Строка отклоняется, если у old_name есть проверки или другие ссылки, если у точки target_name
или в эталоне под этим именем другой код Dodo, или если код dodo_id уже держит другая точка.
Строка, уже выполненная (old_name нет, target_name с этим кодом есть), молча пропускается.

Выгрузка для `--from-dir` — CSV с заголовком, из psql `\\copy (…) to stdout csv header`:
`units.csv` (id, name, code, country, city), `aliases.csv` (unit_id, alias),
`profiles.csv` (country_code, name, dodo_id, city, address), `usage.csv`
(unit_id, inspections, moves, other).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psycopg

from src.db.config import check_environment
from src.db.migrate import admin_dsn
from src.db.space import SYSTEM_SPACE, acting_space, apply_space
from src.db.units import normalize_unit_name
from src.domain.unit_match import (
    HIGH,
    MEDIUM,
    Action,
    Match,
    Ref,
    RefIndex,
    UnitRow,
    Usage,
    plan,
)
from src.domain.unit_name import fold_unit_name

TENANT = "HQ"

_UNITS_SQL = (
    "select id::text, name, code, country, city from units "
    "where tenant_code = %s and merged_into is null order by name"
)
_ALIASES_SQL = "select unit_id::text, alias from unit_aliases where tenant_code = %s"
_REFS_SQL = "select country_code, name, dodo_id, city, address from unit_profiles"
_USAGE_SQL = """
select unit_id::text, sum(i), sum(m), sum(o) from (
    select unit_id, count(*) i, 0 m, 0 o from inspections group by 1
    union all select old_unit_id, 0, count(*), 0 from inspection_moves group by 1
    union all select new_unit_id, 0, count(*), 0 from inspection_moves group by 1
    union all select unit_id, 0, 0, count(*) from prescription_units group by 1
    union all select unit_id, 0, 0, count(*) from trip_steps where unit_id is not null group by 1
    union all select decimus_unit_id, 0, 0, count(*) from ratings.units
        where decimus_unit_id is not null group by 1
) x group by 1
"""
_USAGE_ONE_SQL = _USAGE_SQL.replace(") x group by 1", ") x where unit_id = %s::uuid group by 1")

_INSPECTIONS_ONE_SQL = "select count(*) from inspections where unit_id = %s::uuid"

_ALIAS_SQL = """
insert into unit_aliases (tenant_code, alias_normalized, unit_id, alias)
values (%s, %s, %s::uuid, %s)
on conflict (tenant_code, alias_normalized) do update
    set unit_id = excluded.unit_id, alias = excluded.alias
"""
_UPDATE_SQL = """
update units set name = coalesce(%(name)s, name),
    name_normalized = coalesce(%(key)s, name_normalized),
    code = coalesce(code, %(code)s), city = coalesce(city, %(city)s)
where id = %(id)s::uuid
"""


def _rows(cur: psycopg.Cursor[Any], sql: str, *params: Any) -> list[tuple[Any, ...]]:
    cur.execute(sql, params)
    return cur.fetchall()


def _assemble(
    units: list[tuple[Any, ...]],
    aliases: list[tuple[Any, ...]],
    refs: list[tuple[Any, ...]],
    usage: list[tuple[Any, ...]],
) -> tuple[list[UnitRow], RefIndex]:
    by_unit: dict[str, list[str]] = defaultdict(list)
    for unit_id, alias in aliases:
        by_unit[str(unit_id)].append(alias)
    used = {str(r[0]): Usage(int(r[1] or 0), int(r[2] or 0), int(r[3] or 0)) for r in usage}
    rows = [
        UnitRow(
            id=str(u[0]),
            name=u[1],
            code=u[2] or None,
            country=u[3] or None,
            city=u[4] or None,
            aliases=tuple(sorted(by_unit[str(u[0])])),
            usage=used.get(str(u[0]), Usage()),
        )
        for u in units
    ]
    index = RefIndex([Ref(r[0], r[1], r[2] or None, r[3] or None, r[4] or None) for r in refs])
    return rows, index


def load_db(cur: psycopg.Cursor[Any]) -> tuple[list[UnitRow], RefIndex]:
    return _assemble(
        _rows(cur, _UNITS_SQL, TENANT),
        _rows(cur, _ALIASES_SQL, TENANT),
        _rows(cur, _REFS_SQL),
        _rows(cur, _USAGE_SQL),
    )


def load_dir(folder: Path) -> tuple[list[UnitRow], RefIndex]:
    def read(name: str) -> list[dict[str, str]]:
        with (folder / name).open(encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))

    return _assemble(
        [(r["id"], r["name"], r["code"], r["country"], r["city"]) for r in read("units.csv")],
        [(r["unit_id"], r["alias"]) for r in read("aliases.csv")],
        [
            (r["country_code"], r["name"], r["dodo_id"], r["city"], r["address"])
            for r in read("profiles.csv")
        ],
        [(r["unit_id"], r["inspections"], r["moves"], r["other"]) for r in read("usage.csv")],
    )


# --- отчёт -----------------------------------------------------------------------------------

_TITLES = {
    "rename": "ПЕРЕИМЕНОВАТЬ в имя эталона (старое имя — синонимом)",
    "fill": "ДОПИСАТЬ код, город, страну (имя уже верное)",
    "merge": "СЛИТЬ пустой дубль в точку эталона",
    "retire": "СНЯТЬ дубль с историей переносов (строка остаётся, ведёт на точку эталона)",
    "refused": "ОТКАЗ по строке карты — не тронута",
    "blocked": "ДУБЛЬ ЗАБЛОКИРОВАН — на него есть ссылки, нужно решение человека "
    "(--retire снимает те, что держит только история переносов)",
    "conflict": "КОНФЛИКТ — имя эталона занято другой точкой, не тронута",
    "ambiguous": "НЕОДНОЗНАЧНО — несколько кандидатов, не тронута",
    "unmatched": "НЕ НАЙДЕНО в эталоне, не тронута",
    "skipped": "НИЖЕ ПОРОГА доверия, не тронута",
}


def _line(a: Action, index: RefIndex) -> str:
    m = a.match
    where = f"{a.unit.country or '—'}"
    if a.kind in ("ambiguous",):
        cand = "; ".join(f"{r.name} ({r.address or 'без адреса'})" for r in m.refs)
        return f"  {a.unit.name} [{where}] -> {m.rule}: {cand}"
    if a.kind == "unmatched":
        return f"  {a.unit.name} [{where}] -- {a.note}"
    ref = m.refs[0].clean_name if m.refs else (a.new_name or "—")
    extra = []
    if a.new_code:
        extra.append("+код")
    if a.new_city:
        extra.append(f"город {a.new_city}")
    if a.new_country:
        extra.append(f"страна {a.new_country}")
    if a.target is not None:
        extra.append(f"в {a.target.name}")
    if a.note:
        extra.append(a.note)
    evidence = f"{m.rule}/{m.confidence}: {m.detail}"
    if m.rule in ("address", "city") and m.refs:
        evidence += f"; адрес эталона: {m.refs[0].address or '—'}"
    tail = f" [{', '.join(extra)}]" if extra else ""
    return f"  {a.unit.name} [{where}] -> {ref}{tail}  ({evidence})"


def render(actions: list[Action], index: RefIndex) -> str:
    count = Counter(a.kind for a in actions)
    out = [f"Точек в справочнике {TENANT}: {len(actions)}; строк в эталоне: {len(index.refs)}", ""]
    out.append("Итого: " + ", ".join(f"{k} {count[k]}" for k in ("keep", *_TITLES) if count[k]))
    for kind, title in _TITLES.items():
        items = [a for a in actions if a.kind == kind]
        if not items:
            continue
        out += ["", f"== {title}: {len(items)}"]
        out += [_line(a, index) for a in items]
    touched = [a for a in actions if a.writes and a.unit.usage.inspections]
    out += ["", f"Затрагиваются точки с проверками: {len(touched)}"]
    out += [f"  {a.unit.name}: {a.unit.usage.inspections} пров." for a in touched]
    return "\n".join(out)


# --- запись ----------------------------------------------------------------------------------


def _snapshot(cur: psycopg.Cursor[Any], actions: list[Action]) -> dict[str, Any]:
    ids = sorted({x.id for a in actions if a.writes for x in (a.unit, a.target) if x is not None})
    units = _rows(
        cur,
        "select id::text, tenant_code, name, name_normalized, code, country, city, "
        "created_at::text, merged_into::text from units where id = any(%s::uuid[]) order by name",
        ids,
    )
    aliases = _rows(
        cur,
        "select tenant_code, alias_normalized, unit_id::text, alias from unit_aliases "
        "where unit_id = any(%s::uuid[]) order by alias_normalized",
        ids,
    )
    return {
        "made_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "units": [
            dict(
                zip(
                    ("id", "tenant_code", "name", "name_normalized", "code", "country", "city"),
                    u[:7],
                    strict=True,
                )
            )
            | {"created_at": u[7], "merged_into": u[8]}
            for u in units
        ],
        "aliases": [
            dict(zip(("tenant_code", "alias_normalized", "unit_id", "alias"), a, strict=True))
            for a in aliases
        ],
    }


def _alias(cur: psycopg.Cursor[Any], unit_id: str, alias: str, canonical: str) -> None:
    key = normalize_unit_name(alias)
    if key and key != normalize_unit_name(canonical):
        cur.execute(_ALIAS_SQL, (TENANT, key, unit_id, alias))


def _set_country(conn: psycopg.Connection[Any], unit_id: str, country: str) -> str | None:
    """Страна из эталона. Отказ базы (у точки есть проверки) не роняет прогон: вернуть причину."""
    try:
        with conn.transaction():
            conn.execute(
                "update units set country = %s where id = %s::uuid and country is null",
                (country, unit_id),
            )
    except psycopg.Error as exc:
        return str(exc).splitlines()[0]
    return None


def _write(conn: psycopg.Connection[Any], actions: list[Action]) -> list[str]:
    log: list[str] = []
    with conn.cursor() as cur:
        for a in (x for x in actions if x.kind in ("rename", "fill")):
            cur.execute(
                _UPDATE_SQL,
                {
                    "id": a.unit.id,
                    "name": a.new_name,
                    "key": normalize_unit_name(a.new_name) if a.new_name else None,
                    "code": a.new_code,
                    "city": a.new_city,
                },
            )
            if a.new_name:
                _alias(cur, a.unit.id, a.unit.name, a.new_name)
            if a.new_country and (why := _set_country(conn, a.unit.id, a.new_country)):
                log.append(f"страна {a.new_country} не поставлена у «{a.unit.name}»: {why}")
        for a in actions:
            if a.kind != "merge" or a.target is None:
                continue
            left = _rows(cur, _USAGE_ONE_SQL, a.unit.id)
            if left:
                raise RuntimeError(f"на дубль «{a.unit.name}» появились ссылки {left}: стоп")
            cur.execute(
                "update unit_aliases set unit_id = %s::uuid where unit_id = %s::uuid",
                (a.target.id, a.unit.id),
            )
            _alias(cur, a.target.id, a.unit.name, a.target.name)
            cur.execute("delete from units where id = %s::uuid", (a.unit.id,))
        for a in actions:
            if a.kind != "retire" or a.target is None:
                continue
            left = _rows(cur, _INSPECTIONS_ONE_SQL, a.unit.id)
            if left and left[0][0]:
                raise RuntimeError(f"у дубля «{a.unit.name}» появились проверки {left}: стоп")
            cur.execute(
                "update unit_aliases set unit_id = %s::uuid where unit_id = %s::uuid",
                (a.target.id, a.unit.id),
            )
            _alias(cur, a.target.id, a.unit.name, a.target.name)
            cur.execute(
                "update units set merged_into = %s::uuid where id = %s::uuid",
                (a.target.id, a.unit.id),
            )
    return log


def retire_blocked(actions: list[Action]) -> list[Action]:
    """Заблокированный дубль, который держит ТОЛЬКО история переносов, — на снятие (D538).

    Нет проверок и прочих ссылок (предписаний, поездок, рейтингов) и код не расходится с
    эталоном: тогда на точке эталона уже живёт всё, что у дубля было, а от него осталась
    лишь строка, на которую ссылается история.
    """
    out: list[Action] = []
    for a in actions:
        if a.kind == "blocked" and a.target is not None:
            usage = a.unit.usage
            code = a.match.ref.dodo_id if a.match.refs else None
            clash = bool(a.unit.code and code and a.unit.code != code)
            if not usage.inspections and not usage.other and not clash:
                a = replace(a, kind="retire", note="держит только история переносов")
        out.append(a)
    return out


# --- ручная карта имён (--map) ----------------------------------------------------------------


def read_map(path: Path) -> list[dict[str, str]]:
    """Строки карты: country, old_name, target_name, dodo_id, basis."""
    with path.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    need = {"country", "old_name", "target_name", "dodo_id", "basis"}
    if not rows or not need <= set(rows[0]):
        raise SystemExit(f"в {path} нужны колонки {sorted(need)}")
    return rows


def plan_map(rows: list[dict[str, str]], units: list[UnitRow], index: RefIndex) -> list[Action]:
    """План по карте имён. Ничего не пишет; отказ по строке не мешает остальным."""
    by_name = defaultdict(list)
    for u in units:
        by_name[fold_unit_name(u.name)].append(u)
    by_code = {u.code: u for u in units if u.code}
    actions: list[Action] = []

    def refuse(unit: UnitRow | None, row: dict[str, str], why: str) -> None:
        stub = unit or UnitRow(id="", name=row["old_name"], country=row["country"] or None)
        actions.append(Action("refused", stub, Match("matched", "map", HIGH), note=why))

    for row in rows:
        country, old, target, code = (
            row[k].strip() for k in ("country", "old_name", "target_name", "dodo_id")
        )
        olds = [u for u in by_name.get(fold_unit_name(old), []) if u.country in (None, country)]
        targets = [
            u for u in by_name.get(fold_unit_name(target), []) if u.country in (None, country)
        ]
        same_old = fold_unit_name(old) == fold_unit_name(target)
        if not olds or same_old:
            if not (targets and all(t.code in (None, code) for t in targets)) and not same_old:
                refuse(None, row, f"точки «{old}» нет, и «{target}» с кодом {code} тоже нет")
            continue  # уже сделано
        if len(olds) > 1:
            refuse(None, row, f"имя «{old}» носят несколько точек")
            continue
        unit = olds[0]
        ref_codes = {
            r.dodo_id
            for r in index.refs
            if r.country == country
            and fold_unit_name(r.clean_name) == fold_unit_name(target)
            and r.dodo_id
        }
        if unit.usage.inspections:
            refuse(unit, row, f"у точки {unit.usage.inspections} проверок")
        elif unit.code and unit.code != code:
            refuse(unit, row, f"у точки другой код Dodo ({unit.code})")
        elif ref_codes and code not in ref_codes:
            refuse(
                unit,
                row,
                f"в эталоне «{target}» — другой код Dodo ({', '.join(sorted(ref_codes))})",
            )
        elif targets:
            tgt = targets[0]
            if tgt.code and tgt.code != code:
                refuse(unit, row, f"у точки «{target}» другой код Dodo ({tgt.code})")
            elif unit.usage.other:
                refuse(
                    unit,
                    row,
                    f"на точку ссылаются предписания, поездки или рейтинги ({unit.usage.other})",
                )
            else:
                kind = "retire" if unit.usage.moves else "merge"
                actions.append(
                    Action(kind, unit, Match("matched", "map", HIGH, detail=row["basis"]),
                           target=tgt, note="по карте имён")
                )  # fmt: skip
        elif code in by_code and by_code[code].id != unit.id:
            refuse(unit, row, f"код {code} уже держит точка «{by_code[code].name}»")
        else:
            actions.append(
                Action("rename", unit, Match("matched", "map", HIGH, detail=row["basis"]),
                       new_name=target, new_code=None if unit.code else code,
                       new_country=country if unit.country is None else None)
            )  # fmt: skip
    return actions


def apply(dsn: str, actions_fn: Any, backup: Path) -> tuple[list[Action], RefIndex, list[str]]:
    """Одна транзакция: читаем, планируем, снимок в файл, правим. Файл раньше правок."""
    with psycopg.connect(dsn) as conn:
        apply_space(conn)
        with conn.transaction(), conn.cursor() as cur:
            units, index = load_db(cur)
            actions = actions_fn(units, index)
            if any(a.writes for a in actions):
                backup.parent.mkdir(parents=True, exist_ok=True)
                backup.write_text(
                    json.dumps(_snapshot(cur, actions), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            log = _write(conn, actions)
    return actions, index, log


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="записать, а не только показать")
    parser.add_argument("--backup", type=Path, help="куда снять снимок строк до правки (с --apply)")
    parser.add_argument(
        "--retire", action="store_true",
        help="снять дубли, на которые ссылается только история переносов (D538)",
    )  # fmt: skip
    parser.add_argument("--map", type=Path, help="CSV ручной карты имён; план только по ней")
    parser.add_argument("--from-dir", type=Path, help="сухой прогон по выгрузке CSV, без базы")
    parser.add_argument(
        "--min-confidence", choices=(HIGH, MEDIUM), default=MEDIUM,
        help="ниже порога точка не трогается; medium — улица или район без номера дома",
    )  # fmt: skip
    args = parser.parse_args(argv)

    map_rows = read_map(args.map) if args.map else None

    def make_plan(units: list[UnitRow], index: RefIndex) -> list[Action]:
        if map_rows is not None:
            return plan_map(map_rows, units, index)
        actions = plan(units, index, min_confidence=args.min_confidence)
        return retire_blocked(actions) if args.retire else actions

    if args.apply:
        if args.from_dir or not args.backup:
            parser.error("--apply работает по базе и требует --backup ФАЙЛ")
        with acting_space(SYSTEM_SPACE):
            actions, index, log = apply(
                admin_dsn() or check_environment().dsn, make_plan, args.backup
            )
        print(render(actions, index))
        print("\n".join(log))
        print(f"\nЗаписано: {sum(a.writes for a in actions)}; снимок — {args.backup}")
        return 0
    if args.from_dir:
        units, index = load_dir(args.from_dir)
    else:
        with (
            acting_space(SYSTEM_SPACE),
            psycopg.connect(check_environment().dsn) as conn,
            conn.cursor() as cur,
        ):
            apply_space(conn)
            conn.read_only = True
            units, index = load_db(cur)
    print(render(make_plan(units, index), index))
    print("\nСухой прогон, ничего не записано")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
