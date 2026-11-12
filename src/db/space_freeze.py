"""Заморозка всего пространства партнёра одной кнопкой (D759, миграция `0132`).

Заморозка пространства — это заморозка каждой его действующей учётки ТЕМ ЖЕ
механизмом, что одиночная (`web_access.freeze_account`): отметка `disabled_at` и
триггеры `0059`/`0063`, которые закрывают сессии, подключения Claude, токены MCP и бота.
Сверх того пространство получает свою отметку (когда и кем), а замороженные этой
кнопкой учётки — `space_frozen_at`: разморозка возвращает ровно их, а замороженных
раньше по одной не трогает. Всё делают функции базы в одной транзакции; УК не
замораживается. Пока пространство заморожено, сторож на таблице учёток не даёт в нём
завести учётку или снять заморозку с отдельной (`web_users_frozen_space_guard`).

Роль — та же узкая, что у учёток и пространств (`web_access._managing`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import psycopg

from src.domain.tenants import HQ_TENANT, canonical_tenant

from .errors import AccessError, EmailTakenError
from .web_access import _managing

_FREEZE_SQL = "select freeze_space(%s, %s)"
_UNFREEZE_SQL = "select unfreeze_space(%s)"
_INFO_SQL = """
    select t.code, t.frozen_at, f.login,
           (select count(*) from web_users u
             where u.tenant_code = t.code and u.space_frozen_at is not null
               and u.disabled_at is not null)
      from tenants t
      left join web_users f on f.id = t.frozen_by
     where t.frozen_at is not null
"""


@dataclass(frozen=True)
class FrozenSpace:
    """Замороженное пространство: когда, кем (логин; `None` — не известно) и сколько учёток."""

    code: str
    frozen_at: datetime
    by: str | None
    accounts: int


def _partner_code(space: str) -> str:
    код = canonical_tenant(space)
    if код == HQ_TENANT:
        raise AccessError("Пространство УК не замораживается")
    return код


def freeze_space(space: str, *, by: str | None) -> int:
    """Заморозить пространство партнёра; вернуть число замороженных учёток.

    `0` — пространство уже заморожено, ничего не сделано. УК и незаведённое
    пространство — `AccessError`.
    """
    код = _partner_code(space)
    with _managing(f"заморозить пространство «{код}»") as conn, conn.cursor() as cur:
        cur.execute(_FREEZE_SQL, (код, by))
        строка = cur.fetchone()
    return int(строка[0]) if строка else 0


def unfreeze_space(space: str) -> int:
    """Снять заморозку пространства; вернуть число возвращённых учёток.

    Возвращаются только учётки, замороженные кнопкой пространства. Почту одной из них
    за время заморозки могли отдать живой учётке — тогда `EmailTakenError`, и ничего
    не меняется (двух живых учёток на одну почту не бывает, `0075`).
    """
    код = _partner_code(space)
    try:
        with _managing(f"разморозить пространство «{код}»") as conn, conn.cursor() as cur:
            cur.execute(_UNFREEZE_SQL, (код,))
            строка = cur.fetchone()
    except AccessError as exc:
        if isinstance(exc.__cause__, psycopg.errors.UniqueViolation):
            raise EmailTakenError(
                "почта одной из учёток за время заморозки привязана к другой живой учётке"
            ) from exc
        raise
    return int(строка[0]) if строка else 0


def frozen_spaces() -> dict[str, FrozenSpace]:
    """Замороженные сейчас пространства по коду — для карточки пространства."""
    with _managing("перечислить замороженные пространства") as conn, conn.cursor() as cur:
        cur.execute(_INFO_SQL)
        строки = cur.fetchall()
    return {
        str(r[0]): FrozenSpace(
            code=str(r[0]),
            frozen_at=r[1],
            by=None if r[2] is None else str(r[2]),
            accounts=int(r[3]),
        )
        for r in строки
    }
