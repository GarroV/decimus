"""Переключатель пространств (D726, `0122`): функция базы, что пишет `acting_tenant` — уровень базы.

Ядро прав. Заслон стоит в самой функции, а не только в коде: пробитое приложение не должно
подставить чужое пространство ни обычной сессии, ни сессии без второй ступени, ни закрытой.
Проверяется ЗАПУСКОМ, а не чтением миграции. Учётки заводит владелец схемы, живёт админка под
ролью приложения — как на площадке.
"""

from __future__ import annotations

import pytest
from conftest import requires_db
from db_harness import завести_пространства

psycopg = pytest.importorskip("psycopg")

from src.db.web_access import (  # noqa: E402
    close_session,
    create_account,
    open_session,
    resolve_session,
    session_fingerprint,
    set_acting_tenant,
)

pytestmark = requires_db

ПАРОЛЬ = "длинный-пароль-учётки-1"


@pytest.fixture
def обе_роли(pg_dsn: str, db_env: str, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("DATABASE_ADMIN_URL", pg_dsn)
    завести_пространства(pg_dsn, "TEST")
    return pg_dsn


def _сессия(login: str, *, tenant: str, role: str, **kw: bool) -> str:
    учётка = create_account(login, tenant=tenant, password=ПАРОЛЬ, role=role)
    return open_session(учётка, **kw).token


def _acting(pg_dsn: str, token: str) -> str | None:
    with psycopg.connect(pg_dsn) as conn:
        row = conn.execute(
            "select acting_tenant from web_sessions where fingerprint = %s",
            (session_fingerprint(token),),
        ).fetchone()
    assert row is not None
    return row[0]


def test_главный_админ_переключается_и_возвращается(обе_роли: str) -> None:
    token = _сессия("boss", tenant="HQ", role="superadmin")

    assert set_acting_tenant(token, "TEST") is True
    вид = resolve_session(token)
    assert вид is not None
    assert вид.acting_tenant == "TEST"
    assert вид.tenant == "HQ", "строка учётки не тронута"
    assert вид.role == "superadmin"

    assert set_acting_tenant(token, None) is True
    assert resolve_session(token).acting_tenant is None  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("tenant", "role"), [("HQ", "admin"), ("HQ", "developer"), ("HQ", "guest"), ("TEST", "admin")]
)
def test_прочим_базa_отказывает(обе_роли: str, tenant: str, role: str) -> None:
    token = _сессия("someone", tenant=tenant, role=role)

    assert set_acting_tenant(token, "TEST") is False
    assert _acting(обе_роли, token) is None


def test_незаведённое_пространство_отказ(обе_роли: str) -> None:
    token = _сессия("boss", tenant="HQ", role="superadmin")

    assert set_acting_tenant(token, "NOPE") is False
    assert _acting(обе_роли, token) is None


def test_закрытая_сессия_не_переключается(обе_роли: str) -> None:
    token = _сессия("boss", tenant="HQ", role="superadmin")
    close_session(token)

    assert set_acting_tenant(token, "TEST") is False


def test_чужой_токен_не_переключает_чужую_сессию(обе_роли: str) -> None:
    token = _сессия("boss", tenant="HQ", role="superadmin")

    assert set_acting_tenant("токен-которого-нет", "TEST") is False
    assert _acting(обе_роли, token) is None


def test_со_вторым_способом_нужна_сессия_после_второй_ступени(обе_роли: str) -> None:
    учётка = create_account("boss", tenant="HQ", password=ПАРОЛЬ, role="superadmin")
    with psycopg.connect(обе_роли) as conn:
        conn.execute(
            "insert into web_totp (user_id, secret, confirmed_at) "
            "values (%s, repeat('A', 32), now())",
            (учётка.id,),
        )
    без_ступени = open_session(учётка, step_waived=True).token
    после_ступени = open_session(учётка, second_step=True).token

    assert set_acting_tenant(без_ступени, "TEST") is False
    assert set_acting_tenant(после_ступени, "TEST") is True


def test_приложение_не_пишет_колонку_напрямую(обе_роли: str, db_env: str) -> None:
    """Права на колонку у роли приложения нет: подставить пространство можно только функцией."""
    token = _сессия("boss", tenant="HQ", role="superadmin")

    with psycopg.connect(db_env) as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute(
                "update web_sessions set acting_tenant = 'TEST' where fingerprint = %s",
                (session_fingerprint(token),),
            )


def test_закрытая_сессия_по_прежнему_не_воскресает(обе_роли: str, db_env: str) -> None:
    """Смягчённая проверка новой строки (`0122`) не открыла путь к воскрешению."""
    token = _сессия("boss", tenant="HQ", role="superadmin")
    close_session(token)

    with psycopg.connect(db_env) as conn, conn.cursor() as cur:
        cur.execute(
            "update web_sessions set closed_at = null where fingerprint = %s",
            (session_fingerprint(token),),
        )
        assert cur.rowcount == 0
