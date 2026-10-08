"""Токены сервисов для API чтения `/api/v1` (#567, #568, D336).

Устроено как личные токены MCP (`src/db/mcp_access.py`, миграция `0011`):
в базе только отпечаток SHA-256, значение показывается один раз при выпуске,
отзыв — пометка со следом. Почему SHA-256 без соли, а не медленная функция, —
сказано в заголовке `mcp_access`: 256 случайных бит не перебираются, а соль
отняла бы поиск по индексу.

Отличие — права (`scopes`): токен открывает ровно перечисленные маршруты.

Роли разделены (миграция `0041`): роль приложения только сверяет токен и
отмечает использование; выпускает и отзывает роль повышенных полномочий
(`managing_dsn` — та же, что заводит учётки админки). Веб-процесс токен себе
не выпустит.
"""

from __future__ import annotations

import re
import secrets
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import psycopg

from .config import check_environment
from .database_target import managing_dsn
from .errors import AccessError
from .mcp_access import token_fingerprint

SCOPE_RATINGS_READ = "ratings:read"
SCOPE_INSPECTIONS_READ = "inspections:read"
#: Допустимые права — те же, что в CHECK миграции `0041`.
SCOPES = (SCOPE_RATINGS_READ, SCOPE_INSPECTIONS_READ)

#: Приставка токена. Не секрет и не защита: по ней сканер секретов (gitleaks,
#: поиск по журналам) узнаёт токен Децимуса, случайно попавший не туда.
TOKEN_PREFIX = "dcm_"  # noqa: S105 — приставка формы, не секрет
TOKEN_BYTES = 32

#: Форма предъявленного токена. Всё, что не похоже на выпущенный, отбрасывается
#: до похода в базу — и не уходит дальше ни в отпечаток, ни в журнал.
TOKEN_SHAPE = re.compile(r"dcm_[A-Za-z0-9_-]{43}")

_CONSUMER = re.compile(r"[a-z][a-z0-9_-]{1,39}")

_RESOLVE_SQL = """
select id, consumer, scopes
from api_tokens
where fingerprint = %s and revoked_at is null
"""

#: Отметка использования — не чаще раза в минуту: запись на каждый запрос
#: превратила бы чтение в поток обновлений одной строки.
_TOUCH_SQL = """
update api_tokens set last_used_at = now()
where id = %s and revoked_at is null
  and (last_used_at is null or last_used_at < now() - interval '1 minute')
"""

_INSERT_SQL = """
insert into api_tokens (consumer, scopes, fingerprint, issued_by)
values (%(consumer)s, %(scopes)s, %(fingerprint)s, %(by)s)
returning id
"""

_LIST_SQL = """
select id, consumer, scopes, issued_by, issued_at, revoked_at, revoked_by, last_used_at
from api_tokens
order by (revoked_at is not null), issued_at, id
"""

_REVOKE_SQL = """
update api_tokens set revoked_at = now(), revoked_by = %(by)s
where id = %(id)s and revoked_at is null
"""


@dataclass(frozen=True)
class IssuedApiToken:
    """Выпущенный токен — единственное место, где есть его значение.

    `repr=False`: `repr` структуры попадает в трейсбек, трейсбек — в журнал.
    """

    id: str
    value: str = field(repr=False)
    consumer: str
    scopes: tuple[str, ...]


@dataclass(frozen=True)
class ApiConsumer:
    """Чей предъявленный токен и что ему можно. Значения токена здесь нет."""

    token_id: str
    consumer: str
    scopes: frozenset[str]


@dataclass(frozen=True)
class ApiTokenRow:
    id: str
    consumer: str
    scopes: tuple[str, ...]
    issued_by: str
    issued_at: datetime
    revoked_at: datetime | None
    revoked_by: str | None
    last_used_at: datetime | None


def new_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(TOKEN_BYTES)


def checked_consumer(consumer: str) -> str:
    имя = consumer.strip()
    if not _CONSUMER.fullmatch(имя):
        raise AccessError(
            "Имя потребителя — латиница в нижнем регистре, цифры, «-» и «_», "
            "2–40 знаков, начинается с буквы (например, swarm)"
        )
    return имя


def checked_scopes(scopes: Sequence[str]) -> tuple[str, ...]:
    набор = tuple(dict.fromkeys(s.strip() for s in scopes if s.strip()))
    if not набор:
        raise AccessError(f"Токен без прав не выпускается: назовите права из {', '.join(SCOPES)}")
    чужие = [s for s in набор if s not in SCOPES]
    if чужие:
        raise AccessError(f"Неизвестные права: {', '.join(чужие)}. Допустимы: {', '.join(SCOPES)}")
    return набор


def _checked_actor(actor: str) -> str:
    имя = actor.strip()
    if not 1 <= len(имя) <= 120:
        raise AccessError("Назовите, кто выпускает или отзывает токен: 1–120 знаков")
    return имя


@contextmanager
def _app(зачем: str) -> Iterator[psycopg.Connection[Any]]:
    """Роль приложения. Наружу — тип ошибки драйвера, не текст (в нём бывает DSN)."""
    try:
        with psycopg.connect(check_environment().dsn) as conn:
            yield conn
    except psycopg.Error as exc:
        raise AccessError(f"Не удалось {зачем} ({type(exc).__name__})") from exc


@contextmanager
def _managing(зачем: str) -> Iterator[psycopg.Connection[Any]]:
    """Роль повышенных полномочий — та же, что у учёток (`web_access._managing`)."""
    _, dsn = managing_dsn(зачем)
    try:
        with psycopg.connect(dsn) as conn:
            yield conn
    except psycopg.Error as exc:
        raise AccessError(f"Не удалось {зачем} ({type(exc).__name__})") from exc


def resolve(token: str) -> ApiConsumer | None:
    """Предъявленный токен → потребитель с правами. Незнакомый или отозванный — `None`.

    Отозванный не «находится и отклоняется», а не находится вовсе: ветки
    «нашли, но отозван» нет, и ответ наружу у них один (401). Отказ базы —
    `AccessError`, а не `None`: «не смогли посмотреть» не выдаётся за «чужой».
    """
    if not TOKEN_SHAPE.fullmatch(token):
        return None
    with _app("сверить токен API") as conn, conn.cursor() as cur:
        cur.execute(_RESOLVE_SQL, (token_fingerprint(token),))
        row = cur.fetchone()
        if row is None:
            return None
        cur.execute(_TOUCH_SQL, (row[0],))
    return ApiConsumer(token_id=str(row[0]), consumer=str(row[1]), scopes=frozenset(row[2]))


def issue(consumer: str, *, scopes: Sequence[str], by: str) -> IssuedApiToken:
    """Выпустить токен. Значение возвращается здесь и больше нигде не хранится."""
    имя, права, кто = checked_consumer(consumer), checked_scopes(scopes), _checked_actor(by)
    token = new_token()
    with _managing("выпустить токен API") as conn, conn.cursor() as cur:
        cur.execute(
            _INSERT_SQL,
            {
                "consumer": имя,
                "scopes": list(права),
                "fingerprint": token_fingerprint(token),
                "by": кто,
            },
        )
        row = cur.fetchone()
        if row is None:
            raise AccessError("База не вернула строку после выпуска токена API")
    return IssuedApiToken(id=str(row[0]), value=token, consumer=имя, scopes=права)


def list_tokens() -> tuple[ApiTokenRow, ...]:
    """Все токены со следом, без значений и без отпечатков."""
    with _managing("перечислить токены API") as conn, conn.cursor() as cur:
        cur.execute(_LIST_SQL)
        rows = cur.fetchall()
    return tuple(
        ApiTokenRow(
            id=str(r[0]),
            consumer=str(r[1]),
            scopes=tuple(r[2]),
            issued_by=str(r[3]),
            issued_at=r[4],
            revoked_at=r[5],
            revoked_by=r[6],
            last_used_at=r[7],
        )
        for r in rows
    )


def revoke(token_id: str, *, by: str) -> bool:
    """Отозвать токен по id. Ложь — живого токена с таким id нет (отзыв идемпотентен)."""
    кто = _checked_actor(by)
    try:
        ident = str(uuid.UUID(token_id.strip()))
    except ValueError as exc:
        raise AccessError("id токена — uuid из вывода `list`") from exc
    with _managing("отозвать токен API") as conn, conn.cursor() as cur:
        cur.execute(_REVOKE_SQL, {"id": ident, "by": кто})
        return cur.rowcount > 0
