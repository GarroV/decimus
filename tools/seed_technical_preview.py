"""Seed an isolated technical-control preview with fictional visits and real confirmations.

Run only after the regular demo seed, with TECHNICAL_PREVIEW_SEED=1 and WEB_DEMO=1.
No messaging transport is used. The supplied methodology remains outside Git.
"""

from __future__ import annotations

import io
import json
import os
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw

from src import domain
from src.db import push_inspection
from src.db.accept import accept_inspection
from src.db.directory import upsert_unit
from src.db.photos import upload_photos
from src.db.queries import list_inspections
from src.db.reach import own_reach
from src.db.retract import retract_inspection
from src.db.space import acting_space
from src.domain.state import finish_inspection
from src.domain.technical import confirm, snapshot
from src.domain.tenants import HQ_TENANT
from src.domain.uploads import upload_file


def frame(label: str) -> bytes:
    image = Image.new("RGB", (900, 650), "#e5e5dc")
    draw = ImageDraw.Draw(image)
    draw.rectangle((130, 130, 770, 480), outline="#43433e", width=12)
    draw.text((160, 220), "DEMONSTRATION ONLY", fill="#242424")
    draw.text((160, 260), label, fill="#242424")
    out = io.BytesIO()
    image.save(out, format="JPEG")
    return out.getvalue()


def start(chat: int, *, lang: str, day: str) -> None:
    domain.start_inspection(
        chat,
        unit="Technical-1",
        city="beograd",
        kind="planned",
        report_lang=lang,
        ui_lang=lang,
        speech_lang=lang,
        date=day,
        auditor="Technical preview",
        tenant=HQ_TENANT,
    )


def completed(chat: int, day: str, *, defective: bool) -> str:
    start(chat, lang="ru", day=day)
    env = domain.check_environment()
    photo = domain.save_upload(frame("Technical evidence sample"), env)
    if defective:
        finding = domain.add_finding(
            chat,
            "TEH15",
            "D1",
            "facade",
            "Демонстрация: часть подсветки вывески не работает.",
            comment="Восстановить работу подсветки.",
            photos=[photo],
        )
    else:
        finding = None
    readings = domain.add_finding(
        chat,
        "INF09",
        "D0",
        "hot_kitchen",
        "Демонстрационные настройки печи: 250 °C, 6 минут.",
        photos=[domain.save_upload(frame("Oven display sample"), env)],
    )
    run_id = domain.get_state(chat).run_id
    for row in snapshot(chat)["checks"]:
        extra = {}
        status = "ok"
        if row["id"] == "TC001" and defective:
            status = "issue"
            extra = {"finding_numbers": [finding.n]}
        elif row.get("requires_photo"):
            status = "recorded"
            extra = {"finding_numbers": [readings.n]}
        confirm(chat, run_id=run_id, check_id=row["id"], zone=row["zone"], status=status, **extra)
    finish_inspection(chat, run_id, datetime.now(UTC))
    ident = push_inspection(chat, allow_unknown_version=True)

    def read_frame(ref: str) -> bytes | None:
        path = upload_file(ref, env)
        return path.read_bytes() if path is not None else None

    upload_photos(ident, fetch=read_frame)
    accept_inspection(ident, tenant=HQ_TENANT, actor="Technical preview")
    return str(ident)


def main() -> None:
    if os.environ.get("TECHNICAL_PREVIEW_SEED") != "1" or os.environ.get("WEB_DEMO") != "1":
        raise SystemExit("Only the isolated WEB_DEMO technical preview may be seeded")
    if Path(os.environ.get("AUDIT_DATA_DIR", "")) != Path("/app/data"):
        raise SystemExit("Expected the isolated methodology mount /app/data")
    # Guard data access before any write. The existing seed uses this same DSN check.
    from src.db.config import check_environment

    if urlsplit(check_environment().dsn).hostname != "db":
        raise SystemExit("Only the dedicated compose-local PostgreSQL is allowed")
    upsert_unit("Technical-1", country="RS", city="beograd", tenant=HQ_TENANT)
    for review in (False, True):
        for previous in list_inspections(
            reach=own_reach(HQ_TENANT), unit="Technical-1", on_review=review
        ):
            if previous.auditor == "Technical preview":
                retract_inspection(
                    previous.id,
                    tenant=HQ_TENANT,
                    reason="Обновление демонстрационного набора технического контроля",
                )
    today = date.today()
    ids = [
        completed(999000000711, (today - timedelta(days=180)).isoformat(), defective=True),
        completed(999000000712, (today - timedelta(days=30)).isoformat(), defective=False),
    ]
    for chat, lang in ((999000000701, "en"), (999000000702, "ru")):
        start(chat, lang=lang, day=today.isoformat())
    print(
        json.dumps({"technical_inspections": ids, "active_checks": snapshot(999000000702)["total"]})
    )


if __name__ == "__main__":
    with acting_space(HQ_TENANT):
        main()
