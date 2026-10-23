"""Строки для старых открытых запросов экшн-плана — разовый доливщик (#1168).

Запросы, заведённые до электронного плана, строк не имеют. Открытый запрос без файла
становится электронным: строки — по нарушениям проверки, сроки — от начала отсчёта.
Запросы с файлом, принятые и закрытые не трогаются.

    python tools/plan_rows_backfill.py            # сухой прогон: что будет сделано
    python tools/plan_rows_backfill.py --apply    # сделать

Повторяем: второй прогон берёт только запросы без строк. Что не вышло (нет D1–D3,
методика издания не читается) — в списке пропущенных с причиной.
"""

from __future__ import annotations

import argparse
import sys

from src.db.errors import ActionPlanError
from src.db.plan_backfill import backfill_rows


def main(argv: list[str] | None = None) -> int:
    args = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    args.add_argument("--apply", action="store_true", help="сделать, а не показать")
    apply = args.parse_args(argv).apply

    try:
        report = backfill_rows(apply=apply)
    except ActionPlanError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"открытых запросов без строк: {report.candidates}")
    verb = "сделано" if report.applied else "будет сделано"
    print(f"{verb}: запросов {report.converted}, строк {report.rows}")
    for line in report.skipped:
        print(f"пропущен: {line}")
    if not apply and report.converted:
        print("сухой прогон — ничего не записано; --apply, чтобы записать")
    return 0


if __name__ == "__main__":
    sys.exit(main())
