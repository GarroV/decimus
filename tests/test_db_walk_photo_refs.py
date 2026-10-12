"""F-033: уборка брошенных кадров мини-аппа не снимает кадр сданной проверки.

Сданная проверка уходит в базу, а её папка в состоянии бота потом очищается.
Кадр мини-аппа, ещё не легший в хранилище, читается из `STATE_DIR/uploads/`, и
единственный, кто помнит о нём после сдачи, — строка `photos` в базе. Здесь
проверяется весь путь на настоящей базе: сдали — папку чата убрали — уборка
кадр не тронула, а брошенный рядом убрала.
"""

from __future__ import annotations

import io
import os
import shutil
import time
from pathlib import Path

import pytest
from conftest import requires_db
from PIL import Image

pytest.importorskip("psycopg")

from src.bot import upload_sweeper
from src.db.photos import walk_photo_refs
from src.db.push import push_inspection
from src.domain import add_finding, check_environment, start_inspection
from src.domain.engine import chat_dir
from src.domain.upload_sweep import UNATTACHED_TTL_SEC
from src.domain.uploads import save_upload, upload_file

pytestmark = requires_db

ЧАТ = 4242


def _jpeg(цвет: tuple[int, int, int]) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (16, 16), цвет).save(buffer, format="JPEG")
    return buffer.getvalue()


def _состарить(path: Path) -> None:
    давно = time.time() - UNATTACHED_TTL_SEC - 60
    os.utime(path, (давно, давно))


def test_кадр_сданной_проверки_уборка_не_трогает(domain_env: Path, db_env: str) -> None:
    settings = check_environment()
    сданный = save_upload(_jpeg((10, 20, 30)), settings, owner=ЧАТ)
    брошенный = save_upload(_jpeg((40, 50, 60)), settings, owner=ЧАТ)
    start_inspection(ЧАТ, unit="Белград-1", kind="planned", report_lang="ru")
    add_finding(ЧАТ, code="CLN05", level="D1", zone="hot_kitchen", text="нагар", photos=[сданный])
    push_inspection(ЧАТ)
    shutil.rmtree(chat_dir(ЧАТ, settings))  # после сдачи папка чата очищена
    for ref in (сданный, брошенный):
        _состарить(upload_file(ref, settings))  # type: ignore[arg-type]

    assert сданный in walk_photo_refs()
    итог = upload_sweeper.sweep_once()

    assert итог is not None and итог.frames == 1
    assert upload_file(сданный, settings) is not None, "кадр сданной проверки цел"
    assert upload_file(брошенный, settings) is None, "брошенный убран"
