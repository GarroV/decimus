"""Перенос проверки по дате и пиццерии — с историей каждой правки (D195).

Переносится шапка, а не документ: записи, оценка, буква и разбивка остаются
теми, что посчитал движок при сдаче. История пишется самой базой — триггером
`inspections_move_logged` (миграция `0025`) на том же `update`, — поэтому
перенести мимо истории нельзя, даже минуя эту функцию. Здесь только причина и
автор, которые триггер берёт из настроек транзакции, и понятные отказы.

Идёт под ролью администратора истории (`DATABASE_RETRACTION_URL`): у неё и
только у неё есть право на две колонки шапки, `unit_id` и `inspection_date`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

import psycopg

from .config import load_retraction_settings
from .directory import live_unit_id
from .errors import MoveError
from .pool import connection
from .queries import _require_inspection_id, _require_tenant
from .reach import Reach, require_reach
from .reading import reading as _reading

_SELECT_HEAD_SQL = """
select status, retracted_at, inspection_date, unit_id
from inspections
where id = %(id)s and tenant_code = %(tenant)s
"""

# Годная точка переноса — та же, что пропускает сторож схемы (миграция 0030):
# точка своего тенанта либо справочника УК из стран пространства (D284). Сверка
# здесь — ради понятного отказа до записи; граница — триггер.
_UNIT_OF_TENANT_SQL = """
select 1 from units u
where u.id = %(unit)s
  and (u.tenant_code = %(tenant)s
       or (u.tenant_code = 'HQ' and exists (
           select 1 from space_countries s
            where s.tenant_code = %(tenant)s and s.country = u.country)))
"""

# Экшн-план привязан к проверке, а партнёр видит запрос и файлы по стране её
# точки (0036, D284). Перенос в точку другой страны отдал бы их партнёру той
# страны, поэтому с планом между странами не переносят (F, GHSA-wqh3). Сверка
# здесь — ради понятного отказа; граница — триггер миграции 0066.
_CROSS_COUNTRY_PLAN_SQL = """
select 1
from units o, units n
where o.id = %(old)s and n.id = %(new)s
  and o.country is distinct from n.country
  and exists (select 1 from action_plan_requests r where r.inspection_id = %(id)s)
"""

_MOVE_SQL = """
update inspections
set inspection_date = %(date)s, unit_id = %(unit)s
where id = %(id)s and tenant_code = %(tenant)s
"""

_LIST_MOVES_SQL = """
select m.moved_at, m.moved_by, m.reason, m.old_date, m.new_date,
       uo.name as old_unit, un.name as new_unit
from inspection_moves m
join inspections i on i.id = m.inspection_id
join units u on u.id = i.unit_id
join units uo on uo.id = m.old_unit_id
join units un on un.id = m.new_unit_id
where m.inspection_id = %(id)s
  and (%(tenants)s::text[] is null or i.tenant_code = any(%(tenants)s))
  and (%(countries)s::text[] is null or u.country = any(%(countries)s))
order by m.moved_at desc, m.id desc
"""


@dataclass(frozen=True)
class MoveRecord:
    """Одна правка шапки: когда, кто, почему, что было и что стало."""

    moved_at: str
    moved_by: str
    reason: str
    old_date: str
    new_date: str
    old_unit: str
    new_unit: str


def _require_text(value: str, *, what: str) -> str:
    записанное = (value or "").strip()
    if not записанное:
        raise MoveError(
            f"Не назван {what} исправления. История исправлений обязательна (D195): без неё "
            f"правка даты или пиццерии неотличима от подчистки",
            code="move_reason_required" if what == "повод" else None,
        )
    return записанное


def move_inspection(
    inspection_id: str,
    *,
    tenant: str,
    new_date: date | None,
    new_unit_id: str | None,
    reason: str,
    actor: str,
) -> bool:
    """Перенести проверку: сданную или ждущую приёмки. `False` — переносить нечего.

    `None` у даты или точки — оставить как есть (MCP правит одно из двух). У ждущей
    приёмки триггер истории не срабатывает (она ещё не документ): след правки
    остаётся в журнале действий (`inspection.move`).

    Отказ — `MoveError` с объяснением: нет проверки, она не сдана или
    отклонена, пиццерия чужая, не названа причина.
    """
    ident = _require_inspection_id(inspection_id)
    tenant_code = _require_tenant(tenant)
    причина = _require_text(reason, what="повод")
    автор = _require_text(actor, what="автор")
    if new_unit_id is not None:
        try:
            new_unit_id = str(uuid.UUID(new_unit_id))
        except (ValueError, TypeError, AttributeError):
            raise MoveError(
                "Пиццерия не выбрана или указана неверно", code="move_unit_invalid"
            ) from None
    settings = load_retraction_settings()
    try:
        with connection(settings.dsn) as conn:
            изменено = _apply(conn, ident, tenant_code, new_date, new_unit_id, причина, автор)
            conn.commit()
            return изменено
    except MoveError:
        raise
    except psycopg.Error as exc:
        # Тип, а не текст драйвера: в тексте бывает адрес базы, а отказ
        # печатается на карточке.
        raise MoveError(
            f"Исправить проверку {ident} не удалось ({type(exc).__name__}). Исправление идёт "
            f"одной транзакцией вместе с записью истории — наполовину он не случается"
        ) from exc


def _apply(
    conn: psycopg.Connection[Any],
    ident: str,
    tenant: str,
    new_date: date | None,
    new_unit_id: str | None,
    причина: str,
    автор: str,
) -> bool:
    with conn.cursor() as cur:
        cur.execute(_SELECT_HEAD_SQL, {"id": ident, "tenant": tenant})
        шапка = cur.fetchone()
        if шапка is None:
            raise MoveError(f"Проверки {ident} у арендатора {tenant} нет — исправлять нечего")
        статус, отклонена, дата, точка = шапка
        if статус not in ("finalized", "draft"):
            raise MoveError(f"Проверка {ident} в статусе «{статус}» — исправлять её нельзя")
        if отклонена is not None:
            raise MoveError(f"Проверка {ident} отклонена — отклонённую не исправляют")
        new_date = дата if new_date is None else new_date
        # Снятая точка (D538) ведёт на ту, в которую влита: переносят в живую.
        new_unit_id = (
            str(точка) if new_unit_id is None else live_unit_id(conn, new_unit_id) or new_unit_id
        )
        cur.execute(_UNIT_OF_TENANT_SQL, {"unit": new_unit_id, "tenant": tenant})
        if cur.fetchone() is None:
            raise MoveError("Такой пиццерии в справочнике этого пространства нет")
        if дата == new_date and str(точка) == new_unit_id:
            return False
        cur.execute(_CROSS_COUNTRY_PLAN_SQL, {"old": точка, "new": new_unit_id, "id": ident})
        if cur.fetchone() is not None:
            raise MoveError(
                f"Проверку {ident} нельзя перенести в пиццерию другой страны: по ней заведён "
                f"экшн-план, и его запрос с файлами ушли бы партнёру той страны. Отклоните "
                f"проверку и проведите заново / The inspection {ident} cannot be moved to a "
                f"unit in another country: it has an action plan, whose request and files "
                f"would become visible to that country's partner"
            )
        # `set_config(..., true)` — то же, что `set local`: живёт до конца
        # транзакции и не утекает в следующую на том же подключении.
        cur.execute("select set_config('decimus.move_reason', %s, true)", (причина,))
        cur.execute("select set_config('decimus.move_actor', %s, true)", (автор,))
        cur.execute(
            _MOVE_SQL, {"id": ident, "tenant": tenant, "date": new_date, "unit": new_unit_id}
        )
        if cur.rowcount != 1:
            raise MoveError(
                f"Проверку {ident} исправить не удалось: обновлено строк — {cur.rowcount}, "
                f"ожидалась одна. Так выглядит отказ построчной политики: подключение "
                f"обязано идти под ролью администратора истории"
            )
    return True


def list_moves(inspection_id: str, *, reach: Reach) -> tuple[MoveRecord, ...]:
    """История переносов проверки, свежие первыми. Пусто — переносов не было."""
    ident = _require_inspection_id(inspection_id)
    охват = require_reach(reach)
    with _reading("историю переносов") as conn, conn.cursor() as cur:
        cur.execute(_LIST_MOVES_SQL, {"id": ident, **охват.params()})
        строки = cur.fetchall()
    return tuple(
        MoveRecord(
            moved_at=moved_at.strftime("%Y-%m-%d %H:%M"),
            moved_by=str(moved_by),
            reason=str(reason),
            old_date=old_date.isoformat(),
            new_date=new_date.isoformat(),
            old_unit=str(old_unit),
            new_unit=str(new_unit),
        )
        for moved_at, moved_by, reason, old_date, new_date, old_unit, new_unit in строки
    )
