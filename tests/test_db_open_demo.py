"""Посев открытого демо (D524) на чистой базе: сеть, кадры, приёмка, учётки ролей."""

from __future__ import annotations

import io
import os
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import requires_db
from db_harness import admin_role_dsn

psycopg = pytest.importorskip("psycopg")

from src.db.spaces import create_space, list_spaces, space_exists  # noqa: E402
from src.domain.demo import DEMO_ROLES  # noqa: E402

pytestmark = requires_db

КОРЕНЬ = Path(__file__).resolve().parent.parent


def _кадры(каталог: Path) -> Path:
    """Плашки вместо белградских снимков: те лежат вне репозитория."""
    from PIL import Image

    каталог.mkdir()
    for имя in ("p09.jpg", "p10.jpg", "q35.jpg"):
        buf = io.BytesIO()
        Image.new("RGB", (64, 48), (200, 180, 160)).save(buf, format="JPEG")
        (каталог / имя).write_bytes(buf.getvalue())
    return каталог


def test_посев_открытого_демо(
    pg_dsn: str, db_env: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    monkeypatch.setenv("DATABASE_ADMIN_URL", pg_dsn)
    if not space_exists("HQ"):
        create_space("HQ", name="УК")
    env = {
        **os.environ,
        "DATABASE_ADMIN_URL": pg_dsn,
        "DATABASE_URL": db_env,
        "DATABASE_RETRACTION_URL": admin_role_dsn(db_env),
        "SEED_WEB_DEMO_FORCE": "1",
        "DEMO_STATE_DIR": str(tmp_path / "state"),
        "DEMO_PHOTOS_DIR": str(_кадры(tmp_path / "photos")),
    }

    # Act
    посев = subprocess.run(  # noqa: S603 — аргументы наши, оболочки нет
        [sys.executable, str(КОРЕНЬ / "tools" / "seed_open_demo.py")],
        capture_output=True,
        text=True,
        env={**env, "S3_ENDPOINT_URL": "", "S3_BUCKET": ""},
        check=False,
        timeout=600,
    )

    # Assert
    assert посев.returncode == 0, посев.stderr[-3000:]
    демо = next(s for s in list_spaces() if s.code == "demo")
    assert демо.countries == ("AM", "GE", "RS")
    with psycopg.connect(pg_dsn) as conn:
        статусы = dict(
            conn.execute("select status, count(*) from inspections group by status").fetchall()
        )
        кадров = conn.execute("select count(*) from photos").fetchone()
        логины = {r[0] for r in conn.execute("select login from web_users").fetchall()}
        планов = conn.execute("select count(*) from action_plan_requests").fetchone()
        поездок = conn.execute(
            "select count(*), count(distinct date_trunc('month', date_from)) from trips"
        ).fetchone()
        шагов = conn.execute("select count(*) from trip_steps where kind = 'inspection'").fetchone()
        русских = conn.execute(
            "select count(*) from translations where entity_type = 'finding' and lang = 'ru'"
        ).fetchone()
    assert статусы.get("draft") == 2 and статусы.get("finalized", 0) >= 15, статусы
    # Хранилища в тесте нет: кадры — строками без ссылки, как при лежащем (#459).
    assert кадров is not None and кадров[0] > 0, "кадры из DEMO_PHOTOS_DIR не легли к записям"
    assert {r.login for r in DEMO_ROLES} <= логины
    assert планов is not None and планов[0] > 0, "D2 на приёмке не породили планов"
    assert поездок is not None and поездок[0] >= 10 and поездок[1] >= 5, (
        "в календаре демо должны быть поездки по нескольким месяцам"
    )
    assert шагов is not None and шагов[0] == поездок[0], "у каждой поездки — осмотр точки"
    assert русских is not None and русских[0] == 2, "прошлые записи точки обхода — по-русски"
    assert "chats 999000000701 (WEB_WALK_PREVIEW_CHAT) and 999000000702" in посев.stdout, (
        "русская идущая проверка не заведена"
    )
