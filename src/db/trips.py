"""Поездки «Календаря» (D497, D505, D506): чтение и запись.

Поездка — кто едет (имя или учётка своего пространства), страна, даты, статус,
заметка; план — шаги по дням: время, что происходит, пиццерия, текст.

Пространство — строго своё, и на чтение тоже (D505). Каждый запрос здесь сам
называет пространство (`tenant_code = %(tenant)s`) — это первая линия; вторая —
политики базы (`0074_trips.sql`), которые отдают и принимают только строки
пространства, поставленного дверью (`src/db/space.py`). Запрос без условия всё
равно не увидел бы чужого; условие нужно, чтобы ошибка двери (не то
пространство) проявилась пустотой, а не чужой поездкой, ещё до базы.

Кто что может (админ — всё в своём пространстве, сотрудник партнёра — свои
поездки), решает матрица (`src/domain/permissions.py`, `trip.plan` / `trip.own`)
на маршруте; здесь — данные и их правила.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, time, timedelta
from typing import Any

import psycopg

from src.domain.tenants import canonical_tenant

from .config import check_environment
from .errors import TripError
from .pool import connection

STATUSES = ("planned", "done", "cancelled")
KINDS = ("road", "inspection", "meeting", "other")
MAX_NAME = 120
MAX_NOTE = 2_000
MAX_BODY = 500
#: Поездка не длиннее двух месяцев (то же правило — в `0074`).
MAX_DAYS = 62
#: Сколько поездок читать за раз: сетка рисует не больше трёх месяцев.
LIST_LIMIT = 500


@dataclass(frozen=True)
class Step:
    id: str
    day: date
    at: time | None
    kind: str
    unit_id: str | None
    unit_name: str | None
    body: str


@dataclass(frozen=True)
class Trip:
    id: str
    tenant: str
    executor_name: str
    executor_user_id: str | None
    country: str | None
    date_from: date
    date_to: date
    status: str
    note: str
    created_by: str
    steps: tuple[Step, ...] = ()

    @property
    def days(self) -> tuple[date, ...]:
        """Все дни поездки по порядку."""
        n = (self.date_to - self.date_from).days
        return tuple(self.date_from + timedelta(days=i) for i in range(n + 1))

    def steps_on(self, day: date) -> tuple[Step, ...]:
        return tuple(s for s in self.steps if s.day == day)


@dataclass(frozen=True)
class Draft:
    """Поля поездки из формы — уже разобранные, но ещё не проверенные."""

    executor_name: str
    executor_user_id: str | None
    country: str | None
    date_from: date | None
    date_to: date | None
    status: str
    note: str


@dataclass(frozen=True)
class StepDraft:
    day: date | None
    at: time | None
    kind: str
    unit_id: str | None
    body: str


_LIST_SQL = """
select t.id, t.tenant_code, t.executor_name, t.executor_user_id, t.country,
       t.date_from, t.date_to, t.status, t.note, t.created_by
  from trips t
 where t.tenant_code = %(tenant)s
   and t.date_to >= %(date_from)s and t.date_from <= %(date_to)s
 order by t.date_from, t.executor_name
 limit %(limit)s
"""

_ONE_SQL = """
select t.id, t.tenant_code, t.executor_name, t.executor_user_id, t.country,
       t.date_from, t.date_to, t.status, t.note, t.created_by
  from trips t
 where t.tenant_code = %(tenant)s and t.id = %(id)s
"""

_STEPS_SQL = """
select s.id, s.day, s.at, s.kind, s.unit_id, u.name, s.body
  from trip_steps s
  left join units u on u.id = s.unit_id
 where s.tenant_code = %(tenant)s and s.trip_id = %(id)s
 order by s.day, s.at nulls first, s.created_at
"""

_INSERT_SQL = """
insert into trips (tenant_code, executor_name, executor_user_id, country,
                   date_from, date_to, status, note, created_by)
values (%(tenant)s, %(executor_name)s, %(executor_user_id)s, %(country)s,
        %(date_from)s, %(date_to)s, %(status)s, %(note)s, %(actor)s)
returning id
"""

_UPDATE_SQL = """
update trips
   set executor_name = %(executor_name)s, executor_user_id = %(executor_user_id)s,
       country = %(country)s, date_from = %(date_from)s, date_to = %(date_to)s,
       status = %(status)s, note = %(note)s, updated_at = now()
 where tenant_code = %(tenant)s and id = %(id)s
"""

_DELETE_SQL = "delete from trips where tenant_code = %(tenant)s and id = %(id)s"

#: Шаги за пределами новых дат при правке поездки не теряются молча — отказ.
_STEPS_OUTSIDE_SQL = """
select count(*) from trip_steps
 where tenant_code = %(tenant)s and trip_id = %(id)s
   and (day < %(date_from)s or day > %(date_to)s)
"""

_INSERT_STEP_SQL = """
insert into trip_steps (trip_id, tenant_code, day, at, kind, unit_id, body)
values (%(id)s, %(tenant)s, %(day)s, %(at)s, %(kind)s, %(unit_id)s, %(body)s)
"""

_DELETE_STEP_SQL = """
delete from trip_steps
 where tenant_code = %(tenant)s and trip_id = %(id)s and id = %(step)s
"""


def _space(tenant: str) -> str:
    код = canonical_tenant(tenant or "")
    if not код:
        raise TripError("trip.err.space")
    return код


def _uuid(raw: str | None) -> str | None:
    """Идентификатор или `None`: строка не-uuid из адреса — «не найдено», а не 500."""
    try:
        return str(uuid.UUID(str(raw or "").strip()))
    except ValueError:
        return None


@contextmanager
def _db(зачем: str) -> Iterator[psycopg.Connection[Any]]:
    try:
        with connection(check_environment().dsn) as conn:
            yield conn
    except psycopg.Error as exc:
        # Наружу — тип ошибки драйвера, не текст: в тексте бывает строка подключения.
        raise TripError("trip.err.db", what=type(exc).__name__) from exc


def _trip(row: tuple[Any, ...], steps: tuple[Step, ...] = ()) -> Trip:
    return Trip(
        id=str(row[0]),
        tenant=str(row[1]),
        executor_name=str(row[2]),
        executor_user_id=None if row[3] is None else str(row[3]),
        country=row[4],
        date_from=row[5],
        date_to=row[6],
        status=str(row[7]),
        note=str(row[8]),
        created_by=str(row[9]),
        steps=steps,
    )


def list_trips(*, tenant: str, date_from: date, date_to: date) -> tuple[Trip, ...]:
    """Поездки пространства, задевающие отрезок `date_from` — `date_to` (без шагов)."""
    with _db("прочитать поездки") as conn, conn.cursor() as cur:
        cur.execute(
            _LIST_SQL,
            {
                "tenant": _space(tenant),
                "date_from": date_from,
                "date_to": date_to,
                "limit": LIST_LIMIT,
            },
        )
        return tuple(_trip(r) for r in cur.fetchall())


def get_trip(trip_id: str, *, tenant: str) -> Trip | None:
    """Поездка своего пространства с планом; чужая или несуществующая — `None`."""
    ident = _uuid(trip_id)
    if ident is None:
        return None
    params = {"tenant": _space(tenant), "id": ident}
    with _db("прочитать поездку") as conn, conn.cursor() as cur:
        cur.execute(_ONE_SQL, params)
        row = cur.fetchone()
        if row is None:
            return None
        cur.execute(_STEPS_SQL, params)
        steps = tuple(
            Step(
                id=str(s[0]),
                day=s[1],
                at=s[2],
                kind=str(s[3]),
                unit_id=None if s[4] is None else str(s[4]),
                unit_name=None if s[5] is None else str(s[5]),
                body=str(s[6]),
            )
            for s in cur.fetchall()
        )
    return _trip(row, steps)


def check_draft(draft: Draft) -> Draft:
    """Проверить поля поездки; отказ — `TripError` с понятным человеку текстом."""
    имя = " ".join(draft.executor_name.split())
    if not имя:
        raise TripError("trip.err.name")
    if len(имя) > MAX_NAME:
        raise TripError("trip.err.name_long", n=MAX_NAME)
    if draft.date_from is None or draft.date_to is None:
        raise TripError("trip.err.dates")
    if draft.date_to < draft.date_from:
        raise TripError("trip.err.order")
    if (draft.date_to - draft.date_from).days > MAX_DAYS:
        raise TripError("trip.err.long", n=MAX_DAYS)
    if draft.status not in STATUSES:
        raise TripError("trip.err.status")
    if len(draft.note) > MAX_NOTE:
        raise TripError("trip.err.note", n=MAX_NOTE)
    страна = (draft.country or "").strip().upper() or None
    if страна is not None and not (len(страна) == 2 and страна.isascii() and страна.isalpha()):
        raise TripError("trip.err.country")
    return Draft(
        executor_name=имя,
        executor_user_id=_uuid(draft.executor_user_id) if draft.executor_user_id else None,
        country=страна,
        date_from=draft.date_from,
        date_to=draft.date_to,
        status=draft.status,
        note=draft.note.strip(),
    )


def _params(draft: Draft) -> dict[str, Any]:
    return {
        "executor_name": draft.executor_name,
        "executor_user_id": draft.executor_user_id,
        "country": draft.country,
        "date_from": draft.date_from,
        "date_to": draft.date_to,
        "status": draft.status,
        "note": draft.note,
    }


def create_trip(draft: Draft, *, tenant: str, actor_id: str) -> str:
    """Завести поездку в своём пространстве; вернуть её `id`."""
    чистый = check_draft(draft)
    автор = _uuid(actor_id)
    if автор is None:
        raise TripError("trip.err.space")
    with _db("сохранить поездку") as conn, conn.cursor() as cur:
        cur.execute(_INSERT_SQL, {**_params(чистый), "tenant": _space(tenant), "actor": автор})
        row = cur.fetchone()
        conn.commit()
    if row is None:
        raise TripError("trip.err.db", what="insert")
    return str(row[0])


def update_trip(trip_id: str, draft: Draft, *, tenant: str) -> bool:
    """Править поездку своего пространства. `False` — такой поездки у пространства нет."""
    ident = _uuid(trip_id)
    if ident is None:
        return False
    чистый = check_draft(draft)
    params = {**_params(чистый), "tenant": _space(tenant), "id": ident}
    with _db("сохранить поездку") as conn, conn.cursor() as cur:
        cur.execute(_STEPS_OUTSIDE_SQL, params)
        вне = cur.fetchone()
        if вне is not None and int(вне[0]) > 0:
            conn.rollback()
            raise TripError("trip.err.steps_outside", n=int(вне[0]))
        cur.execute(_UPDATE_SQL, params)
        изменено = cur.rowcount == 1
        conn.commit()
    return изменено


def delete_trip(trip_id: str, *, tenant: str) -> bool:
    """Удалить поездку своего пространства вместе с планом."""
    ident = _uuid(trip_id)
    if ident is None:
        return False
    with _db("удалить поездку") as conn, conn.cursor() as cur:
        cur.execute(_DELETE_SQL, {"tenant": _space(tenant), "id": ident})
        удалено = cur.rowcount == 1
        conn.commit()
    return удалено


def check_step(step: StepDraft, trip: Trip) -> StepDraft:
    """Проверить шаг плана против его поездки."""
    if step.day is None or not trip.date_from <= step.day <= trip.date_to:
        raise TripError("trip.err.step_day")
    if step.kind not in KINDS:
        raise TripError("trip.err.step_kind")
    текст = step.body.strip()
    if len(текст) > MAX_BODY:
        raise TripError("trip.err.step_long", n=MAX_BODY)
    точка = _uuid(step.unit_id) if step.unit_id else None
    if step.kind == "inspection" and точка is None:
        raise TripError("trip.err.step_unit")
    if step.kind != "inspection" and not текст and точка is None:
        raise TripError("trip.err.step_text")
    return StepDraft(day=step.day, at=step.at, kind=step.kind, unit_id=точка, body=текст)


def add_step(trip: Trip, step: StepDraft) -> None:
    """Добавить шаг в план поездки (поездка уже прочитана своим пространством)."""
    чистый = check_step(step, trip)
    with _db("сохранить шаг плана") as conn, conn.cursor() as cur:
        cur.execute(
            _INSERT_STEP_SQL,
            {
                "id": trip.id,
                "tenant": _space(trip.tenant),
                "day": чистый.day,
                "at": чистый.at,
                "kind": чистый.kind,
                "unit_id": чистый.unit_id,
                "body": чистый.body,
            },
        )
        conn.commit()


def delete_step(trip: Trip, step_id: str) -> bool:
    ident = _uuid(step_id)
    if ident is None:
        return False
    with _db("удалить шаг плана") as conn, conn.cursor() as cur:
        cur.execute(_DELETE_STEP_SQL, {"tenant": _space(trip.tenant), "id": trip.id, "step": ident})
        удалено = cur.rowcount == 1
        conn.commit()
    return удалено
