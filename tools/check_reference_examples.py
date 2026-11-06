"""Проверить движок текущей ветки на локальных эталонах Белграда вне git (D002, #1471)."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reference-root",
        type=Path,
        default=Path(
            os.environ.get(
                "DECIMUS_REFERENCE_ROOT", str(Path.home() / "Documents/projects/decimus")
            )
        ),
        help=(
            "копия с data/ и examples/; по умолчанию DECIMUS_REFERENCE_ROOT "
            "или ~/Documents/projects/decimus"
        ),
    )
    args = parser.parse_args()
    reference = args.reference_root.expanduser().resolve()
    cases = (("belgrade-1", 97.5, 5), ("belgrade-2", 97.0, 6))
    required = [
        reference / "data" / name for name in ("checklist.csv", "zones.csv", "scoring.json")
    ]
    required += [reference / "examples" / name / "inspection.json" for name, _, _ in cases]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        print("Проверка НЕ выполнена: отсутствуют локальные эталоны (D002):", file=sys.stderr)
        for path in missing:
            print(f"  {path}", file=sys.stderr)
        print(
            "Укажите --reference-root или DECIMUS_REFERENCE_ROOT; данные в git не добавлять.",
            file=sys.stderr,
        )
        return 2

    # The source checkout supplies data only: always execute this worktree's engine.
    engine = Path(__file__).resolve().parents[1] / "engine/audit.py"
    failed = False
    with tempfile.TemporaryDirectory(prefix="decimus-reference-check-") as directory:
        for name, percentage, d1 in cases:
            env = dict(
                os.environ,
                CHECKLIST_DIR=str(reference / "data"),
                INSPECTION_FILE=str(reference / "examples" / name / "inspection.json"),
            )
            run = subprocess.run(  # noqa: S603 - fixed interpreter and engine, no shell
                [sys.executable, str(engine), "score", "--json"],
                cwd=directory,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            if run.returncode:
                print(
                    f"{name}: движок завершился с кодом {run.returncode}; проверка не пройдена.",
                    file=sys.stderr,
                )
                failed = True
                continue
            try:
                score = json.loads(run.stdout)
                actual = (
                    score["pct"],
                    score["grade"],
                    *(score["counts"][level] for level in ("D1", "D2", "D3")),
                )
            except (ValueError, KeyError, TypeError):
                print(f"{name}: движок не вернул ожидаемый JSON оценки.", file=sys.stderr)
                failed = True
                continue
            expected = (percentage, "A", d1, 0, 0)
            passed = actual == expected
            print(
                f"{name}: {'PASS' if passed else 'FAIL'}; оценка/классы {actual}, эталон {expected}"
            )
            failed |= not passed
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
