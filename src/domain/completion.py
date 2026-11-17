"""Durable run snapshots awaiting archival after the auditor received the PDF.

Snapshots live outside chat state so a new visit cannot erase an unfinished
archive. They contain the original engine input, downloaded photos and the exact
PDF delivered; retries always use that run's immutable input.
"""

from __future__ import annotations

import json
import logging
import shutil
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from .config import DATA_FILES, Settings, check_environment
from .edition import pin
from .edition import snapshot as edition_snapshot
from .engine import DOMAIN_KEY, chat_dir, state_file
from .errors import DomainError
from .revision import revision
from .state import _read_raw, _write_atomic, read_state, state_lock
from .version import compose

logger = logging.getLogger(__name__)

JOBS_DIR = "completed-runs"
ARCHIVED_KEEP_SEC = 24 * 60 * 60


def snapshot(chat_id: int, run_id: str, expected_revision: str) -> Settings:
    """Copy a sealed run under the state lock, never a replacement visit."""
    env = check_environment()
    source = state_file(chat_id, env)
    target = replace(env, state_dir=env.state_dir / JOBS_DIR / (run_id or expected_revision))
    dest = state_file(chat_id, target)
    with state_lock(source):
        current = read_state(chat_id, env)
        if current is None or current.run_id != run_id or revision(current) != expected_revision:
            raise DomainError("Сменился запуск или содержимое проверки; сборка отменена")
        dest.parent.mkdir(parents=True, exist_ok=True)
        pinned = pin(chat_id, env)
        kept = edition_snapshot(env, current.checklist_version, current.checklist_code)
        if kept is not None:
            pinned = replace(pinned, data_dir=kept)
        _write_atomic(dest, _read_raw(source))
    return replace(pinned, state_dir=target.state_dir)


def prepare(chat_id: int, env: Settings, pdf: Path, photos: dict[str, str]) -> Path:
    """Persist the report and available evidence BEFORE exposing completion."""
    root = chat_dir(chat_id, env)
    report = root / "report" / pdf.name
    report.parent.mkdir(exist_ok=True)
    shutil.copyfile(pdf, report)
    saved: dict[str, str] = {}
    frames = root / "photos"
    frames.mkdir(exist_ok=True)
    for index, (ref, path) in enumerate(photos.items()):
        dest = frames / str(index)
        shutil.copyfile(path, dest)
        saved[ref] = str(dest)
    inspection = read_state(chat_id, env)
    if inspection is None:
        raise DomainError("Снимок проверки отсутствует")
    _write_atomic(
        root / "delivery.json",
        {
            "version": 1,
            "run_id": inspection.run_id,
            "inspection_revision": revision(inspection),
            "method_version": compose(env.data_dir, DATA_FILES),
            "checklist_code": inspection.checklist_code,
            "stage": "prepared",
            "photos": saved,
            "data_dir": str(env.data_dir),
            "report": str(report),
        },
    )
    return report


def mark(chat_id: int, env: Settings, stage: str) -> None:
    path = chat_dir(chat_id, env) / "delivery.json"
    with state_lock(path):
        raw = _read_raw(path)
        raw["stage"] = stage
        if stage == "archived":
            raw["archived_at"] = time.time()
        _write_atomic(path, raw)


def pending() -> list[tuple[int, Settings, dict[str, str]]]:
    """Only acknowledged PDF deliveries may enter the archive automatically."""
    env = check_environment()
    jobs = env.state_dir / JOBS_DIR
    result = []
    for path in jobs.glob("*/chat_*/delivery.json"):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if raw.get("stage") != "delivered":
                continue
            chat_id = int(path.parent.name.removeprefix("chat_"))
            job = replace(env, state_dir=path.parent.parent, data_dir=Path(raw["data_dir"]))
            validate(chat_id, job)
            result.append((chat_id, job, dict(raw["photos"])))
        except (DomainError, OSError, ValueError, KeyError, TypeError):
            logger.exception("Сохранённая сдача повреждена; автоматическая запись отклонена")
    return result


def finish_snapshot(chat_id: int, env: Settings, finished_at: datetime) -> None:
    path = state_file(chat_id, env)
    with state_lock(path):
        raw = _read_raw(path)
        block = dict(raw[DOMAIN_KEY])
        block["finished_at"] = finished_at.isoformat()
        raw[DOMAIN_KEY] = block
        _write_atomic(path, raw)


def publish_finished(chat_id: int, env: Settings, run_id: str, source_revision: str) -> None:
    """Mirror the delivered snapshot only if the original visit is still current."""
    current_env = check_environment()
    path = state_file(chat_id, current_env)
    with state_lock(path):
        current = read_state(chat_id, current_env)
        if current is None or current.run_id != run_id:
            return
        if revision(current) != source_revision:
            raise DomainError("Содержимое сданной проверки изменилось")
        _write_atomic(path, _read_raw(state_file(chat_id, env)))


def report_path(chat_id: int, env: Settings) -> Path:
    path = chat_dir(chat_id, env) / "delivery.json"
    return Path(_read_raw(path)["report"])


def validate(chat_id: int, env: Settings) -> None:
    """Fail closed on changed run, edition or snapshot; never fall back to current data."""
    root = chat_dir(chat_id, env)
    raw = _read_raw(root / "delivery.json")
    inspection = read_state(chat_id, env)
    if (
        raw.get("version") != 1
        or inspection is None
        or inspection.run_id != raw.get("run_id")
        or inspection.checklist_code != raw.get("checklist_code")
        or revision(inspection) != raw.get("inspection_revision")
        or str(env.data_dir) != raw.get("data_dir")
        or compose(env.data_dir, DATA_FILES) != raw.get("method_version")
        or (
            inspection.checklist_version
            and inspection.checklist_version != raw.get("method_version")
        )
    ):
        raise DomainError("Снимок или издание сданной проверки изменились; повтор отклонён")


def prune_archived() -> None:
    """Release acknowledged local copies after a day, beyond optional delivery work."""
    jobs = check_environment().state_dir / JOBS_DIR
    for path in jobs.glob("*/chat_*/delivery.json"):
        try:
            with state_lock(path):
                raw = _read_raw(path)
                if (
                    raw.get("stage") == "archived"
                    and time.time() - float(raw["archived_at"]) > ARCHIVED_KEEP_SEC
                ):
                    shutil.rmtree(path.parent.parent)
        except (DomainError, OSError, KeyError, ValueError, TypeError):
            logger.exception("Сохранённая сдача не очищена; ожидающие задания не затронуты")
