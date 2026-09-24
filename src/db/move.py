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
from .errors import MoveError
from .queries import _reading, _require_inspection_id, _require_tenant

_SELECT_HEAD_SQL = """
select status, retracted_at, inspection_date, unit_id
from inspections
where id = %(id)s and tenant_code = %(tenant)s
"""

_UNIT_OF_TENANT_SQL = "select 1 from units where id = %(unit)s and tenant_code = %(tenant)s"

_MOVE_SQL = """
update inspections
set inspection_date = %(date)s, unit_id = %(unit)s
where id = %(id)s and tenant_code = %(tenant)s
"""

_LIST_MOVES_SQL = """
select m.moved_at, m.moved_by, m.reason, m.old_date, m.new_date,
       uo.name as old_unit, un.name as new_unit
from inspection_moves m
join units uo on uo.id = m.old_unit_id
join units un on un.id = m.new_unit_id
where m.inspection_id = %(id)s and m.tenant_code = %(tenant)s
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
            f"Не назван {what} переноса. История переноса обязательна (D195): без неё "
            f"правка даты или пиццерии неотличима от подчистки"
        )
    return записанное


def move_inspection(
    inspection_id: str,
    *,
    tenant: str,
    new_date: date,
    new_unit_id: str,
    reason: str,
    actor: str,
) -> bool:
    """Перенести сданную проверку. `False` — переносить нечего, всё уже так.

    Отказ — `MoveError` с объяснением: нет проверки, она не сдана или
    отклонена, пиццерия чужая, не названа причина.
    """
    ident = _require_inspection_id(inspection_id)
    tenant_code = _require_tenant(tenant)
    причина = _require_text(reason, what="повод")
    автор = _require_text(actor, what="автор")
    try:
        new_unit_id = str(uuid.UUID(new_unit_id))
    except (ValueError, TypeError, AttributeError):
        raise MoveError("Пиццерия не выбрана или указана неверно") from None
    settings = load_retraction_settings()
    try:
        with psycopg.connect(settings.dsn) as conn:
            изменено = _apply(conn, ident, tenant_code, new_date, new_unit_id, причина, автор)
            conn.commit()
            return изменено
    except MoveError:
        raise
    except psycopg.Error as exc:
        # Тип, а не текст драйвера: в тексте бывает адрес базы, а отказ
        # печатается на карточке.
        raise MoveError(
            f"Перенести проверку {ident} не удалось ({type(exc).__name__}). Перенос идёт "
            f"одной транзакцией вместе с записью истории — наполовину он не случается"
        ) from exc


def _apply(
    conn: psycopg.Connection[Any],
    ident: str,
    tenant: str,
    new_date: date,
    new_unit_id: str,
    причина: str,
    автор: str,
) -> bool:
    with conn.cursor() as cur:
        cur.execute(_SELECT_HEAD_SQL, {"id": ident, "tenant": tenant})
        шапка = cur.fetchone()
        if шапка is None:
            raise MoveError(f"Проверки {ident} у арендатора {tenant} нет — переносить нечего")
        статус, отклонена, дата, точка = шапка
        if статус != "finalized":
            raise MoveError(
                f"Проверка {ident} ещё не сдана (статус «{статус}») — переносится только "
                f"сданная; черновик правит аудитор в боте"
            )
        if отклонена is not None:
            raise MoveError(f"Проверка {ident} отклонена — отклонённую не переносят")
        cur.execute(_UNIT_OF_TENANT_SQL, {"unit": new_unit_id, "tenant": tenant})
        if cur.fetchone() is None:
            raise MoveError("Такой пиццерии в справочнике этого арендатора нет")
        if дата == new_date and str(точка) == new_unit_id:
            return False
        # `set_config(..., true)` — то же, что `set local`: живёт до конца
        # транзакции и не утекает в следующую на том же подключении.
        cur.execute("select set_config('decimus.move_reason', %s, true)", (причина,))
        cur.execute("select set_config('decimus.move_actor', %s, true)", (автор,))
        cur.execute(
            _MOVE_SQL, {"id": ident, "tenant": tenant, "date": new_date, "unit": new_unit_id}
        )
        if cur.rowcount != 1:
            raise MoveError(
                f"Проверку {ident} перенести не удалось: обновлено строк — {cur.rowcount}, "
                f"ожидалась одна. Так выглядит отказ построчной политики: подключение "
                f"обязано идти под ролью администратора истории"
            )
    return True


def list_moves(inspection_id: str, *, tenant: str) -> tuple[MoveRecord, ...]:
    """История переносов проверки, свежие первыми. Пусто — переносов не было."""
    ident = _require_inspection_id(inspection_id)
    tenant_code = _require_tenant(tenant)
    with _reading("историю переносов") as conn, conn.cursor() as cur:
        cur.execute(_LIST_MOVES_SQL, {"id": ident, "tenant": tenant_code})
        строки = cur.fetchall()
    return tuple(
        MoveRecord(
            moved_at=moved_at.isoformat(timespec="minutes"),
            moved_by=str(moved_by),
            reason=str(reason),
            old_date=old_date.isoformat(),
            new_date=new_date.isoformat(),
            old_unit=str(old_unit),
            new_unit=str(new_unit),
        )
        for moved_at, moved_by, reason, old_date, new_date, old_unit, new_unit in строки
    )
