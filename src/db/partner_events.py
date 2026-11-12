"""События в пространствах партнёров для экрана «Пользователи» (D759, миграция `0132`).

Пишет триггер таблицы учёток: в пространстве партнёра (не УК) учётке выдана роль
админа (заведение или повышение) либо у учётки сменилась почта. Здесь только чтение
непросмотренного и отметка «Видел». Наружу ничего не отправляется: события видны на
экране тем, кто ведёт пространства (главный админ и админ УК), и больше нигде.

Отметка «Видел» своя у каждого: сигнал безопасности не должен пропасть у второго
администратора оттого, что первый его закрыл. Кому показывать, решает вызывающий
(маршрут сверяет охват); база не знает, кто смотрит, кроме его `web_users.id`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .web_access import _managing

#: Сколько непросмотренных событий показывает блок; остальные видны после отметки этих.
SHOWN_LIMIT = 20

KIND_ADMIN_ADDED = "admin_added"
KIND_EMAIL_CHANGED = "email_changed"

_UNSEEN_SQL = """
    select e.id, e.occurred_at, e.tenant_code, e.kind, u.login, u.role, a.login
      from partner_account_events e
      join web_users u on u.id = e.user_id
      left join web_users a on a.id = e.actor_id
     where not exists (select 1 from partner_event_seen s
                        where s.event_id = e.id and s.user_id = %(viewer)s)
     order by e.occurred_at desc, e.id desc
     limit %(limit)s
"""
_COUNT_SQL = """
    select count(*) from partner_account_events e
     where not exists (select 1 from partner_event_seen s
                        where s.event_id = e.id and s.user_id = %(viewer)s)
"""
_SEEN_SQL = """
    insert into partner_event_seen (event_id, user_id)
    select e.id, %(viewer)s from partner_account_events e where e.id = %(event)s
    on conflict do nothing
"""


@dataclass(frozen=True)
class PartnerEvent:
    """Событие: когда, в каком пространстве, что, с какой учёткой и кто сделал."""

    id: int
    occurred_at: datetime
    tenant: str
    kind: str
    login: str
    role: str
    #: Логин сделавшего; `None` — сама учётка или команда с сервера.
    actor: str | None


def unseen(viewer_id: str, *, limit: int = SHOWN_LIMIT) -> tuple[tuple[PartnerEvent, ...], int]:
    """Непросмотренные зрителем события (новые первыми) и их общее число."""
    with _managing("прочитать события пространств партнёров") as conn, conn.cursor() as cur:
        cur.execute(_UNSEEN_SQL, {"viewer": viewer_id, "limit": limit})
        строки = cur.fetchall()
        cur.execute(_COUNT_SQL, {"viewer": viewer_id})
        всего = cur.fetchone()
    события = tuple(
        PartnerEvent(
            id=int(r[0]),
            occurred_at=r[1],
            tenant=str(r[2]),
            kind=str(r[3]),
            login=str(r[4]),
            role=str(r[5]),
            actor=None if r[6] is None else str(r[6]),
        )
        for r in строки
    )
    return события, int(всего[0]) if всего else 0


def mark_seen(viewer_id: str, event_id: int) -> bool:
    """Отметить событие просмотренным этим зрителем. `False` — такого события нет."""
    with _managing("отметить событие просмотренным") as conn, conn.cursor() as cur:
        cur.execute(_SEEN_SQL, {"viewer": viewer_id, "event": event_id})
        return cur.rowcount > 0
