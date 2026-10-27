"""Где проверка чата лежит в истории и ждёт ли она приёмки (напоминание боту, 27.10.2026).

Читающий вызов, без записи: слив (`push.push_inspection`) на повтор тоже не
плодит строк, но на ПЕРВЫЙ вызов пишет, а повторная отправка отчёта
(`bot.routers.resend`) в историю писать не должна никогда. Поэтому проверка
ищется по тем же отпечаткам, что у слива (`fingerprint`), только без вставки.
"""

from __future__ import annotations

from dataclasses import dataclass

import psycopg

from src.domain import get_state
from src.domain import score as domain_score
from src.domain.errors import DomainError

from .config import check_environment
from .errors import DbError
from .fingerprint import compute_fingerprint, previous_fingerprints
from .pool import connection
from .push import _tenant_code

_SELECT_SQL = """
select id, status, retracted_at is not null
from inspections
where source_fingerprint = any(%s)
limit 1
"""

_DRAFT = "draft"


@dataclass(frozen=True)
class PushedInspection:
    """Строка истории: идентификатор и то, ждёт ли она приёмки."""

    id: str
    #: На приёмке (`draft`) и не снята. Принятая и снятая — `False`.
    awaiting_acceptance: bool


def find_pushed(chat_id: int) -> PushedInspection | None:
    """Проверка чата в истории; `None` — в истории её нет.

    Нет базы в окружении — `ConfigError`, сбой запроса или нечитаемая проверка —
    `DbError`: молчаливое «нет» не отличило бы ненастроенную базу от проверки,
    которая не слилась.
    """
    settings = check_environment()
    try:
        inspection = get_state(chat_id)
        if inspection is None:
            return None
        tenant = _tenant_code(inspection)
        result = domain_score(chat_id)
        prints = [
            compute_fingerprint(inspection, result, tenant_code=tenant),
            *previous_fingerprints(inspection, result, tenant_code=tenant),
        ]
        with connection(settings.dsn) as conn, conn.cursor() as cur:
            cur.execute(_SELECT_SQL, (prints,))
            row = cur.fetchone()
    except (psycopg.Error, DomainError) as exc:
        raise DbError(
            f"Проверка чата {chat_id} в истории не прочитана ({type(exc).__name__})"
        ) from exc
    if row is None:
        return None
    return PushedInspection(id=str(row[0]), awaiting_acceptance=row[1] == _DRAFT and not row[2])
