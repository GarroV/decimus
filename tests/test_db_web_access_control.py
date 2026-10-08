"""Роль «контроль» бывает только в пространстве УК — держат и код, и схема (`0039`)."""

from __future__ import annotations

import pytest
from conftest import requires_db
from db_harness import завести_пространства

psycopg = pytest.importorskip("psycopg")

from src.db import web_access  # noqa: E402
from src.db.errors import AccessError  # noqa: E402

pytestmark = requires_db

ПАРОЛЬ = "длинный-пароль-1"


@pytest.fixture
def обе_роли(pg_dsn: str, db_env: str, monkeypatch: pytest.MonkeyPatch) -> str:
    """Заведение учёток идёт ролью владельца схемы (`_managing`), как в `test_db_web_access.py`."""
    monkeypatch.setenv("DATABASE_ADMIN_URL", pg_dsn)
    завести_пространства(pg_dsn, "GE")
    return pg_dsn


def test_контроль_заводится_в_уК(обе_роли: str) -> None:
    учётка = web_access.create_account("ctl", tenant="HQ", password=ПАРОЛЬ, role="control")

    assert учётка.role == "control"


def test_контроль_у_партнёра_отказ_кодом(обе_роли: str) -> None:
    with pytest.raises(AccessError, match="только в пространстве УК"):
        web_access.create_account("ctl", tenant="GE", password=ПАРОЛЬ, role="control")
    web_access.create_account("aud", tenant="GE", password=ПАРОЛЬ)
    with pytest.raises(AccessError, match="только в пространстве УК"):
        web_access.reassign_role("aud", tenant="GE", role="control")


def test_контроль_у_партнёра_отказ_схемой(обе_роли: str) -> None:
    web_access.create_account("aud", tenant="GE", password=ПАРОЛЬ)

    with psycopg.connect(обе_роли) as conn, pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("update web_users set role = 'control' where login = 'aud'")


def test_контроль_в_уК_назначается_и_снимается(обе_роли: str) -> None:
    web_access.create_account("aud", tenant="HQ", password=ПАРОЛЬ)

    assert web_access.reassign_role("aud", tenant="HQ", role="control") == "auditor"
    assert web_access.reassign_role("aud", tenant="HQ", role="auditor") == "control"


def test_роли_пространства_контроль_только_в_уК() -> None:
    assert "control" in web_access.roles_for("HQ")
    assert "control" not in web_access.roles_for("GE")
