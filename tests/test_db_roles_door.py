"""Права роли приезжают вместе с опознанием — и действуют со следующей сверки."""

from __future__ import annotations

import pytest
from conftest import requires_db
from db_harness import завести_пространства

psycopg = pytest.importorskip("psycopg")

from src.db.errors import AccessError  # noqa: E402
from src.db.roles import grants_of, list_roles  # noqa: E402
from src.db.web_access import (  # noqa: E402
    authenticate,
    create_account,
    open_session,
    reassign_role,
    resolve_session,
)
from src.domain.permissions import DEFAULT_MATRIX  # noqa: E402

pytestmark = requires_db
ПАРОЛЬ = "очень-длинный-пароль"


@pytest.fixture
def обе_роли(pg_dsn: str, db_env: str, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("DATABASE_ADMIN_URL", pg_dsn)
    завести_пространства(pg_dsn, "GE")
    return pg_dsn


def test_старая_роль_переводится_на_заведении(обе_роли: str) -> None:
    учётка = create_account("ge-boss", tenant="GE", password=ПАРОЛЬ, role="admin")
    assert учётка.role == "country_admin"


def test_вход_приносит_права_с_охватом_и_имя_роли(обе_роли: str) -> None:
    create_account("hq-staff", tenant="HQ", password=ПАРОЛЬ, role="hq_staff")
    вошёл = authenticate("hq-staff", ПАРОЛЬ)
    assert вошёл is not None
    assert dict(вошёл.grants) == dict(DEFAULT_MATRIX["hq_staff"])
    assert вошёл.grants["inspection.retract"] == "own"
    assert (вошёл.role_name_ru, вошёл.role_name_en) == ("Сотрудник УК", "HQ staff")


def test_снятое_право_действует_со_следующей_сверки_сессии(обе_роли: str) -> None:
    учётка = create_account("hq-boss", tenant="HQ", password=ПАРОЛЬ, role="hq_admin")
    сессия = open_session(учётка)
    with psycopg.connect(обе_роли) as conn:
        conn.execute(
            "delete from role_permissions where role_code = 'hq_admin' "
            "and action_code = 'inspection.retract'"
        )
    после = resolve_session(сессия.token)
    assert после is not None and "inspection.retract" not in после.grants


def test_роль_чужого_охвата_названа(обе_роли: str) -> None:
    with pytest.raises(AccessError, match="не для пространства «GE»"):
        create_account("ge-intruder", tenant="GE", password=ПАРОЛЬ, role="hq_admin")


def test_незаведённая_роль_названа(обе_роли: str) -> None:
    create_account("ge-worker", tenant="GE", password=ПАРОЛЬ)
    with pytest.raises(AccessError, match="«ghost» не заведена"):
        reassign_role("ge-worker", tenant="GE", role="ghost")


def test_перечень_ролей_и_права_роли(обе_роли: str) -> None:
    assert {р.code: р.scope for р in list_roles()} == {
        "hq_admin": "hq",
        "hq_staff": "hq",
        "country_admin": "country",
        "country_staff": "country",
    }
    assert dict(grants_of("country_staff")) == dict(DEFAULT_MATRIX["country_staff"])
    assert dict(grants_of("ghost")) == {}
