#!/usr/bin/env python3
"""Найти проверки-дубли — одну проверку в базе дважды с разными датами (#1635).

Без аргументов только ЧИТАЕТ: печатает пары принятых и не снятых проверок одной
точки, у которых совпали оценка, буква и набор записей, а даты отличаются не
больше чем на `DUPLICATE_WINDOW_DAYS` (то же правило, что у отказа при
подтверждении, — `src/db/duplicates.py`). Подключение — `DATABASE_RETRACTION_URL`
(администратор истории), как у снятия проверки.

Снять лишнюю — отдельным запуском и осознанно, по одной:

    python scripts/duplicate_visits.py --retract <id> --tenant <код> --reason "дубль <id другой>"

Снятие — пометка, а не удаление (D089): строка и причина остаются, обратимо.
Какую из двух снимать, скрипт не решает: чаще неверна запись, сохранённая раньше
(её завели с ошибочной датой, а потом заново с верной), но это решает человек по
карточкам. На проде запускать только после «да» владельца.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg

from src.db.config import load_retraction_settings
from src.db.duplicates import DUPLICATE_WINDOW_DAYS, signature
from src.db.retract import retract_inspection

_ROWS_SQL = """
select i.id::text, i.tenant_code, u.name, i.inspection_date, i.pushed_at, i.pct::text, i.grade,
       coalesce(
           (select array_agg(array[f.code, f.level, f.zone, coalesce(t.text, '')])
              from findings f
              left join translations t
                     on t.entity_type = 'finding' and t.entity_id = f.id
                    and t.field = 'text' and t.lang = i.speech_lang
             where f.inspection_id = i.id),
           '{}'
       )
from inspections i join units u on u.id = i.unit_id
where i.status = 'finalized' and i.retracted_at is null
order by i.unit_id, i.inspection_date, i.pushed_at
"""


def find_pairs(rows: list[tuple[Any, ...]]) -> list[tuple[tuple[Any, ...], tuple[Any, ...]]]:
    """Пары-дубли среди строк `_ROWS_SQL` (внутри одной точки и пространства)."""
    пары = []
    for a_pos, a in enumerate(rows):
        a_sig = signature(tuple(x) for x in a[7])
        if not a_sig:
            continue
        for b in rows[a_pos + 1 :]:
            if (b[1], b[2]) != (a[1], a[2]):
                continue
            if abs((b[3] - a[3]).days) > DUPLICATE_WINDOW_DAYS:
                continue
            if (a[5], a[6]) == (b[5], b[6]) and a_sig == signature(tuple(x) for x in b[7]):
                пары.append((a, b))
    return пары


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--retract", metavar="ID", help="снять проверку с этим id")
    parser.add_argument("--tenant", help="код пространства снимаемой проверки")
    parser.add_argument("--reason", help="причина снятия (обязательна)")
    args = parser.parse_args()

    if args.retract:
        if not args.tenant or not args.reason:
            parser.error("--retract требует --tenant и --reason")
        done = retract_inspection(args.retract, tenant=args.tenant, reason=args.reason)
        print(f"снята {done.inspection_id}: {done.reason}")
        return 0

    with psycopg.connect(load_retraction_settings().dsn) as conn, conn.cursor() as cur:
        cur.execute("set transaction read only")
        cur.execute(_ROWS_SQL)
        rows = cur.fetchall()
    пары = find_pairs(rows)
    for a, b in пары:
        print(f"{a[2]} [{a[1]}] {a[5]}% {a[6]}")
        print(f"  {a[0]}  {a[3]}  записана {a[4]:%Y-%m-%d %H:%M}")
        print(f"  {b[0]}  {b[3]}  записана {b[4]:%Y-%m-%d %H:%M}")
    print(f"пар-дублей: {len(пары)}")
    return 1 if пары else 0


if __name__ == "__main__":
    raise SystemExit(main())
