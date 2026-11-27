"""Retry acknowledged report archives from durable snapshots without chat messages."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from src import db
from src.domain import completion
from src.domain.errors import DomainError
from src.report import snapshot_text

logger = logging.getLogger(__name__)


async def retry_once() -> None:
    """Each failed run remains durable; database and storage writes are idempotent."""
    await asyncio.to_thread(completion.prune_archived)
    for chat_id, env, photos in await asyncio.to_thread(completion.pending):
        try:
            inspection_id = await asyncio.to_thread(
                db.push_inspection, chat_id, source_settings=env
            )

            def fetch(ref: str, saved: dict[str, str] = photos) -> bytes | None:
                return Path(saved[ref]).read_bytes() if ref in saved else None

            await asyncio.to_thread(
                db.upload_photos,
                inspection_id,
                fetch=fetch,
                allow_missing=True,
            )
            report = completion.report_path(chat_id, env)
            await asyncio.to_thread(db.upload_report, inspection_id, data=report.read_bytes())
            await asyncio.to_thread(snapshot_text.archive, chat_id, env, inspection_id)
            await asyncio.to_thread(completion.mark, chat_id, env, "archived")
        except (db.DbError, DomainError, OSError):
            logger.exception("Сдача из сохранённого снимка не записана; будет повторена")
