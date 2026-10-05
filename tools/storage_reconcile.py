"""Сверка хранилища файлов с таблицами — экшн-планы и предписания (#496).

Показывает расхождения между хранилищем и базой и НИЧЕГО не удаляет:

* объект без строки — файл лежит, а версии/ответа к нему в базе нет;
* строка без объекта — версия видна в истории, а файла в хранилище нет;
* ссылка не разбирается — строка ссылается не туда, проверить её нечем.

Участки: `action-plans/` ↔ `action_plan_files`, `prescriptions/` ↔
`prescription_replies` (только ответы с файлом). Объект без строки моложе
порога не считается — это загрузка в эту минуту; он показывается отдельно.

Только чтение: база — роль приложения (`DATABASE_URL`) в сессии только для
чтения, хранилище — `S3_*`, только список объектов.

    python tools/storage_reconcile.py                   # оба участка
    python tools/storage_reconcile.py --grace-minutes 30

Код возврата: 0 — всё сходится, 1 — есть расхождения, 2 — сверка не
состоялась (нет окружения, база или хранилище не ответили).
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta

import psycopg

from src.db.errors import ConfigError, StorageError
from src.db.storage_reconcile import DEFAULT_GRACE, AreaReport, reconcile_live

EXIT_CLEAN = 0
EXIT_DISCREPANCIES = 1
EXIT_NOT_RUN = 2

_MB = 1024 * 1024


def _размер(size: int) -> str:
    return f"{size / _MB:.1f} МБ" if size >= _MB // 10 else f"{size} байт"


def _когда(moment: datetime) -> str:
    return f"{moment.astimezone(UTC):%Y-%m-%d %H:%M} UTC"


def _печать(итог: AreaReport) -> None:
    print(
        f"\n{итог.area}: хранилище {итог.prefix} — объектов {итог.objects}; "
        f"база — строк с файлом {итог.rows}; совпало {итог.matched}"
    )
    if итог.clean:
        print("  расхождений нет")
    if итог.orphan_objects:
        print(f"  объект без строки: {len(итог.orphan_objects)}")
        for obj in итог.orphan_objects:
            print(f"    {obj.key}  {_размер(obj.size)}, положен {_когда(obj.modified)}")
    if итог.missing_objects:
        print(f"  строка без объекта: {len(итог.missing_objects)}")
        for row in итог.missing_objects:
            print(f"    строка {row.id} → {row.storage_path}")
    if итог.bad_links:
        print(f"  ссылка не разбирается или ведёт мимо {итог.prefix}: {len(итог.bad_links)}")
        for row in итог.bad_links:
            print(f"    строка {row.id} → {row.storage_path!r}")
    if итог.fresh_skipped:
        print(f"  свежие объекты без строки, не считаются: {len(итог.fresh_skipped)}")
        for obj in итог.fresh_skipped:
            print(f"    {obj.key}  положен {_когда(obj.modified)}")


def main(argv: list[str] | None = None) -> int:
    args = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    args.add_argument(
        "--grace-minutes",
        type=int,
        default=int(DEFAULT_GRACE.total_seconds() // 60),
        help="объект без строки моложе стольких минут не считается расхождением",
    )
    grace_minutes = args.parse_args(argv).grace_minutes
    if grace_minutes < 0:
        print("--grace-minutes не может быть отрицательным", file=sys.stderr)
        return EXIT_NOT_RUN

    try:
        итоги = reconcile_live(grace=timedelta(minutes=grace_minutes))
    except ConfigError as exc:
        print(f"сверка не состоялась — окружение: {exc}", file=sys.stderr)
        return EXIT_NOT_RUN
    except StorageError as exc:
        print(f"сверка не состоялась — хранилище: {exc}", file=sys.stderr)
        return EXIT_NOT_RUN
    except psycopg.Error as exc:
        # Тип, а не текст драйвера: в тексте бывает адрес базы с учёткой.
        print(f"сверка не состоялась — база не ответила ({type(exc).__name__})", file=sys.stderr)
        return EXIT_NOT_RUN

    for итог in итоги:
        _печать(итог)
    всего = sum(итог.discrepancies for итог in итоги)
    if всего:
        print(
            f"\nИТОГ: расхождений {всего}. Ничего не удалено — "
            "что делать, см. docs/08-deploy.md §4.9.3"
        )
        return EXIT_DISCREPANCIES
    print("\nИТОГ: хранилище и база сходятся")
    return EXIT_CLEAN


if __name__ == "__main__":
    raise SystemExit(main())
