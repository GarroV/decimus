"""Уведомления электронного плана исправлений — только внутри приложения (#1168, D604, D614).

Событие плана пишется на курсоре самого перехода (`notifications.notify`): откатился
переход — откатилось и уведомление. Ни писем, ни Telegram: сообщение человеку по
«да» владельца на текст, адресатов и условие, а его нет (§7 глобальных правил).

Кому (спека «Уведомления»):

| Событие | Кому |
|---|---|
| запрос плана | партнёр страны |
| план отправлен на согласование | девелопер страны |
| план принят / возвращён | партнёр |
| строка отмечена сделанной | девелопер |
| строка подтверждена / возвращена | партнёр |

«Девелопер страны» — пока имя строкой в карточке страны, а не учётка (выбор
девелопера-учётки — следующий шаг): уведомление получают админы УК. Актёр сам себя
не уведомляет. Текст не хранится — по виду его берёт экран (`texts_notifications.py`).
"""

from __future__ import annotations

from typing import Any

import psycopg

from src.domain.tenants import HQ_TENANT

from .notifications import notify, user_by_login, users_with_role

KIND_REQUESTED = "plan_requested"
KIND_SUBMITTED = "plan_submitted"
KIND_ACCEPTED = "plan_accepted"
KIND_RETURNED = "plan_returned"
KIND_ROW_DONE = "plan_row_done"
KIND_ROW_CONFIRMED = "plan_row_confirmed"
KIND_ROW_RETURNED = "plan_row_returned"

#: Виды, адресованные партнёру страны; остальные — УК (админам, пока нет девелопера-учётки).
_FOR_PARTNER = frozenset(
    {KIND_REQUESTED, KIND_ACCEPTED, KIND_RETURNED, KIND_ROW_CONFIRMED, KIND_ROW_RETURNED}
)
#: Роли УК, которым уходит «девелоперское» уведомление, пока девелопер не выбран в карточке страны.
_HQ_RECIPIENT_ROLES = ("admin", "superadmin")

# Какая страна и пиццерия у запроса — для адресатов и текста. Запись события идёт из
# двери, которая запрос уже прочла по охвату; наружу уходит только название точки.
_CONTEXT_SQL = """
select u.country, u.name
from action_plan_requests r
join inspections i on i.id = r.inspection_id
join units u on u.id = i.unit_id
where r.id = %s
"""

_PARTNERS_SQL = """
select w.id::text
from web_users w
join space_countries s on s.tenant_code = w.tenant_code
where s.country = %s and w.disabled_at is null
order by w.login
"""


def plan_link(request_id: str, row_id: str | None = None) -> str:
    """Адрес внутри приложения: панель запроса в «Действиях», при `row_id` — с этой строкой."""
    base = f"/actions?tab=plans&id={request_id}"
    return f"{base}&row={row_id}" if row_id else base


def notify_event(
    cur: psycopg.Cursor[Any],
    kind: str,
    request_id: str,
    *,
    actor: str,
    actor_tenant: str,
    row_id: str | None = None,
) -> int:
    """Положить уведомление о событии плана адресатам вида. Возвращает число строк.

    Страны у точки нет (запрос завести без неё нельзя, но пиццерию могли перенести) —
    партнёру адресовать некому, уведомление не пишется: событие уже в истории плана.
    """
    cur.execute(_CONTEXT_SQL, (request_id,))
    context = cur.fetchone()
    if context is None:
        return 0
    country, unit = context
    if kind in _FOR_PARTNER:
        if not country:
            return 0
        cur.execute(_PARTNERS_SQL, (country,))
        recipients = [str(r[0]) for r in cur.fetchall()]
    else:
        recipients = [
            u for role in _HQ_RECIPIENT_ROLES for u in users_with_role(cur, role, tenant=HQ_TENANT)
        ]
    self_key = user_by_login(cur, actor, tenant=actor_tenant)
    return notify(
        cur,
        [u for u in recipients if u != self_key],
        kind,
        plan_link(request_id, row_id),
        {"unit": str(unit), "by": actor},
    )
