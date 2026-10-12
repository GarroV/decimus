"""Хранилище OAuth: клиенты, коды, подключения и токены (D417, миграция `0051`).

Claude подключается к MCP входом через сайт: веб-админка выдаёт коды и токены
(`src/web/oauth.py`), сервер MCP их сверяет (`src/mcp/config.py`). Блоки
`src.web` и `src.mcp` — пиры и друг друга не импортируют, общее место у них
одно — здесь, ярусом ниже (так же живут личные токены MCP, `mcp_access.py`).

**Значения кодов и токенов не хранятся** — только SHA-256, как у сессий и
личных токенов MCP: секрет — 256 случайных бит, соль к нему не прибавляет
стойкости, а поиск обязан быть одним обращением по индексу.

**Права здесь не решаются.** Сверка access-токена возвращает учётку, её
пространство и роль, прочитанные из `web_users` в том же запросе: отключённая
учётка не находится вовсе, а смена роли видна на следующем же вызове. Что роли
открыто в MCP, решает `src/mcp/policy.py`.

Чистые правила (адрес возврата, PKCE) лежат здесь же, а не в вебе: их
спрашивают и регистрация клиента, и выдача кода, и обмен, и расходиться им
нельзя.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import psycopg

from src.domain.public_urls import OAUTH_SCOPE

from .config import check_environment
from .errors import AccessError, OAuthGrantError

#: Сколько живёт код авторизации (спека D417): на «Разрешить» и обмен хватает.
CODE_TTL = timedelta(minutes=10)

#: Сколько живёт access-токен. Час: отзыв и отключение учётки действуют и так
#: сразу (сверка на каждом вызове), а короткий срок сужает окно украденного.
ACCESS_TTL = timedelta(hours=1)

#: Сколько живёт refresh-токен. Ротируется при каждом обмене.
REFRESH_TTL = timedelta(days=30)

#: Отметка «последний вызов» пишется не чаще раза в это время на подключение:
#: точнее минуты человеку на карточке не нужно, а запись на каждый вызов MCP
#: была бы лишней нагрузкой.
LAST_USED_STEP = timedelta(minutes=1)

#: Байт случайности в кодах и токенах — как у сессий и личных токенов MCP.
SECRET_BYTES = 32

#: Байт случайности в `client_id`: идентификатор, а не секрет.
CLIENT_ID_BYTES = 24

#: Единственная область доступа: весь MCP decimus в пределах роли.
SCOPE = OAUTH_SCOPE

#: Длина отпечатка SHA-256 шестнадцатеричной записью (схема `0051` требует её же).
FINGERPRINT_LENGTH = 64

#: Адреса возврата Claude (спека D417, «Безопасность»): веб и Desktop/телефон
#: через claude.ai или claude.com, Claude Code — петля с любым портом. Всё
#: остальное — отказ, и отказ без редиректа: увести код на чужой адрес нельзя.
_CLAUDE_CALLBACKS = frozenset(
    {
        "https://claude.ai/api/mcp/auth_callback",
        "https://claude.com/api/mcp/auth_callback",
    }
)
_LOOPBACK_CALLBACK = re.compile(r"^http://(localhost|127\.0\.0\.1):([0-9]{1,5})/callback$")
_MAX_PORT = 65535

#: `code_challenge` метода S256: base64url без выравнивания от 32 байт.
_CHALLENGE = re.compile(r"^[A-Za-z0-9_-]{43}$")

#: `code_verifier` по RFC 7636 §4.1: 43–128 знаков из безопасного алфавита.
_VERIFIER = re.compile(r"^[A-Za-z0-9._~-]{43,128}$")

#: Имя клиента при регистрации без имени.
DEFAULT_CLIENT_NAME = "MCP client"
MAX_CLIENT_NAME = 200
MAX_REDIRECT_URIS = 10


# --- чистые правила ---------------------------------------------------------


def redirect_uri_allowed(uri: object) -> bool:
    """Адрес возврата — один из адресов Claude. Порт петли — любой годный."""
    if not isinstance(uri, str):
        return False
    if uri in _CLAUDE_CALLBACKS:
        return True
    петля = _LOOPBACK_CALLBACK.match(uri)
    return петля is not None and 0 < int(петля.group(2)) <= _MAX_PORT


def is_loopback(uri: str) -> bool:
    """Возврат на машину человека (Claude Code): странице согласия — предупреждение."""
    return _LOOPBACK_CALLBACK.match(uri) is not None


def challenge_valid(challenge: object) -> bool:
    """`code_challenge` по форме годится для S256."""
    return isinstance(challenge, str) and _CHALLENGE.match(challenge) is not None


def pkce_matches(verifier: object, challenge: str) -> bool:
    """PKCE S256: base64url(SHA-256(verifier)) == challenge. Метода `plain` нет."""
    if not isinstance(verifier, str) or _VERIFIER.match(verifier) is None:
        return False
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    ожидание = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return hmac.compare_digest(ожидание, challenge)


def fingerprint(secret: str) -> str:
    """Отпечаток кода или токена — то единственное, что от него остаётся в базе."""
    отпечаток = hashlib.sha256(secret.encode("utf-8")).hexdigest()
    if len(отпечаток) != FINGERPRINT_LENGTH:
        raise AccessError(f"отпечаток вышел длиной {len(отпечаток)} вместо {FINGERPRINT_LENGTH}")
    return отпечаток


def new_secret() -> str:
    """Новый код или токен: непрозрачный, только из безопасного для адреса алфавита."""
    return secrets.token_urlsafe(SECRET_BYTES)


def clean_client_name(name: object) -> str:
    """Имя клиента для страницы согласия: строка, без управляющих знаков, не длиннее предела."""
    if not isinstance(name, str):
        return DEFAULT_CLIENT_NAME
    чистое = "".join(знак for знак in name if знак.isprintable()).strip()
    return чистое[:MAX_CLIENT_NAME] or DEFAULT_CLIENT_NAME


# --- структуры --------------------------------------------------------------


@dataclass(frozen=True)
class Client:
    """Зарегистрированный клиент: что показать на согласии и куда можно вернуть."""

    id: int
    client_id: str
    client_name: str
    redirect_uris: tuple[str, ...]


@dataclass(frozen=True)
class TokenPair:
    """Выпущенная пара — единственное место, где значения токенов вообще есть."""

    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    expires_in: int


@dataclass(frozen=True)
class OAuthOwner:
    """Кто стоит за access-токеном: учётка сайта, её пространство и роль — свежие."""

    user_id: str
    login: str
    tenant: str
    role: str


@dataclass(frozen=True)
class Connection:
    """Живое подключение на своей карточке: какой клиент, когда подключён, последний вызов."""

    id: str
    client_name: str
    created_at: datetime
    last_used_at: datetime | None


# --- запросы ----------------------------------------------------------------

_INSERT_CLIENT_SQL = """
insert into oauth_clients (client_id, client_name, redirect_uris)
values (%s, %s, %s)
returning id
"""

_COUNT_RECENT_CLIENTS_SQL = "select count(*) from oauth_clients where created_at > now() - %s"

_SELECT_CLIENT_SQL = """
select id, client_id, client_name, redirect_uris from oauth_clients where client_id = %s
"""

_INSERT_CODE_SQL = """
insert into oauth_codes
    (fingerprint, client_id, user_id, redirect_uri, code_challenge, scope, resource, expires_at)
values (%s, %s, %s, %s, %s, %s, %s, now() + %s)
"""

#: Код целиком, под замком строки: два одновременных обмена одного кода не
#: выпустят двух подключений — второй дождётся первого и увидит `used_at`.
_LOCK_CODE_SQL = """
select k.id, c.client_id, k.redirect_uri, k.code_challenge, k.used_at,
       k.grant_id, k.expires_at > now(), u.disabled_at is null
  from oauth_codes k
  join oauth_clients c on c.id = k.client_id
  join web_users u on u.id = k.user_id
 where k.fingerprint = %s
   for update of k
"""

_INSERT_GRANT_SQL = """
insert into oauth_grants (user_id, client_id)
select k.user_id, k.client_id from oauth_codes k where k.id = %s
returning id
"""

_USE_CODE_SQL = "update oauth_codes set used_at = now(), grant_id = %s where id = %s"

_INSERT_ISSUED_SQL = """
insert into oauth_tokens (grant_id, kind, fingerprint, expires_at)
values (%s, %s, %s, now() + %s)
"""

#: Отзыв подключения при повторе обменянного кода или refresh (RFC 6749 §4.1.2,
#: OAuth 2.1 §4.3.1): предъявивший второй раз — либо вор, либо жертва кражи.
_REVOKE_REUSED_SQL = """
update oauth_grants set revoked_at = now(), revoked_reason = 'reuse'
 where id = %s and revoked_at is null
"""

_LOCK_REFRESH_SQL = """
select t.id, t.grant_id, c.client_id, t.used_at, t.expires_at > now(),
       g.revoked_at is null, u.disabled_at is null
  from oauth_tokens t
  join oauth_grants g on g.id = t.grant_id
  join oauth_clients c on c.id = g.client_id
  join web_users u on u.id = g.user_id
 where t.fingerprint = %s and t.kind = 'refresh'
   for update of t
"""

_USE_REFRESH_SQL = "update oauth_tokens set used_at = now() where id = %s"

#: Сверка access-токена: только живой токен живого подключения живой учётки.
#: Отозванное и отключённое не «находится и отклоняется», а не находится вовсе.
_RESOLVE_ACCESS_SQL = """
select u.id, u.login, u.tenant_code, u.role, g.id,
       g.last_used_at is null or g.last_used_at < now() - %s
  from oauth_tokens t
  join oauth_grants g on g.id = t.grant_id
  join web_users u on u.id = g.user_id
 where t.fingerprint = %s
   and t.kind = 'access'
   and t.expires_at > now()
   and g.revoked_at is null
   and u.disabled_at is null
"""

_TOUCH_GRANT_SQL = "update oauth_grants set last_used_at = now() where id = %s"

#: Живые подключения человека: не отозваны и есть неиспользованный живой refresh.
_LIST_CONNECTIONS_SQL = """
select g.id, c.client_name, g.created_at, g.last_used_at
  from oauth_grants g
  join oauth_clients c on c.id = g.client_id
 where g.user_id = %s
   and g.revoked_at is null
   and exists (select 1 from oauth_tokens t
                where t.grant_id = g.id and t.kind = 'refresh'
                  and t.used_at is null and t.expires_at > now())
 order by g.created_at desc
"""

#: Отзыв своим владельцем: `user_id` в условии — чужое подключение не найдётся.
_REVOKE_OWN_SQL = """
update oauth_grants set revoked_at = now(), revoked_reason = 'user'
 where id = %s and user_id = %s and revoked_at is null
"""


@contextmanager
def _connected(зачем: str) -> Iterator[psycopg.Connection[Any]]:
    """Подключение роли приложения. Отказ базы — `AccessError` с типом, без текста драйвера."""
    settings = check_environment()
    try:
        with psycopg.connect(settings.dsn) as conn:
            yield conn
    except psycopg.Error as exc:
        raise AccessError(f"Не удалось {зачем} ({type(exc).__name__})") from exc


def _invalid_grant(описание: str) -> OAuthGrantError:
    return OAuthGrantError("invalid_grant", описание)


# --- клиенты ----------------------------------------------------------------


def register_client(name: object, redirect_uris: Sequence[str]) -> Client:
    """Завести клиента (RFC 7591). Адреса возврата уже проверены вызывающим — и здесь снова."""
    if not 0 < len(redirect_uris) <= MAX_REDIRECT_URIS or not all(
        redirect_uri_allowed(uri) for uri in redirect_uris
    ):
        raise OAuthGrantError("invalid_redirect_uri", "Адрес возврата не из разрешённых")
    client_id = secrets.token_urlsafe(CLIENT_ID_BYTES)
    имя = clean_client_name(name)
    with _connected("завести OAuth-клиента") as conn, conn.cursor() as cur:
        cur.execute(_INSERT_CLIENT_SQL, (client_id, имя, list(redirect_uris)))
        row = cur.fetchone()
    if row is None:
        raise AccessError("Не удалось завести OAuth-клиента (insert без строки)")
    return Client(
        id=int(row[0]), client_id=client_id, client_name=имя, redirect_uris=tuple(redirect_uris)
    )


def recent_clients(window: timedelta) -> int:
    """Сколько клиентов заведено за окно — для общего предела регистраций."""
    with _connected("сосчитать OAuth-клиентов") as conn, conn.cursor() as cur:
        cur.execute(_COUNT_RECENT_CLIENTS_SQL, (window,))
        row = cur.fetchone()
    return 0 if row is None else int(row[0])


def find_client(client_id: str) -> Client | None:
    """Клиент по `client_id` или `None`, если такого не заводили."""
    with _connected("найти OAuth-клиента") as conn, conn.cursor() as cur:
        cur.execute(_SELECT_CLIENT_SQL, (client_id,))
        row = cur.fetchone()
    if row is None:
        return None
    return Client(
        id=int(row[0]),
        client_id=str(row[1]),
        client_name=str(row[2]),
        redirect_uris=tuple(str(u) for u in row[3]),
    )


# --- код авторизации --------------------------------------------------------


def issue_code(
    client: Client,
    *,
    user_id: str,
    redirect_uri: str,
    code_challenge: str,
    resource: str | None,
) -> str:
    """Выдать код после «Разрешить». Значение возвращается один раз — в редирект."""
    if redirect_uri not in client.redirect_uris or not redirect_uri_allowed(redirect_uri):
        raise OAuthGrantError("invalid_request", "Адрес возврата не зарегистрирован у клиента")
    if not challenge_valid(code_challenge):
        raise OAuthGrantError("invalid_request", "code_challenge не годится для S256")
    код = new_secret()
    with _connected("выдать код авторизации") as conn, conn.cursor() as cur:
        cur.execute(
            _INSERT_CODE_SQL,
            (
                fingerprint(код),
                client.id,
                user_id,
                redirect_uri,
                code_challenge,
                SCOPE,
                resource,
                CODE_TTL,
            ),
        )
    return код


def _issue_pair(cur: Any, grant_id: str) -> TokenPair:
    access, refresh = new_secret(), new_secret()
    cur.execute(_INSERT_ISSUED_SQL, (grant_id, "access", fingerprint(access), ACCESS_TTL))
    cur.execute(_INSERT_ISSUED_SQL, (grant_id, "refresh", fingerprint(refresh), REFRESH_TTL))
    return TokenPair(
        access_token=access,
        refresh_token=refresh,
        expires_in=int(ACCESS_TTL.total_seconds()),
    )


@dataclass(frozen=True)
class CodeState:
    """Строка кода так, как её видит решение об обмене."""

    client_id: str
    redirect_uri: str
    code_challenge: str
    used: bool
    alive: bool
    account_alive: bool


@dataclass(frozen=True)
class RefreshState:
    """Строка refresh-токена так, как её видит решение об обновлении."""

    client_id: str
    used: bool
    alive: bool
    grant_alive: bool
    account_alive: bool


@dataclass(frozen=True)
class Judgement:
    """Решение об обмене: отказ (или `None` — выпускать) и отзывать ли подключение."""

    refusal: str | None
    revoke: bool = False


def judge_code(
    state: CodeState | None, *, client_id: str, redirect_uri: str, verifier: str
) -> Judgement:
    """Можно ли обменять код. Чистая функция: правила обмена отдельно от SQL.

    Порядок важен. Повтор проверяется ПЕРВЫМ и отзывает подключение, кто бы ни
    предъявил: настоящий клиент код второй раз не шлёт (RFC 6749 §4.1.2). Неудача
    по прочим причинам код не сжигает — иначе чужой мог бы испортить код
    человека, угадав только его значение.
    """
    if state is None:
        return Judgement("Код авторизации не опознан")
    if state.used:
        return Judgement("Код авторизации уже обменян; подключение отозвано", revoke=True)
    if state.client_id != client_id:
        return Judgement("Код выдан другому клиенту")
    if not state.alive:
        return Judgement("Срок кода авторизации истёк")
    if state.redirect_uri != redirect_uri:
        return Judgement("redirect_uri не совпадает с адресом из запроса кода")
    if not pkce_matches(verifier, state.code_challenge):
        return Judgement("code_verifier не подходит к code_challenge")
    if not state.account_alive:
        return Judgement("Учётка отключена")
    return Judgement(None)


def judge_refresh(state: RefreshState | None, *, client_id: str) -> Judgement:
    """Можно ли обновить пару по refresh. Чистая функция, как `judge_code`.

    Повтор уже обменянного refresh отзывает подключение: настоящий клиент
    держит только последний, и второй предъявитель — признак кражи.
    """
    if state is None:
        return Judgement("Refresh-токен не опознан")
    if state.client_id != client_id:
        return Judgement("Refresh-токен выдан другому клиенту")
    if not state.grant_alive:
        return Judgement("Подключение отозвано")
    if state.used:
        return Judgement("Refresh-токен уже обменян; подключение отозвано", revoke=True)
    if not state.alive:
        return Judgement("Срок refresh-токена истёк")
    if not state.account_alive:
        return Judgement("Учётка отключена")
    return Judgement(None)


def exchange_code(code: str, *, client_id: str, redirect_uri: str, verifier: str) -> TokenPair:
    """Код + PKCE → первая пара токенов и новое подключение. Иначе `OAuthGrantError`.

    Решает `judge_code`, здесь — только чтение под замком и запись. Отзыв при
    повторе фиксируется в базе до отказа: отказ поднимается после выхода из
    транзакции, иначе он откатил бы и сам отзыв.
    """
    решение = Judgement("Код авторизации не опознан")
    пара: TokenPair | None = None
    with _connected("обменять код авторизации") as conn, conn.cursor() as cur:
        cur.execute(_LOCK_CODE_SQL, (fingerprint(code),))
        row = cur.fetchone()
        состояние = (
            None
            if row is None
            else CodeState(
                client_id=str(row[1]),
                redirect_uri=str(row[2]),
                code_challenge=str(row[3]),
                used=row[4] is not None,
                alive=bool(row[6]),
                account_alive=bool(row[7]),
            )
        )
        решение = judge_code(
            состояние, client_id=client_id, redirect_uri=redirect_uri, verifier=verifier
        )
        if row is not None and решение.revoke:
            cur.execute(_REVOKE_REUSED_SQL, (row[5],))
        if row is not None and решение.refusal is None:
            cur.execute(_INSERT_GRANT_SQL, (row[0],))
            grant = cur.fetchone()
            if grant is None:
                raise AccessError("Не удалось завести подключение (insert без строки)")
            grant_id = str(grant[0])
            cur.execute(_USE_CODE_SQL, (grant_id, row[0]))
            пара = _issue_pair(cur, grant_id)
    if решение.refusal is not None:
        raise _invalid_grant(решение.refusal)
    if пара is None:
        raise AccessError("Обмен кода не выпустил токенов")
    return пара


def refresh_tokens(refresh_token: str, *, client_id: str) -> TokenPair:
    """Refresh → новая пара; старый refresh больше не действует (ротация).

    Решает `judge_refresh`; отзыв при повторе фиксируется до отказа, как у кода.
    """
    решение = Judgement("Refresh-токен не опознан")
    пара: TokenPair | None = None
    with _connected("обновить токен доступа") as conn, conn.cursor() as cur:
        cur.execute(_LOCK_REFRESH_SQL, (fingerprint(refresh_token),))
        row = cur.fetchone()
        состояние = (
            None
            if row is None
            else RefreshState(
                client_id=str(row[2]),
                used=row[3] is not None,
                alive=bool(row[4]),
                grant_alive=bool(row[5]),
                account_alive=bool(row[6]),
            )
        )
        решение = judge_refresh(состояние, client_id=client_id)
        if row is not None and решение.revoke:
            cur.execute(_REVOKE_REUSED_SQL, (row[1],))
        if row is not None and решение.refusal is None:
            cur.execute(_USE_REFRESH_SQL, (row[0],))
            пара = _issue_pair(cur, str(row[1]))
    if решение.refusal is not None:
        raise _invalid_grant(решение.refusal)
    if пара is None:
        raise AccessError("Обновление не выпустило токенов")
    return пара


# --- сверка и подключения ---------------------------------------------------


def resolve_access_token(token: str) -> OAuthOwner | None:
    """Access-токен → учётка, пространство, роль. Незнакомый, истёкший, отозванный — `None`.

    Спрашивается сервером MCP на каждый вызов. Отказ базы — `AccessError`, а не
    `None`: «не смогли посмотреть» не выдаётся за «токен незнакомый».
    """
    with _connected("сверить OAuth-токен") as conn, conn.cursor() as cur:
        cur.execute(_RESOLVE_ACCESS_SQL, (LAST_USED_STEP, fingerprint(token)))
        row = cur.fetchone()
        if row is None:
            return None
        if row[5]:
            cur.execute(_TOUCH_GRANT_SQL, (row[4],))
    return OAuthOwner(user_id=str(row[0]), login=str(row[1]), tenant=str(row[2]), role=str(row[3]))


def list_connections(user_id: str) -> tuple[Connection, ...]:
    """Живые подключения Claude этой учётки — для её карточки."""
    with _connected("прочитать подключения Claude") as conn, conn.cursor() as cur:
        cur.execute(_LIST_CONNECTIONS_SQL, (user_id,))
        rows = cur.fetchall()
    return tuple(
        Connection(id=str(r[0]), client_name=str(r[1]), created_at=r[2], last_used_at=r[3])
        for r in rows
    )


def revoke_connection(connection_id: str, *, user_id: str) -> bool:
    """Отозвать своё подключение. `False` — живого своего с таким номером нет.

    Номер чужого подключения не найдётся: `user_id` стоит в условии запроса, а
    не проверяется после. Кривой номер — тоже `False`, а не отказ базы.
    """
    try:
        номер = str(uuid.UUID(connection_id))
    except ValueError:
        return False
    with _connected("отозвать подключение Claude") as conn, conn.cursor() as cur:
        cur.execute(_REVOKE_OWN_SQL, (номер, user_id))
        return cur.rowcount > 0
