"""Строки для старых открытых запросов экшн-плана — разовый доливщик (#1168).

Запросы, заведённые до электронного плана, строк не имеют. Открытый запрос без файла
становится электронным: строки — по нарушениям проверки, сроки — от начала отсчёта.
Сроки записей берутся у движка (`audit.py score`), своих чисел нет. Запросы с файлом,
принятые и закрытые не трогаются.

    python tools/plan_rows_backfill.py            # сухой прогон: что будет сделано
    python tools/plan_rows_backfill.py --apply    # сделать

Повторяем: второй прогон берёт только запросы без строк. Что не вышло (нет D1–D3,
методика издания не читается) — в списке пропущенных с причиной.
"""

from __future__ import annotations

import argparse
import sys

from src.db import queries
from src.db.errors import ActionPlanError
from src.db.plan_backfill import backfill_rows
from src.db.reach import reach_of
from src.domain.tenants import HQ_TENANT
from src.report import plan_terms
from src.report.letters import sources as letter_sources


def main(argv: list[str] | None = None) -> int:
    args = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    args.add_argument("--apply", action="store_true", help="сделать, а не показать")
    apply = args.parse_args(argv).apply

    reach = reach_of(HQ_TENANT)
    terms = plan_terms.provider(
        lambda ident: queries.get_inspection(ident, reach=reach, include_on_review=True),
        papers=letter_sources(),
    )
    try:
        report = backfill_rows(terms=terms, apply=apply)
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
