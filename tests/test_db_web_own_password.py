"""#324: человек меняет СВОЙ пароль с экрана — уровень базы.

Писать хеш здесь будет роль приложения, а у неё на `web_users` по-прежнему
только чтение. Право уходит в функцию базы (`change_own_password`, миграция
`0032`): она находит учётку по ЖИВОЙ СЕССИИ, токен которой ей принесли, и
меняет хеш только этой строки. Пробитое приложение по-прежнему не перепишет
пароль человеку, чьей сессии у него в руках нет.

Каждое свойство проверяется запуском, а не чтением миграции.
"""

from __future__ import annotations

import pytest
from conftest import requires_db

psycopg = pytest.importorskip("psycopg")

from src.db.errors import AccessError  # noqa: E402
from src.db.web_access import (  # noqa: E402
    MIN_PASSWORD_LENGTH,
    authenticate,
    change_own_password,
    create_account,
    disable_account,
    open_session,
    password_hash,
    resolve_session,
)

pytestmark = requires_db

ТЕНАНТ = "HQ"
ПАРОЛЬ = "верный-пароль-учётки"
НОВЫЙ = "новый-пароль-учётки-длиннее"


@pytest.fixture
def обе_роли(pg_dsn: str, db_env: str, monkeypatch: pytest.MonkeyPatch) -> str:
    """Учётки заводит владелец, а смена своего пароля идёт ролью приложения."""
    monkeypatch.setenv("DATABASE_ADMIN_URL", pg_dsn)
    return pg_dsn


def test_верный_текущий_меняет_пароль(обе_роли: str) -> None:
    учётка = create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    сессия = open_session(учётка)

    assert change_own_password(сессия.token, current=ПАРОЛЬ, new=НОВЫЙ) is True

    assert authenticate("director", НОВЫЙ) is not None
    assert authenticate("director", ПАРОЛЬ) is None


def test_неверный_текущий_не_меняет_ничего(обе_роли: str) -> None:
    """Без текущего пароля чужая открытая вкладка забирала бы учётку навсегда."""
    учётка = create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    сессия = open_session(учётка)

    assert change_own_password(сессия.token, current="не-тот-пароль-вовсе", new=НОВЫЙ) is False

    assert authenticate("director", ПАРОЛЬ) is not None
    assert authenticate("director", НОВЫЙ) is None
    assert resolve_session(сессия.token) is not None


def test_остальные_сессии_закрыты_а_своя_жива(обе_роли: str) -> None:
    """Смена — реакция на «меня взломали»: вошедший по старому вылетает, сам человек — нет."""
    учётка = create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    своя = open_session(учётка)
    чужая = open_session(учётка)

    assert change_own_password(своя.token, current=ПАРОЛЬ, new=НОВЫЙ) is True

    assert resolve_session(своя.token) is not None
    assert resolve_session(чужая.token) is None


def test_сессии_соседа_не_трогаются(обе_роли: str) -> None:
    учётка = create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    сосед = create_account("petr", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    своя = open_session(учётка)
    соседская = open_session(сосед)

    change_own_password(своя.token, current=ПАРОЛЬ, new=НОВЫЙ)

    assert resolve_session(соседская.token) is not None
    assert authenticate("petr", ПАРОЛЬ) is not None


def test_короткий_новый_отвергается_до_записи(обе_роли: str) -> None:
    учётка = create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    сессия = open_session(учётка)

    with pytest.raises(AccessError):
        change_own_password(сессия.token, current=ПАРОЛЬ, new="к" * (MIN_PASSWORD_LENGTH - 1))

    assert authenticate("director", ПАРОЛЬ) is not None


def test_закрытая_сессия_пароль_не_меняет(обе_роли: str) -> None:
    учётка = create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    сессия = open_session(учётка)
    change_own_password(open_session(учётка).token, current=ПАРОЛЬ, new=НОВЫЙ)
    assert resolve_session(сессия.token) is None

    assert change_own_password(сессия.token, current=НОВЫЙ, new=ПАРОЛЬ + "-третий") is False


def test_отключённая_учётка_пароль_не_меняет(обе_роли: str) -> None:
    учётка = create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    сессия = open_session(учётка)
    disable_account("director", tenant=ТЕНАНТ)

    assert change_own_password(сессия.token, current=ПАРОЛЬ, new=НОВЫЙ) is False


def test_функция_базы_меняет_только_строку_своей_сессии(обе_роли: str, db_env: str) -> None:
    """Роль приложения, зовущая функцию напрямую, не дотягивается до чужой строки.

    Отпечатки сессий роли приложения видны, токены — нет. Функция берёт ТОКЕН и
    сама считает отпечаток: отпечаток соседа, поданный как токен, не опознаёт
    никого.
    """
    учётка = create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    сосед = create_account("petr", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    open_session(учётка)
    open_session(сосед)
    with psycopg.connect(обе_роли) as conn, conn.cursor() as cur:
        cur.execute(
            "select s.fingerprint, u.password_hash from web_sessions s "
            "join web_users u on u.id = s.user_id where u.login = 'petr'"
        )
        (отпечаток_соседа, хеш_соседа) = cur.fetchone()  # type: ignore[misc]

    with psycopg.connect(db_env) as conn, conn.cursor() as cur:
        cur.execute(
            "select change_own_password(%s, %s, %s)",
            (отпечаток_соседа, хеш_соседа, password_hash("подменённый-пароль")),
        )
        (вышло,) = cur.fetchone()  # type: ignore[misc]
        conn.commit()

    assert вышло is False
    assert authenticate("petr", ПАРОЛЬ) is not None


def test_функция_сверяет_прежний_хеш(обе_роли: str, db_env: str) -> None:
    """Между сверкой текущего пароля и записью пароль сменили — запись не проходит."""
    учётка = create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    сессия = open_session(учётка)

    with psycopg.connect(db_env) as conn, conn.cursor() as cur:
        cur.execute(
            "select change_own_password(%s, %s, %s)",
            (сессия.token, password_hash(ПАРОЛЬ), password_hash(НОВЫЙ)),
        )
        (вышло,) = cur.fetchone()  # type: ignore[misc]
        conn.commit()

    assert вышло is False
    assert authenticate("director", ПАРОЛЬ) is not None


def test_роль_приложения_прямой_записи_хеша_не_получила(обе_роли: str) -> None:
    with psycopg.connect(обе_роли) as conn, conn.cursor() as cur:
        cur.execute(
            "select has_column_privilege('dodo_audit_app', 'web_users', 'password_hash', 'update')"
        )
        (может,) = cur.fetchone()  # type: ignore[misc]

    assert может is False


def test_функцию_зовёт_только_приложение(обе_роли: str) -> None:
    """Выполнение не роздано всем: `public` его не имеет, администратор истории — тоже."""
    with psycopg.connect(обе_роли) as conn, conn.cursor() as cur:
        cur.execute(
            "select has_function_privilege(r, 'change_own_password(text, text, text)', 'execute') "
            "from unnest(array['dodo_audit_app', 'dodo_audit_admin']) as r"
        )
        права = [строка[0] for строка in cur.fetchall()]
        cur.execute(
            "select coalesce(bool_or(acl::text like '=X/%%'), false) from pg_proc, "
            "unnest(proacl) acl where proname = 'change_own_password'"
        )
        (у_всех,) = cur.fetchone()  # type: ignore[misc]

    assert права == [True, False]
    assert у_всех is False
