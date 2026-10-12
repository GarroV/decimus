"""Роль «контроль» бывает только в пространстве УК — держат и код, и схема (`0040`)."""

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
    web_access.create_account("aud", tenant="HQ", password=ПАРОЛЬ, role="developer")

    assert web_access.reassign_role("aud", tenant="HQ", role="control") == "developer"
    assert web_access.reassign_role("aud", tenant="HQ", role="developer") == "control"


def test_роли_пространства_контроль_только_в_уК() -> None:
    assert "control" in web_access.roles_for("HQ")
    assert "control" not in web_access.roles_for("GE")


@pytest.mark.parametrize("роль", ["developer", "guest"])
def test_девелопер_и_гость_у_партнёра_отказ_схемой(обе_роли: str, роль: str) -> None:
    """D440 (`0059`): обе роли бывают только в УК — держит схема, а не форма."""
    web_access.create_account("aud", tenant="GE", password=ПАРОЛЬ)

    with psycopg.connect(обе_роли) as conn, pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("update web_users set role = %s where login = 'aud'", (роль,))


def test_аудитора_в_уК_схема_не_даёт(обе_роли: str) -> None:
    """D440 (`0059`): аудитор УК стал девелопером, и новый в УК не заводится."""
    web_access.create_account("dev", tenant="HQ", password=ПАРОЛЬ, role="developer")

    with psycopg.connect(обе_роли) as conn, pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("update web_users set role = 'auditor' where login = 'dev'")


def test_роль_по_умолчанию_самая_узкая() -> None:
    """Без роли: гость в УК (только чтение), сотрудник у партнёра."""
    assert web_access.roles_for("HQ")[0] == "guest"
    assert "auditor" not in web_access.roles_for("HQ")
    assert web_access.roles_for("GE") == ("auditor", "admin")
