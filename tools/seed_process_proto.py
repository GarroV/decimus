"""Посев прототипа «итоги по процессам» (D714) на превью-стенд: только синтетика.

Три случая, каждый дважды — по прежнему изданию демо-методики (итог по зонам)
и по изданию процессов (та же методика, в `scoring.json` включён
`d3.mode = "once_per_process"`). Одни и те же записи, две оценки рядом:

* «Просрочка в 3 зонах» — один и тот же D3 записан на кухне, складе и в зале;
* «Одно и то же в двух зонах» — D1 и D2 повторяются в двух зонах (как Белград-2);
* «Чистая» — одно мелкое замечание.

Проверки собираются тем же кодом, что посев открытого демо (`_build` → слив →
кадры → приёмка). Издание процессов кладётся копией в том состояния
(`STATE_DIR/process-edition`), боевая методика не участвует вовсе.

Повторный запуск ничего не дублирует: точка, у которой проверка уже есть,
пропускается.

Запуск на превью-стенде (§8.22 `docs/08-deploy.md`):

    %P% --profile seed run --rm --no-deps seed python tools/seed_process_proto.py
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tools"))

import psycopg  # noqa: E402
import seed_demo  # noqa: E402 -- путь к tools выставляется выше
import seed_open_demo as od  # noqa: E402
from seed_web_demo import _require_local_dsn  # noqa: E402

from src import domain  # noqa: E402
from src.db.accept import accept_inspection  # noqa: E402
from src.db.config import check_environment  # noqa: E402
from src.db.directory import upsert_unit  # noqa: E402
from src.db.photos import upload_photos  # noqa: E402
from src.db.push import push_inspection  # noqa: E402
from src.db.space import SYSTEM_SPACE, acting_space, apply_space  # noqa: E402
from src.domain.engine import chat_dir  # noqa: E402
from src.domain.tenants import HQ_TENANT  # noqa: E402

#: Чаты прототипа — из вымышленного диапазона демо, рядом с открытым демо (601…, 701).
FIRST_CHAT = 999_000_000_801
#: Цена D3 за процесс в издании процессов (D714, вариант, показанный владельцу).
PROCESS_LOSS = 10.0
COUNTRY = "RS"
CITY = "Northgate"

N = od.Note

CASES: tuple[tuple[str, tuple[od.Note, ...]], ...] = (
    (
        "Просрочка в 3 зонах",
        (
            N("DEM05", "D3", "kitchen", "Соус с истёкшим сроком на линии сборки.", ("p09.jpg",)),
            N(
                "DEM05",
                "D3",
                "storage",
                "Две пачки сыра на день позже срока на стеллаже.",
                ("p18.jpg",),
            ),
            N("DEM05", "D3", "dining", "Просроченные напитки в холодильнике зала.", ("p26.jpg",)),
            N("DEM06", "D1", "kitchen", "Разделочная доска без обработки после смены."),
            N("DEM13", "D1", "dining", "Мусор у колонны у входа."),
            N("DEM08", "D1", "storage", "Открытая банка без даты вскрытия."),
        ),
    ),
    (
        "Одно и то же в двух зонах",
        (
            N("DEM13", "D1", "dining", "Крошки под столами у окна.", ("p19.jpg",)),
            N("DEM13", "D1", "kitchen", "Мусор в углу у печи.", ("p20.jpg",)),
            N("DEM12", "D2", "kitchen", "Налёт на тестомесе.", ("p03.jpg",)),
            N("DEM12", "D2", "dining", "Грязный запайщик стаканов у кассы.", ("p04.jpg",)),
            N("DEM10", "D1", "staff", "Закончились бумажные полотенца у раковины."),
            N("DEM07", "D1", "storage", "Мешок муки на полу у двери."),
        ),
    ),
    (
        "Чистая",
        (N("DEM02", "D1", "facade", "Следы рук на стекле входной двери.", ("p05.jpg",)),),
    ),
)

EDITIONS = (("зоны", False), ("процессы", True))


def process_edition(state_dir: Path) -> Path:
    """Копия демо-методики с режимом процессов — в томе состояния, на каждый запуск заново."""
    dst = state_dir / "process-edition"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(seed_demo.DEMO_DATA_DIR, dst)
    path = dst / "scoring.json"
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg["d3"] = {"mode": "once_per_process", "process_loss": PROCESS_LOSS}
    cfg["collapse"] = "item"
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
    return dst


def _has_inspection(dsn: str, unit: str) -> bool:
    with psycopg.connect(dsn) as conn:
        apply_space(conn)
        row = conn.execute(
            "select 1 from inspections i join units u on u.id = i.unit_id where u.name = %s",
            (unit,),
        ).fetchone()
    return row is not None


def _build(chat_id: int, unit: str, notes: tuple[od.Note, ...], photos_dir: Path | None) -> None:
    """Проверка тем же кодом, что бот и мини-апп; третья зона просрочки — словом человека."""
    settings = domain.check_environment()
    work_dir = chat_dir(chat_id, settings)
    if work_dir.exists():
        shutil.rmtree(work_dir)
    domain.start_inspection(
        chat_id,
        unit=unit,
        kind="planned",
        report_lang="ru",
        ui_lang="ru",
        speech_lang="ru",
        date=date.today().isoformat(),
        city=CITY,
        auditor="Olivia Hart",
        tenant=HQ_TENANT,
    )
    for note in notes:
        frames = []
        for name in note.photos:
            raw = od._photo_bytes(name, photos_dir)
            if raw is not None:
                frames.append(domain.save_upload(raw, settings))
        domain.add_finding(
            chat_id, note.code, note.level, note.zone, note.text, photos=frames, zone_by_person=True
        )


def seed() -> int:
    state_dir = seed_demo.demo_state_dir()
    os.environ["STATE_DIR"] = str(state_dir)
    editions = {False: seed_demo.DEMO_DATA_DIR, True: process_edition(state_dir)}
    raw_dir = (os.environ.get(od.PHOTOS_VAR) or "").strip()
    photos_dir = Path(raw_dir) if raw_dir and Path(raw_dir).is_dir() else None
    dsn = check_environment().dsn
    _require_local_dsn(dsn)
    upload = photos_dir is not None and od._storage_ready()
    chat = FIRST_CHAT
    for number, (title, notes) in enumerate(CASES, 1):
        for word, by_process in EDITIONS:
            unit = f"Прототип-{number} · {title} · {word}"
            chat += 1
            if _has_inspection(dsn, unit):
                print(f"{unit}: уже есть, пропущено")
                continue
            os.environ["AUDIT_DATA_DIR"] = str(editions[by_process])
            upsert_unit(unit, country=COUNTRY, city=CITY, tenant=HQ_TENANT)
            _build(chat, unit, notes, photos_dir)
            ident = push_inspection(chat, allow_unknown_version=True)
            if upload:
                upload_photos(ident, fetch=od._read_frame)
            score = domain.score(chat)
            accept_inspection(
                ident, tenant=HQ_TENANT, actor="Olivia Hart", terms=od._plan_terms(HQ_TENANT)
            )
            print(f"{unit}: {score.pct:g}% {score.grade} -> /inspections/{ident}")
    return 0


if __name__ == "__main__":
    with acting_space(SYSTEM_SPACE):
        sys.exit(seed())
