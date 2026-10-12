"""Хранилище OAuth (D417, `src/db/oauth_store.py`) — уровень базы.

Ядро: ошибка здесь тихая — код меняется дважды, украденный refresh работает,
отключённая учётка продолжает ходить в MCP. Проверяется запуском на настоящей
базе под ролью приложения (`db_env`): так же, как ходят веб и сервер MCP, —
заодно это проверка, что выданных `0051` прав хватает.
"""

from __future__ import annotations

import base64
import hashlib
from datetime import timedelta

import pytest
from conftest import requires_db
from db_harness import завести_пространства

psycopg = pytest.importorskip("psycopg")

from src.db.errors import OAuthGrantError  # noqa: E402
from src.db.oauth_store import (  # noqa: E402
    Client,
    exchange_code,
    issue_code,
    list_connections,
    purge_stale,
    recent_clients,
    refresh_tokens,
    register_client,
    resolve_access_token,
    revoke_connection,
)
from src.db.web_access import (  # noqa: E402
    ROLE_ADMIN,
    authenticate,
    change_own_password,
    change_password,
    create_account,
    disable_account,
    open_session,
    set_role,
)

pytestmark = requires_db

ТЕНАНТ = "HQ"
ВОЗВРАТ = "https://claude.ai/api/mcp/auth_callback"
АДРЕС = "203.0.113.5"
РЕСУРС = "https://mcp.example/mcp"
VERIFIER = "x" * 64
CHALLENGE = (
    base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).rstrip(b"=").decode()
)


@pytest.fixture
def база(pg_dsn: str, db_env: str, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("DATABASE_ADMIN_URL", pg_dsn)
    завести_пространства(pg_dsn, ТЕНАНТ, "rs")
    return pg_dsn


@pytest.fixture
def учётка(база: str) -> str:
    return create_account("anna", tenant=ТЕНАНТ, password="пароль-учётки-anna").id


@pytest.fixture
def клиент(база: str) -> Client:
    return register_client("Claude", [ВОЗВРАТ], address=АДРЕС)


def _код(клиент: Client, учётка: str) -> str:
    return issue_code(
        клиент, user_id=учётка, redirect_uri=ВОЗВРАТ, code_challenge=CHALLENGE, resource=РЕСУРС
    )


def _обмен(код: str, клиент: Client, **иное: str):  # type: ignore[no-untyped-def]
    параметры = {"client_id": клиент.client_id, "redirect_uri": ВОЗВРАТ, "verifier": VERIFIER}
    параметры.update(иное)
    return exchange_code(код, **параметры)


def test_полный_путь_код_токен_сверка(клиент: Client, учётка: str) -> None:
    пара = _обмен(_код(клиент, учётка), клиент)

    кто = resolve_access_token(пара.access_token, resource=РЕСУРС)
    assert кто is not None
    assert (кто.login, кто.tenant, кто.role) == ("anna", ТЕНАНТ, "auditor")
    assert resolve_access_token(пара.refresh_token, resource=РЕСУРС) is None, (
        "refresh не годится как access"
    )


def test_в_базе_нет_значений(база: str, клиент: Client, учётка: str) -> None:
    код = _код(клиент, учётка)
    пара = _обмен(код, клиент)

    with psycopg.connect(база) as conn, conn.cursor() as cur:
        cur.execute("select string_agg(fingerprint, ',') from oauth_tokens")
        (токены,) = cur.fetchone()  # type: ignore[misc]
        cur.execute("select string_agg(fingerprint, ',') from oauth_codes")
        (коды,) = cur.fetchone()  # type: ignore[misc]
    for секрет in (код, пара.access_token, пара.refresh_token):
        assert секрет not in токены and секрет not in коды


def test_код_одноразовый_и_повтор_отзывает_подключение(клиент: Client, учётка: str) -> None:
    код = _код(клиент, учётка)
    пара = _обмен(код, клиент)

    with pytest.raises(OAuthGrantError) as отказ:
        _обмен(код, клиент)

    assert отказ.value.error == "invalid_grant"
    assert resolve_access_token(пара.access_token, resource=РЕСУРС) is None


def test_просроченный_код_отвергается(база: str, клиент: Client, учётка: str) -> None:
    код = _код(клиент, учётка)
    with psycopg.connect(база) as conn:
        conn.execute("update oauth_codes set expires_at = now() - interval '1 second'")

    with pytest.raises(OAuthGrantError, match="Срок"):
        _обмен(код, клиент)


@pytest.mark.parametrize(
    "иное",
    [
        {"verifier": "y" * 64},
        {"verifier": CHALLENGE},
        {"redirect_uri": "http://localhost:9999/callback"},
        {"client_id": "чужой-клиент-1234567"},
    ],
)
def test_обмен_с_чужими_параметрами_отвергается(
    клиент: Client, учётка: str, иное: dict[str, str]
) -> None:
    код = _код(клиент, учётка)

    with pytest.raises(OAuthGrantError) as отказ:
        _обмен(код, клиент, **иное)

    assert отказ.value.error == "invalid_grant"
    assert _обмен(код, клиент).access_token, "неудачный обмен не сжигает код"


def test_код_на_незарегистрированный_адрес_не_выдаётся(клиент: Client, учётка: str) -> None:
    with pytest.raises(OAuthGrantError):
        issue_code(
            клиент,
            user_id=учётка,
            redirect_uri="http://localhost:8080/callback",
            code_challenge=CHALLENGE,
            resource=РЕСУРС,
        )


def test_регистрация_с_чужим_адресом_отвергается(база: str) -> None:
    with pytest.raises(OAuthGrantError):
        register_client("x", ["https://evil.com/cb"], address=АДРЕС)


def test_refresh_ротируется(клиент: Client, учётка: str) -> None:
    первая = _обмен(_код(клиент, учётка), клиент)

    вторая = refresh_tokens(первая.refresh_token, client_id=клиент.client_id)

    assert resolve_access_token(вторая.access_token, resource=РЕСУРС) is not None
    assert вторая.refresh_token != первая.refresh_token


def test_повтор_refresh_отзывает_подключение(клиент: Client, учётка: str) -> None:
    первая = _обмен(_код(клиент, учётка), клиент)
    вторая = refresh_tokens(первая.refresh_token, client_id=клиент.client_id)

    with pytest.raises(OAuthGrantError, match="отозвано"):
        refresh_tokens(первая.refresh_token, client_id=клиент.client_id)

    assert resolve_access_token(вторая.access_token, resource=РЕСУРС) is None
    with pytest.raises(OAuthGrantError):
        refresh_tokens(вторая.refresh_token, client_id=клиент.client_id)
    assert list_connections(учётка) == ()


def test_refresh_чужим_клиентом_отвергается(клиент: Client, учётка: str) -> None:
    пара = _обмен(_код(клиент, учётка), клиент)
    другой = register_client("Другой", [ВОЗВРАТ], address=АДРЕС)

    with pytest.raises(OAuthGrantError):
        refresh_tokens(пара.refresh_token, client_id=другой.client_id)


def test_отключённая_учётка_не_опознаётся(клиент: Client, учётка: str) -> None:
    пара = _обмен(_код(клиент, учётка), клиент)

    disable_account("anna", tenant=ТЕНАНТ)

    assert resolve_access_token(пара.access_token, resource=РЕСУРС) is None
    with pytest.raises(OAuthGrantError):
        refresh_tokens(пара.refresh_token, client_id=клиент.client_id)


def test_роль_читается_свежей(клиент: Client, учётка: str) -> None:
    пара = _обмен(_код(клиент, учётка), клиент)

    set_role("anna", tenant=ТЕНАНТ, role=ROLE_ADMIN)

    кто = resolve_access_token(пара.access_token, resource=РЕСУРС)
    assert кто is not None and кто.role == ROLE_ADMIN


def test_последний_вызов_отмечается(клиент: Client, учётка: str) -> None:
    пара = _обмен(_код(клиент, учётка), клиент)
    assert list_connections(учётка)[0].last_used_at is None

    resolve_access_token(пара.access_token, resource=РЕСУРС)

    assert list_connections(учётка)[0].last_used_at is not None


def test_отзыв_своего_подключения(клиент: Client, учётка: str) -> None:
    пара = _обмен(_код(клиент, учётка), клиент)
    (подключение,) = list_connections(учётка)

    assert revoke_connection(подключение.id, user_id=учётка) is True

    assert resolve_access_token(пара.access_token, resource=РЕСУРС) is None
    assert list_connections(учётка) == ()
    assert revoke_connection(подключение.id, user_id=учётка) is False


def test_чужое_подключение_не_отзывается(клиент: Client, учётка: str) -> None:
    пара = _обмен(_код(клиент, учётка), клиент)
    (подключение,) = list_connections(учётка)
    чужой = create_account("boris", tenant="rs", password="пароль-учётки-boris").id

    assert revoke_connection(подключение.id, user_id=чужой) is False
    assert revoke_connection("не-номер", user_id=учётка) is False

    assert resolve_access_token(пара.access_token, resource=РЕСУРС) is not None


def test_роль_приложения_не_удаляет_подключения(db_env: str, клиент: Client) -> None:
    with psycopg.connect(db_env) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("delete from oauth_grants")


def test_регистрации_считаются_по_адресу(клиент: Client) -> None:
    register_client("Ещё", [ВОЗВРАТ], address="198.51.100.7")

    assert recent_clients(timedelta(hours=1), address=АДРЕС) == 1
    assert recent_clients(timedelta(hours=1), address="198.51.100.7") == 1
    assert recent_clients(timedelta(hours=1)) == 2


def test_чистка_убирает_только_отжившее(база: str, клиент: Client, учётка: str) -> None:
    брошенный = register_client("Брошенный", [ВОЗВРАТ], address=АДРЕС)
    пара = _обмен(_код(клиент, учётка), клиент)
    with psycopg.connect(база) as conn:
        conn.execute("update oauth_clients set created_at = now() - interval '2 days'")
        conn.execute(
            "update oauth_tokens set expires_at = now() - interval '2 days' where kind = 'access'"
        )

    убрано = purge_stale()

    with psycopg.connect(база) as conn:
        клиенты = {r[0] for r in conn.execute("select client_id from oauth_clients")}
        токены = conn.execute("select kind from oauth_tokens").fetchall()
    assert убрано == 2
    assert клиенты == {клиент.client_id}
    assert брошенный.client_id not in клиенты
    assert токены == [("refresh",)]
    assert refresh_tokens(пара.refresh_token, client_id=клиент.client_id) is not None


def test_роль_приложения_не_удаляет_клиентов_напрямую(db_env: str, клиент: Client) -> None:
    with psycopg.connect(db_env) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("delete from oauth_clients")


def test_токен_годен_только_для_своего_ресурса(клиент: Client, учётка: str) -> None:
    пара = _обмен(_код(клиент, учётка), клиент)

    assert resolve_access_token(пара.access_token, resource=РЕСУРС) is not None
    assert resolve_access_token(пара.access_token, resource="https://other.example/mcp") is None


def test_обмен_с_чужим_ресурсом_отвергается(клиент: Client, учётка: str) -> None:
    with pytest.raises(OAuthGrantError) as отказ:
        _обмен(_код(клиент, учётка), клиент, resource="https://other.example/mcp")

    assert отказ.value.error == "invalid_target"


def test_refresh_наследует_ресурс(клиент: Client, учётка: str) -> None:
    первая = _обмен(_код(клиент, учётка), клиент)

    вторая = refresh_tokens(первая.refresh_token, client_id=клиент.client_id, resource=РЕСУРС)

    assert resolve_access_token(вторая.access_token, resource=РЕСУРС) is not None


def test_смена_пароля_командой_отзывает_подключения(клиент: Client, учётка: str) -> None:
    пара = _обмен(_код(клиент, учётка), клиент)

    assert change_password("anna", tenant=ТЕНАНТ, password="новый-пароль-учётки-anna")

    assert resolve_access_token(пара.access_token, resource=РЕСУРС) is None
    with pytest.raises(OAuthGrantError):
        refresh_tokens(пара.refresh_token, client_id=клиент.client_id)


def test_смена_своего_пароля_отзывает_подключения(клиент: Client, учётка: str) -> None:
    пара = _обмен(_код(клиент, учётка), клиент)
    кто = authenticate("anna", "пароль-учётки-anna")
    assert кто is not None
    сессия = open_session(кто)

    assert change_own_password(
        сессия.token, current="пароль-учётки-anna", new="новый-пароль-учётки-anna"
    )

    assert resolve_access_token(пара.access_token, resource=РЕСУРС) is None
    assert list_connections(учётка) == ()
