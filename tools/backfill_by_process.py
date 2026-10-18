"""Разбивка по процессам для проверок, принятых до миграции 0073 — разовый доливщик (D507).

Колонка `inspections.by_process` пишется сливом и правкой на приёмке; проверки,
сданные раньше, её не имеют, и карточка «Где сеть теряет проценты» на главной их
не видит. Доливщик прогоняет движок по записанной проверке её же методикой
(`rescore`, тот же путь, что у правки на приёмке) и пишет ТОЛЬКО `by_process`.

Оценка не пересчитывается и не переписывается: движок обязан выдать тот же
процент и ту же букву, что стоят в базе, и сумму вкладов процессов, равную
вычету. Не сошлось — проверка пропускается с громким сообщением, а код возврата
1 говорит, что такое было. Историческим (`origin = 'legacy'`, D332) разбивка не
кладётся никогда; отклонённые не трогаются.

Идёт под администратором истории (`DATABASE_RETRACTION_URL`): сданную проверку
менять может только он, и колонка выдана ему отдельным правом, а сторож
`inspections_by_process_guarded` (0073) пускает запись только из NULL.

    python tools/backfill_by_process.py            # сухой прогон: что будет записано
    python tools/backfill_by_process.py --apply    # записать

Повторяемо: второй прогон берёт только проверки без разбивки.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

# Окружение — до импорта дверей (как у `tools/space.py`).
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psycopg  # noqa: E402
from psycopg.types.json import Json  # noqa: E402

from src.db.config import load_retraction_settings  # noqa: E402
from src.db.models import InspectionDetail  # noqa: E402
from src.db.push import _by_process_payload  # noqa: E402
from src.db.queries import get_inspection  # noqa: E402
from src.db.reach import Reach  # noqa: E402
from src.domain.models import Score  # noqa: E402
from src.report.letters import Papers, sources  # noqa: E402
from src.report.rescore import rescore  # noqa: E402

_PENDING_SQL = """
select id, tenant_code
from inspections
where by_process is null and origin <> 'legacy' and retracted_at is null
order by inspection_date, id
"""

_SET_SQL = """
update inspections set by_process = %s
where id = %s and by_process is null and origin <> 'legacy'
"""

#: Допуск сверки итога: вычеты движок округляет до сотых, вклады процессов — до
#: десятитысячных, и их сумма расходится с итогом на доли округления.
SUM_TOLERANCE = 0.05


def refusal(detail: InspectionDetail, score: Score) -> str | None:
    """Почему эту проверку нельзя долить; `None` — можно.

    Чистая функция без базы: именно здесь живёт сверка, ради которой доливщик не
    имеет права переписать оценку (процент и буква из движка обязаны совпасть
    с записанными), и тест гоняет её на испорченных входах.
    """
    if score.pct != detail.inspection.pct or score.grade != detail.inspection.grade:
        return (
            f"движок дал {score.pct}% {score.grade}, в базе {detail.inspection.pct}% "
            f"{detail.inspection.grade}"
        )
    if not score.by_process:
        return "движок не вернул разбивку по процессам"
    total = sum(p.loss for p in score.by_process.values())
    if abs(total - score.deductions) > SUM_TOLERANCE:
        return f"вклады процессов дают {total:.4f}, вычет проверки {score.deductions:.4f}"
    return None


def main(argv: list[str] | None = None) -> int:
    args = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    args.add_argument("--apply", action="store_true", help="записать, а не показать")
    apply = args.parse_args(argv).apply

    papers: Papers = sources()
    dsn = load_retraction_settings().dsn
    with psycopg.connect(dsn) as conn:
        pending = conn.execute(_PENDING_SQL).fetchall()
    print(f"проверок без разбивки по процессам: {len(pending)}")

    done = skipped = 0
    for ident, tenant in pending:
        reach = Reach(tenant=str(tenant), tenants=(str(tenant),), countries=None)
        try:
            detail = get_inspection(
                str(ident), reach=reach, include_retracted=True, include_on_review=True
            )
            if detail is None:
                raise RuntimeError("проверка не читается под администратором истории")
            score = rescore(detail, papers=papers)
            why = refusal(detail, score)
        except Exception as exc:  # любой отказ называется и идёт дальше
            why = f"{type(exc).__name__}: {exc}"
            score = None
        if why is not None or score is None:
            skipped += 1
            print(f"ПРОПУЩЕНА {ident} ({tenant}): {why}", file=sys.stderr)
            continue
        if not apply:
            print(f"записал бы {ident}: процессов {len(score.by_process)}")
            continue
        with psycopg.connect(dsn) as conn:
            cur = conn.execute(_SET_SQL, (Json(_by_process_payload(score)), str(ident)))
            if cur.rowcount != 1:
                skipped += 1
                print(f"ПРОПУЩЕНА {ident}: строка уже изменилась", file=sys.stderr)
                continue
        done += 1

    if not apply:
        print(f"сухой прогон — ничего не записано; сделать: --apply (пропущено бы: {skipped})")
    else:
        print(f"записано: {done}, пропущено: {skipped}")
    return 1 if skipped else 0


if __name__ == "__main__":
    raise SystemExit(main())
