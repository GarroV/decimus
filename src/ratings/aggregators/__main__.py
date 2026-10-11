"""Руками (на площадке — `docker exec decimus-bot-1 python -m src.ratings.aggregators …`):

- без аргументов — собрать все агрегаторы сейчас;
- `run wolt glovo` — только перечисленные;
- `seed <файл.json>` — наполнить справочник точек агрегаторов «по известной
  точке» (Glovo, Chowdeck) из файла разведки: список объектов с полями
  `aggregator, point_key, country_code, name, url, lat, lng, dodo_id, dodo_name,
  link_distance_m, extra`. Повтор безопасен: точка обновляется по ключу.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import date
from pathlib import Path
from typing import Any

from src.db import agg_store
from src.db.agg_store import PointRow

from .collect import run_all


def _opt(value: object, kind: type) -> Any:
    return None if value is None else kind(value)


def _point(row: dict[str, Any]) -> PointRow:
    missing = [f for f in ("aggregator", "point_key", "country_code") if not row.get(f)]
    if missing:
        raise SystemExit(f"В записи справочника нет полей {missing}: {row}")
    return PointRow(
        str(row["aggregator"]),
        str(row["point_key"]),
        str(row["country_code"]),
        _opt(row.get("name"), str),
        _opt(row.get("url"), str),
        _opt(row.get("lat"), float),
        _opt(row.get("lng"), float),
        _opt(row.get("dodo_id"), str),
        _opt(row.get("dodo_name"), str),
        _opt(row.get("link_distance_m"), int),
        dict(row.get("extra") or {}),
    )


def seed(path: Path) -> int:
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise SystemExit("Файл справочника — список объектов")
    points = [_point(row) for row in rows]
    return agg_store.save(points, [])[0]


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    args = sys.argv[1:]
    if args[:1] == ["seed"] and len(args) == 2:
        print(f"Точек в справочнике записано: {seed(Path(args[1]))}")
        return
    outcomes = run_all(date.today(), only=args[1:] if args[:1] == ["run"] else ())
    failed = [o.aggregator for o in outcomes if not o.ok]
    if failed:
        raise SystemExit(f"Сбой агрегаторов: {', '.join(failed)}")


if __name__ == "__main__":
    main()
