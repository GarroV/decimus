"""Сервисные токены внешнего API и журнал обращений (D356, D388, #568).

Первый потребитель — API чтения для Swarm (`src/web/swarm_api.py`, #567, D387).
Раньше его токен лежал в окружении веба открытым текстом: один, без прав, без
отзыва и без следа. Теперь, как у личных токенов MCP (`mcp_access`):

- **значение токена не хранится** — только SHA-256 (миграция `0049`); почему
  SHA-256 без соли, а не медленная функция, сказано в заголовке `mcp_access`;
- **права** — закрытый перечень (`SCOPES`), маршрут пускает только токен с
  нужным правом;
- **отзыв** — пометкой со следом, строка остаётся;
- **журнал** — каждое обращение, включая отказы; по нему же считается лимит
  частоты на токен.

Сверка и журнал идут ролью приложения; выдача и отзыв — ролью администратора
истории (`managing_dsn`, та же, что заводит учётки): получив базу продукта,
чужой не выдаст себе доступ.

Отказ базы уходит наружу `AccessError`, а не «токен незнакомый»: «не смогли
посмотреть» и «такого нет» — разные ответы, и подменять одно другим значит
молча закрыть доступ всем с неверным объяснением.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import psycopg

from .config import check_environment
from .database_target import managing_dsn
from .errors import AccessError
from .mcp_access import new_token, token_fingerprint

SCOPE_RATINGS_READ = "ratings:read"
SCOPE_INSPECTIONS_READ = "inspections:read"
#: Закрытый перечень прав. Тот же список держит ограничение схемы (`0049`).
SCOPES = (SCOPE_RATINGS_READ, SCOPE_INSPECTIONS_READ)

#: Сколько хранится журнал. Старше — удаляется попутно с записью.
LOG_RETENTION = timedelta(days=90)
#: Сколько старых строк удаляется за одну запись: чистка не должна тормозить ответ.
LOG_PURGE_BATCH = 100

_RESOLVE_SQL = """
select id, consumer, scopes from api.tokens
where fingerprint = %s and revoked_at is null
"""

_RECENT_SQL = """
select count(*) from api.access_log where token_id = %s and at > now() - %s::interval
"""

_LOG_SQL = """
insert into api.access_log (token_id, path, status, client) values (%s, %s, %s, %s)
"""

_PURGE_SQL = """
delete from api.access_log
where id in (select id from api.access_log where at < now() - %s::interval limit %s)
"""

_ISSUE_SQL = """
insert into api.tokens (consumer, fingerprint, scopes, issued_by)
values (%s, %s, %s, %s)
returning id
"""

_REVOKE_SQL = """
update api.tokens set revoked_at = now(), revoked_by = %s
where id = %s and revoked_at is null
"""

_LIST_SQL = """
select id, consumer, scopes, issued_at, issued_by, revoked_at, revoked_by
from api.tokens order by id
"""


@dataclass(frozen=True)
class ApiToken:
    """Опознанный живой токен: чей и что ему можно."""

    id: int
    consumer: str
    scopes: tuple[str, ...]

    def allows(self, scope: str) -> bool:
        return scope in self.scopes


@dataclass(frozen=True)
class IssuedApiToken:
    """Только что выпущенный токен. `value` существует ровно здесь и один раз."""

    id: int
    consumer: str
    scopes: tuple[str, ...]
    value: str


@dataclass(frozen=True)
class TokenRow:
    """Строка перечня токенов — без отпечатка: он никому не нужен на экране."""

    id: int
    consumer: str
    scopes: tuple[str, ...]
    issued_at: datetime
    issued_by: str
    revoked_at: datetime | None
    revoked_by: str | None


@contextmanager
def _connected(зачем: str) -> Iterator[psycopg.Connection[Any]]:
    """Роль приложения; наружу — тип исключения драйвера, а не его текст (DSN)."""
    settings = check_environment()
    try:
        with psycopg.connect(settings.dsn) as conn:
            yield conn
    except psycopg.Error as exc:
        raise AccessError(f"Не удалось {зачем} ({type(exc).__name__})") from exc


@contextmanager
def _managing(зачем: str) -> Iterator[psycopg.Connection[Any]]:
    """Роль администратора истории (а без неё — владельца схемы), как у учёток."""
    _, dsn = managing_dsn(зачем)
    try:
        with psycopg.connect(dsn) as conn:
            yield conn
    except psycopg.Error as exc:
        raise AccessError(f"Не удалось {зачем} ({type(exc).__name__})") from exc


def _scopes(raw: Any) -> tuple[str, ...]:
    return tuple(str(s) for s in raw or ())


def resolve(token: str) -> ApiToken | None:
    """Предъявленный токен → живой токен с правами. Незнакомый или отозванный — `None`."""
    with _connected("сверить токен API") as conn, conn.cursor() as cur:
        cur.execute(_RESOLVE_SQL, (token_fingerprint(token),))
        row = cur.fetchone()
    if row is None:
        return None
    return ApiToken(id=int(row[0]), consumer=str(row[1]), scopes=_scopes(row[2]))


def recent_requests(token_id: int, window: timedelta) -> int:
    """Сколько обращений этим токеном записано в журнал за последнее окно."""
    with _connected("посчитать обращения к API") as conn, conn.cursor() as cur:
        cur.execute(_RECENT_SQL, (token_id, window))
        row = cur.fetchone()
    return int(row[0]) if row else 0


def log_access(token_id: int | None, path: str, status: int, client: str | None) -> None:
    """Записать обращение и попутно удалить пачку строк старше срока хранения."""
    with _connected("записать обращение к API") as conn, conn.cursor() as cur:
        cur.execute(_LOG_SQL, (token_id, path, status, client))
        cur.execute(_PURGE_SQL, (LOG_RETENTION, LOG_PURGE_BATCH))


def _checked_scopes(scopes: tuple[str, ...]) -> tuple[str, ...]:
    if not scopes:
        raise AccessError("Токен без прав не выпускается: назовите хотя бы одно право")
    чужие = [s for s in scopes if s not in SCOPES]
    if чужие:
        raise AccessError(f"Неизвестные права: {', '.join(чужие)}. Бывают: {', '.join(SCOPES)}")
    return tuple(dict.fromkeys(scopes))


def issue(consumer: str, scopes: tuple[str, ...], *, by: str) -> IssuedApiToken:
    """Выпустить токен. Значение возвращается один раз — в базе только отпечаток."""
    права = _checked_scopes(scopes)
    token = new_token()
    with _managing("выпустить токен API") as conn, conn.cursor() as cur:
        cur.execute(_ISSUE_SQL, (consumer, token_fingerprint(token), list(права), by))
        row = cur.fetchone()
        if row is None:
            raise AccessError("База не вернула строку после выпуска токена API")
    return IssuedApiToken(id=int(row[0]), consumer=consumer, scopes=права, value=token)


def revoke(token_id: int, *, by: str) -> bool:
    """Отозвать токен. `False` — живого токена с таким номером нет."""
    with _managing("отозвать токен API") as conn, conn.cursor() as cur:
        cur.execute(_REVOKE_SQL, (by, token_id))
        return cur.rowcount > 0


def list_tokens() -> list[TokenRow]:
    """Все токены, включая отозванные: след выдачи и отзыва."""
    with _managing("перечислить токены API") as conn, conn.cursor() as cur:
        cur.execute(_LIST_SQL)
        rows = cur.fetchall()
    return [
        TokenRow(
            id=int(r[0]),
            consumer=str(r[1]),
            scopes=_scopes(r[2]),
            issued_at=r[3],
            issued_by=str(r[4]),
            revoked_at=r[5],
            revoked_by=None if r[6] is None else str(r[6]),
        )
        for r in rows
    ]
