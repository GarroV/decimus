"""Переключатель пространств (D726, `0122`, `0123`): функция базы, что пишет `web_session_peeks`.

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


def _id_сессии(pg_dsn: str, token: str) -> str:
    with psycopg.connect(pg_dsn) as conn:
        row = conn.execute(
            "select id from web_sessions where fingerprint = %s", (session_fingerprint(token),)
        ).fetchone()
    assert row is not None
    return str(row[0])


def _acting(pg_dsn: str, token: str) -> str | None:
    with psycopg.connect(pg_dsn) as conn:
        row = conn.execute(
            "select k.tenant_code from web_session_peeks k "
            "join web_sessions s on s.id = k.session_id where s.fingerprint = %s",
            (session_fingerprint(token),),
        ).fetchone()
    return row[0] if row else None


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


def test_приложение_не_пишет_таблицу_переключателя_напрямую(обе_роли: str, db_env: str) -> None:
    """У роли приложения на таблицу только `select`: подставить пространство можно лишь функцией."""
    token = _сессия("boss", tenant="HQ", role="superadmin")
    set_acting_tenant(token, "TEST")
    sid = _id_сессии(обе_роли, token)

    with psycopg.connect(db_env, autocommit=True) as conn:
        for sql, args in (
            ("insert into web_session_peeks (session_id, tenant_code) values (%s, 'HQ')", (sid,)),
            ("update web_session_peeks set tenant_code = 'HQ' where session_id = %s", (sid,)),
            ("delete from web_session_peeks where session_id = %s", (sid,)),
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(sql, args)
        assert conn.execute("select count(*) from web_session_peeks").fetchone()[0] == 1
    assert _acting(обе_роли, token) == "TEST"


def test_приложение_правит_у_сессии_только_закрытие(обе_роли: str, db_env: str) -> None:
    """Колонки сессии, кроме `closed_at`, роли приложения не даны: пространства там больше нет."""
    token = _сессия("boss", tenant="HQ", role="superadmin")

    with psycopg.connect(db_env, autocommit=True) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(
                "update web_sessions set expires_at = now() + interval '1 year' "
                "where fingerprint = %s",
                (session_fingerprint(token),),
            )


def test_заслон_закрытия_строгий_правка_живой_строки_без_закрытия_отказ(
    обе_роли: str, db_env: str
) -> None:
    """Проверка новой строки (`0122` смягчил, `0123` вернул): живая остаётся живой — нельзя.

    Правка единственной колонки, что роли приложения разрешена (`closed_at`), которая оставляет
    живую строку живой, отклоняется политикой `with check (closed_at is not null)`. При
    смягчённой до `true` проверке такая правка проходила бы.
    """
    token = _сессия("boss", tenant="HQ", role="superadmin")

    with psycopg.connect(db_env, autocommit=True) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(
                "update web_sessions set closed_at = null where fingerprint = %s",
                (session_fingerprint(token),),
            )
    assert resolve_session(token) is not None, "сессия осталась как была"


def test_закрытие_сессии_снимает_просмотр_с_действия(обе_роли: str) -> None:
    token = _сессия("boss", tenant="HQ", role="superadmin")
    assert set_acting_tenant(token, "TEST") is True
    assert resolve_session(token) is not None

    close_session(token)

    assert resolve_session(token) is None, "закрытая сессия не опознаётся, а с ней и просмотр"
    assert set_acting_tenant(token, None) is False


def test_удаление_сессии_уносит_строку_просмотра(обе_роли: str) -> None:
    token = _сессия("boss", tenant="HQ", role="superadmin")
    set_acting_tenant(token, "TEST")

    with psycopg.connect(обе_роли, autocommit=True) as conn:
        conn.execute(
            "delete from web_sessions where fingerprint = %s", (session_fingerprint(token),)
        )
        assert conn.execute("select count(*) from web_session_peeks").fetchone()[0] == 0


def test_закрытая_сессия_по_прежнему_не_воскресает(обе_роли: str, db_env: str) -> None:
    token = _сессия("boss", tenant="HQ", role="superadmin")
    close_session(token)

    with psycopg.connect(db_env) as conn, conn.cursor() as cur:
        cur.execute(
            "update web_sessions set closed_at = null where fingerprint = %s",
            (session_fingerprint(token),),
        )
        assert cur.rowcount == 0
