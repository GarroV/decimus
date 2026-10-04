"""Экшн-планы: запрос, версии файла, приём и возврат (волна 2, D263–D274).

Партнёр отвечает на проверку УК файлом плана (D265, D267). Запрос появляется
сам при подтверждении проверки УК, в которой есть D2 или D3 (D272), со сроком
из настройки (D274), — или кнопкой УК. Партнёр кладёт версию, УК принимает её
или возвращает с комментарием, партнёр кладёт следующую.

**Кто что пишет — держит база (`0036`), а не этот модуль.** Загрузка идёт ролью
приложения и умеет только положить версию и перевести запрос на приёмку.
Запрос, срок и вердикт — ролью администратора истории. Вставить запрос сразу
«принятым» или перевести его в «принят» без вердикта не может никто; историю
пишут триггеры. Здесь — понятные человеку отказы до похода в базу и охват.

**Охват.** Читают по охвату (`reach.py`): УК — все страны, партнёр — свои
(D284, D289). Чужой запрос или файл по угаданному id отвечает тем же `None`,
что несуществующий.

**«Просрочен» не хранится**, а считается на чтении (`is_overdue`).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol

import psycopg

from src.domain.tenants import HQ_TENANT

from .config import (
    check_environment,
    load_action_plan_settings,
    load_retraction_settings,
    load_storage_settings,
)
from .errors import ActionPlanError, DbError, StorageError
from .reach import Reach, require_reach
from .storage import PhotoStorage, S3PhotoStorage, key_of_uri

logger = logging.getLogger(__name__)

#: Классы, при которых запрос появляется сам (D272) — решение владельца, а не
#: ставка методики: вычеты и буквы по-прежнему только в `data/scoring.json`.
TRIGGER_LEVELS = ("D2", "D3")

STATUS_REQUESTED = "requested"
STATUS_ON_REVIEW = "on_review"
STATUS_ACCEPTED = "accepted"
STATUSES = (STATUS_REQUESTED, STATUS_ON_REVIEW, STATUS_ACCEPTED)

VERDICT_ACCEPTED = "accepted"
VERDICT_RETURNED = "returned"
VERDICTS = (VERDICT_ACCEPTED, VERDICT_RETURNED)

#: Состояние для экрана: статус базы плюс «вернули» — запрошен заново после возврата.
STATE_REQUESTED = "requested"
STATE_RETURNED = "returned"
STATE_ON_REVIEW = "on_review"
STATE_ACCEPTED = "accepted"

ORIGIN_AUTO = "auto"
ORIGIN_MANUAL = "manual"

#: Префикс файлов в хранилище кадров (D268): удаление кадров после вычитки
#: (D202) ходит по `inspections/`, сюда не заглядывает.
STORAGE_PREFIX = "action-plans"

#: Тип, когда браузер его не прислал.
DEFAULT_CONTENT_TYPE = "application/octet-stream"
MAX_FILE_NAME = 255
MAX_CONTENT_TYPE = 255
#: Сколько запросов читается в список за раз.
LIST_LIMIT = 500


def today() -> date:
    """Сегодня для срока и просрочки — по UTC, одно на всю систему."""
    return datetime.now(UTC).date()


# ── Ядро: чистые правила ────────────────────────────────────────────────────


def needs_action_plan(counts: Mapping[str, Any]) -> bool:
    """Нужен ли запрос сам: в счётчиках движка есть D2 или D3 (D272)."""
    for level in TRIGGER_LEVELS:
        raw = counts.get(level, 0)
        try:
            number = int(raw)
        except (TypeError, ValueError) as exc:
            raise ActionPlanError(
                f"Счётчик {level} у проверки не число ({raw!r}) — нужен ли экшн-план, "
                f"не понять. Счётчики кладёт движок; такой ответ — поломка, а не ноль"
            ) from exc
        if number > 0:
            return True
    return False


def _require_status(status: str) -> str:
    if status not in STATUSES:
        raise ActionPlanError(f"Статус запроса «{status}» неизвестен: {', '.join(STATUSES)}")
    return status


def is_overdue(status: str, due_on: date, *, today: date) -> bool:
    """Просрочен: срок прошёл, а план всё ещё ждут от партнёра (в т. ч. после возврата)."""
    return _require_status(status) == STATUS_REQUESTED and today > due_on


def plan_state(status: str, last_verdict: str | None) -> str:
    """Состояние для экрана: запрошен / вернули / на приёмке / принят."""
    if _require_status(status) == STATUS_REQUESTED:
        return STATE_RETURNED if last_verdict == VERDICT_RETURNED else STATE_REQUESTED
    return STATE_ON_REVIEW if status == STATUS_ON_REVIEW else STATE_ACCEPTED


def due_date(start: date, days: int) -> date:
    """Срок ответа: `days` дней от `start`. Меньше дня — отказ."""
    if days < 1:
        raise ActionPlanError(f"Срок ответа меньше дня ({days}) — партнёру не успеть")
    return start + timedelta(days=days)


# ── Модель чтения ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PlanFile:
    """Версия файла плана и вердикт УК по ней (если вынесен)."""

    id: str
    version: int
    file_name: str
    size_bytes: int
    content_type: str
    uploaded_by: str
    uploaded_at: datetime
    verdict: str | None
    comment: str | None
    reviewed_by: str | None
    reviewed_at: datetime | None


@dataclass(frozen=True)
class PlanEvent:
    """Строка истории: кто, что, когда."""

    action: str
    actor: str
    detail: str | None
    at: datetime


@dataclass(frozen=True)
class PlanRequest:
    """Запрос экшн-плана с проверкой, версиями и историей."""

    id: str
    inspection_id: str
    #: Страна точки проверки сейчас (не копия на момент запроса): проверку
    #: переносят в точку другой страны (D195) — запрос уезжает с ней.
    country: str | None
    due_on: date
    status: str
    origin: str
    requested_by: str
    requested_at: datetime
    unit_id: str
    unit_name: str
    inspection_date: date
    pct: float | None
    grade: str | None
    files: tuple[PlanFile, ...]
    events: tuple[PlanEvent, ...]

    @property
    def state(self) -> str:
        return plan_state(self.status, self.files[-1].verdict if self.files else None)

    def overdue(self, on: date) -> bool:
        return is_overdue(self.status, self.due_on, today=on)

    @property
    def last_comment(self) -> str | None:
        """Комментарий последнего возврата — его партнёр видит у запроса."""
        for item in reversed(self.files):
            if item.verdict == VERDICT_RETURNED:
                return item.comment
        return None


@dataclass(frozen=True)
class PlanList:
    """Страница списка: строки и упёрся ли он в предел (тогда это сказано на экране)."""

    rows: tuple[PlanRequest, ...]
    truncated: bool


@dataclass(frozen=True)
class PlanFileRef:
    """Файл к выдаче: где лежит и как назывался."""

    storage_path: str
    file_name: str
    content_type: str
    size_bytes: int


# ── Запросы ─────────────────────────────────────────────────────────────────

# Охват — литералом `REACH_SQL` (сверка `tests/test_db_reach_static.py`).
# Отклонённая проверка запрос не снимает, но из списков он уходит.
#
# Очередь — только открытые: принятые копятся годами и, попав в общий список с
# пределом, вытеснили бы открытые молча. Условие статуса — литерал, а не
# параметр: так его узнаёт частичный индекс `action_plan_requests_open_idx`
# (0036), и очередь по всем странам не читает историю.
_OPEN_SQL = """
select r.id, r.inspection_id, u.country, r.due_on, r.status, r.origin, r.requested_by,
       r.requested_at, u.id, u.name, i.inspection_date, i.pct, i.grade
from action_plan_requests r
join inspections i on i.id = r.inspection_id
join units u on u.id = i.unit_id
where (%(tenants)s::text[] is null or i.tenant_code = any(%(tenants)s)) and (%(countries)s::text[] is null or u.country = any(%(countries)s))
  and r.status <> 'accepted'
  and i.retracted_at is null
  and (%(country)s::text is null or u.country = %(country)s)
order by r.due_on, r.requested_at
limit %(limit)s
"""  # noqa: E501 — условие охвата вписано литералом целиком

# Принятые — отдельно, по кнопке «Принятые»: свежие первыми.
_ACCEPTED_SQL = """
select r.id, r.inspection_id, u.country, r.due_on, r.status, r.origin, r.requested_by,
       r.requested_at, u.id, u.name, i.inspection_date, i.pct, i.grade
from action_plan_requests r
join inspections i on i.id = r.inspection_id
join units u on u.id = i.unit_id
where (%(tenants)s::text[] is null or i.tenant_code = any(%(tenants)s)) and (%(countries)s::text[] is null or u.country = any(%(countries)s))
  and r.status = 'accepted'
  and i.retracted_at is null
  and (%(country)s::text is null or u.country = %(country)s)
order by r.due_on desc, r.requested_at desc
limit %(limit)s
"""  # noqa: E501

# Один запрос — по id или по проверке, в любом статусе.
_ONE_SQL = """
select r.id, r.inspection_id, u.country, r.due_on, r.status, r.origin, r.requested_by,
       r.requested_at, u.id, u.name, i.inspection_date, i.pct, i.grade
from action_plan_requests r
join inspections i on i.id = r.inspection_id
join units u on u.id = i.unit_id
where (%(tenants)s::text[] is null or i.tenant_code = any(%(tenants)s)) and (%(countries)s::text[] is null or u.country = any(%(countries)s))
  and i.retracted_at is null
  and (%(request_id)s::uuid is null or r.id = %(request_id)s)
  and (%(inspection_id)s::uuid is null or r.inspection_id = %(inspection_id)s)
limit 1
"""  # noqa: E501

_FILES_SQL = """
select f.request_id, f.id, f.version, f.file_name, f.size_bytes, f.content_type,
       f.uploaded_by, f.uploaded_at, v.verdict, v.comment, v.reviewed_by, v.reviewed_at
from action_plan_files f
left join action_plan_reviews v on v.file_id = f.id
where f.request_id = any(%(ids)s::uuid[])
order by f.request_id, f.version
"""

_EVENTS_SQL = """
select e.request_id, e.action, e.actor, e.detail, e.at
from action_plan_events e
where e.request_id = any(%(ids)s::uuid[])
order by e.request_id, e.at, e.id
"""

_FILE_SQL = """
select f.storage_path, f.file_name, f.content_type, f.size_bytes
from action_plan_files f
join action_plan_requests r on r.id = f.request_id
join inspections i on i.id = r.inspection_id
join units u on u.id = i.unit_id
where (%(tenants)s::text[] is null or i.tenant_code = any(%(tenants)s)) and (%(countries)s::text[] is null or u.country = any(%(countries)s))
  and i.retracted_at is null
  and f.id = %(id)s
"""  # noqa: E501

# Карточка: у точки проверки нет страны — запрос с D2/D3 не завёлся (ревью #495).
_UNIT_COUNTRY_MISSING_SQL = """
select u.country is null
from inspections i
join units u on u.id = i.unit_id
where (%(tenants)s::text[] is null or i.tenant_code = any(%(tenants)s)) and (%(countries)s::text[] is null or u.country = any(%(countries)s))
  and i.id = %(id)s
"""  # noqa: E501

# Загрузка: замок строки запроса, охват — тем же литералом.
_LOCK_FOR_UPLOAD_SQL = """
select r.status
from action_plan_requests r
join inspections i on i.id = r.inspection_id
join units u on u.id = i.unit_id
where (%(tenants)s::text[] is null or i.tenant_code = any(%(tenants)s)) and (%(countries)s::text[] is null or u.country = any(%(countries)s))
  and i.retracted_at is null
  and r.id = %(id)s
for update of r
"""  # noqa: E501

_NEXT_VERSION_SQL = (
    "select coalesce(max(version), 0) + 1 from action_plan_files where request_id = %s"
)

_INSERT_FILE_SQL = """
insert into action_plan_files
    (id, request_id, version, storage_path, file_name, size_bytes, content_type,
     uploaded_by, uploaded_tenant)
values
    (%(id)s, %(request_id)s, %(version)s, %(storage_path)s, %(file_name)s, %(size_bytes)s,
     %(content_type)s, %(uploaded_by)s, %(uploaded_tenant)s)
"""

_SET_STATUS_SQL = "update action_plan_requests set status = %(status)s where id = %(id)s"

# Двери УК (администратор истории): проверка по id, без охвата — пишет только
# УК и только по проверкам своего пространства (условие `tenant_code`).
_INSPECTION_FOR_REQUEST_SQL = """
select i.tenant_code, i.status, i.retracted_at, i.counts, u.country
from inspections i
join units u on u.id = i.unit_id
where i.id = %s
"""

_EXISTING_SQL = "select 1 from action_plan_requests where inspection_id = %s"

_INSERT_REQUEST_SQL = """
insert into action_plan_requests
    (inspection_id, due_on, origin, requested_by, due_set_by)
values (%(inspection_id)s, %(due_on)s, %(origin)s, %(actor)s, %(actor)s)
on conflict (inspection_id) do nothing
returning id
"""

_LOCK_REQUEST_SQL = "select status from action_plan_requests where id = %s for update"

_LAST_FILE_SQL = """
select f.id, v.verdict
from action_plan_files f
left join action_plan_reviews v on v.file_id = f.id
where f.request_id = %s
order by f.version desc
limit 1
"""

# Подпись срока — настройкой транзакции: `due_set_by` пишет триггер (0036).
_SIGN_DUE_SQL = "select set_config('decimus.plan_actor', %s, true)"

_SET_DUE_SQL = "update action_plan_requests set due_on = %(due_on)s where id = %(id)s"

_INSERT_REVIEW_SQL = """
insert into action_plan_reviews (file_id, verdict, comment, reviewed_by)
values (%(file_id)s, %(verdict)s, %(comment)s, %(actor)s)
"""


# ── Чтение ──────────────────────────────────────────────────────────────────


def _uuid_or_none(value: str | None) -> str | None:
    """Идентификатор из адреса: кривой — это «нет такого», а не ошибка базы."""
    if value is None:
        return None
    try:
        return str(uuid.UUID(str(value).strip()))
    except ValueError:
        return None


def _read(sql: str, params: dict[str, Any]) -> tuple[PlanRequest, ...]:
    try:
        with psycopg.connect(check_environment().dsn) as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            heads = cur.fetchall()
            ids = [str(row[0]) for row in heads]
            cur.execute(_FILES_SQL, {"ids": ids})
            files = cur.fetchall()
            cur.execute(_EVENTS_SQL, {"ids": ids})
            events = cur.fetchall()
    except psycopg.Error as exc:
        raise DbError(f"Не удалось прочитать экшн-планы ({type(exc).__name__})") from exc
    return tuple(_assemble(row, files, events) for row in heads)


def _assemble(
    head: tuple[Any, ...], files: list[tuple[Any, ...]], events: list[tuple[Any, ...]]
) -> PlanRequest:
    ident = str(head[0])
    return PlanRequest(
        id=ident,
        inspection_id=str(head[1]),
        country=None if head[2] is None else str(head[2]),
        due_on=head[3],
        status=str(head[4]),
        origin=str(head[5]),
        requested_by=str(head[6]),
        requested_at=head[7],
        unit_id=str(head[8]),
        unit_name=str(head[9]),
        inspection_date=head[10],
        pct=None if head[11] is None else float(head[11]),
        grade=None if head[12] is None else str(head[12]),
        files=tuple(
            PlanFile(
                id=str(row[1]),
                version=int(row[2]),
                file_name=str(row[3]),
                size_bytes=int(row[4]),
                content_type=str(row[5]),
                uploaded_by=str(row[6]),
                uploaded_at=row[7],
                verdict=row[8],
                comment=row[9],
                reviewed_by=row[10],
                reviewed_at=row[11],
            )
            for row in files
            if str(row[0]) == ident
        ),
        events=tuple(
            PlanEvent(action=str(row[1]), actor=str(row[2]), detail=row[3], at=row[4])
            for row in events
            if str(row[0]) == ident
        ),
    )


def list_requests(*, reach: Reach, country: str | None = None, accepted: bool = False) -> PlanList:
    """Открытые запросы в охвате (и стране, если названа) по сроку; `accepted` — принятые.

    Читается на одну строку больше предела: так видно, что список обрезан, и
    экран говорит об этом, а не молчит.
    """
    params = {
        **require_reach(reach).params(),
        "country": country or None,
        "limit": LIST_LIMIT + 1,
    }
    rows = _read(_ACCEPTED_SQL if accepted else _OPEN_SQL, params)
    return PlanList(rows=rows[:LIST_LIMIT], truncated=len(rows) > LIST_LIMIT)


def _read_one(
    reach: Reach, *, request_id: str | None = None, inspection_id: str | None = None
) -> PlanRequest | None:
    params = {
        **require_reach(reach).params(),
        "request_id": request_id,
        "inspection_id": inspection_id,
    }
    found = _read(_ONE_SQL, params)
    return found[0] if found else None


def get_request(request_id: str, *, reach: Reach) -> PlanRequest | None:
    """Запрос по id в охвате. Чужой и несуществующий — одинаково `None`."""
    ident = _uuid_or_none(request_id)
    if ident is None:
        return None
    return _read_one(reach, request_id=ident)


def request_of_inspection(inspection_id: str, *, reach: Reach) -> PlanRequest | None:
    """Запрос по проверке в охвате, или `None`."""
    ident = _uuid_or_none(inspection_id)
    if ident is None:
        return None
    return _read_one(reach, inspection_id=ident)


def unit_country_missing(inspection_id: str, *, reach: Reach) -> bool:
    """У точки проверки нет страны? Проверки вне охвата — `False`, как и нет её."""
    ident = _uuid_or_none(inspection_id)
    if ident is None:
        return False
    try:
        with psycopg.connect(check_environment().dsn) as conn, conn.cursor() as cur:
            cur.execute(_UNIT_COUNTRY_MISSING_SQL, {"id": ident, **require_reach(reach).params()})
            row = cur.fetchone()
    except psycopg.Error as exc:
        raise DbError(f"Не удалось прочитать страну точки ({type(exc).__name__})") from exc
    return bool(row and row[0])


def file_for_download(file_id: str, *, reach: Reach) -> PlanFileRef | None:
    """Файл версии в охвате читающего. Чужой и несуществующий — одинаково `None`."""
    ident = _uuid_or_none(file_id)
    if ident is None:
        return None
    try:
        with psycopg.connect(check_environment().dsn) as conn, conn.cursor() as cur:
            cur.execute(_FILE_SQL, {"id": ident, **require_reach(reach).params()})
            row = cur.fetchone()
    except psycopg.Error as exc:
        raise DbError(f"Не удалось прочитать файл экшн-плана ({type(exc).__name__})") from exc
    if row is None:
        return None
    return PlanFileRef(
        storage_path=str(row[0]),
        file_name=str(row[1]),
        content_type=str(row[2]),
        size_bytes=int(row[3]),
    )


class FileReader(Protocol):
    """Чтение объекта из хранилища."""

    def get(self, key: str) -> bytes: ...


def fetch_file(ref: PlanFileRef, *, storage: FileReader | None = None) -> bytes:
    """Байты файла из хранилища. Пустой объект — отказ, а не пустой файл."""
    store = storage if storage is not None else S3PhotoStorage(load_storage_settings())
    data = store.get(key_of_uri(ref.storage_path))
    if not data:
        raise StorageError(f"Хранилище отдало пустой объект вместо плана: {ref.storage_path}")
    return data


# ── Запись: автозапрос при подтверждении ───────────────────────────────────


def open_auto_request(
    cur: psycopg.Cursor[Any], inspection_id: str, *, actor: str, on: date
) -> str | None:
    """Завести запрос сам — тем же курсором, что подтверждает проверку (D272).

    Зовётся из `accept.py` внутри транзакции подтверждения: подтверждение без
    запроса невозможно, оба ложатся вместе или не ложатся вовсе. Возвращает id
    запроса или `None`, если он не нужен (нет D2/D3, проверка не УК) или уже был.

    Срок (`ACTION_PLAN_DUE_DAYS`) читается здесь и только когда запрос нужен:
    кривая настройка роняет подтверждение проверки с D2/D3 (`ConfigError`), а не
    любой проверки.
    """
    cur.execute(_INSPECTION_FOR_REQUEST_SQL, (inspection_id,))
    row = cur.fetchone()
    if row is None:
        return None
    tenant, _status, _retracted, counts, country = row
    if tenant != HQ_TENANT or not needs_action_plan(counts or {}):
        return None
    if not country:
        # Без страны запрос некому показать. Подтверждение не роняем: проверка
        # принята верно, а страну точке дописывают в справочнике.
        logger.warning(
            "проверка %s с D2/D3 принята, но у её точки нет страны — запрос экшн-плана не заведён",
            inspection_id,
        )
        return None
    cur.execute(
        _INSERT_REQUEST_SQL,
        {
            "inspection_id": inspection_id,
            "due_on": due_date(on, load_action_plan_settings().due_days),
            "origin": ORIGIN_AUTO,
            "actor": actor,
        },
    )
    created = cur.fetchone()
    return None if created is None else str(created[0])


# ── Запись: двери УК (администратор истории) ───────────────────────────────


def _actor(actor: str) -> str:
    value = (actor or "").strip()
    if not value:
        raise ActionPlanError("Не назван, кто действует: в истории каждое действие подписано")
    return value


def _admin_write(what: str) -> psycopg.Connection[Any]:
    try:
        return psycopg.connect(load_retraction_settings().dsn)
    except psycopg.Error as exc:
        raise ActionPlanError(f"{what}: база не на связи ({type(exc).__name__})") from exc


def _translate(what: str, exc: psycopg.Error) -> ActionPlanError:
    # Тип, а не текст драйвера: в тексте бывает адрес базы, а отказ — на экране.
    return ActionPlanError(f"{what} не удалось ({type(exc).__name__}). Ничего не изменено")


def request_plan(inspection_id: str, *, actor: str, due_on: date) -> str:
    """Запросить план кнопкой УК по принятой проверке УК. Возвращает id запроса."""
    who = _actor(actor)
    ident = _uuid_or_none(inspection_id)
    if ident is None:
        raise ActionPlanError(f"«{inspection_id}» не похоже на идентификатор проверки")
    if due_on < today():
        raise ActionPlanError(f"Срок {due_on.isoformat()} уже прошёл — назначьте будущую дату")
    try:
        with _admin_write("Запросить экшн-план") as conn, conn.cursor() as cur:
            cur.execute(_INSPECTION_FOR_REQUEST_SQL, (ident,))
            row = cur.fetchone()
            _require_requestable(ident, row)
            cur.execute(_EXISTING_SQL, (ident,))
            if cur.fetchone() is not None:
                raise ActionPlanError("По этой проверке экшн-план уже запрошен")
            cur.execute(
                _INSERT_REQUEST_SQL,
                {
                    "inspection_id": ident,
                    "due_on": due_on,
                    "origin": ORIGIN_MANUAL,
                    "actor": who,
                },
            )
            created = cur.fetchone()
            if created is None:
                raise ActionPlanError("По этой проверке экшн-план уже запрошен")
            conn.commit()
            return str(created[0])
    except psycopg.Error as exc:
        raise _translate("Запросить экшн-план", exc) from exc


def _require_requestable(ident: str, row: tuple[Any, ...] | None) -> None:
    if row is None:
        raise ActionPlanError(f"Проверки {ident} нет")
    tenant, status, retracted, _counts, country = row
    if tenant != HQ_TENANT:
        raise ActionPlanError("Экшн-план запрашивают по проверке УК, а это проверка партнёра")
    if retracted is not None:
        raise ActionPlanError("Проверка отклонена — запрашивать план не по чему")
    if status != "finalized":
        raise ActionPlanError("Проверка ещё на приёмке — сначала её подтверждают")
    if not country:
        raise ActionPlanError("У пиццерии проверки нет страны — запрос некому показать")


def set_due(request_id: str, *, actor: str, due_on: date) -> None:
    """Поправить срок у конкретного запроса (D274). Принятый не правится."""
    who = _actor(actor)
    ident = _uuid_or_none(request_id)
    if ident is None:
        raise ActionPlanError("Запроса нет")
    if due_on < today():
        raise ActionPlanError(f"Срок {due_on.isoformat()} уже прошёл — назначьте будущую дату")
    try:
        with _admin_write("Поправить срок") as conn, conn.cursor() as cur:
            status = _locked_status(cur, ident)
            if status == STATUS_ACCEPTED:
                raise ActionPlanError("План уже принят — срок не правится")
            cur.execute(_SIGN_DUE_SQL, (who,))
            cur.execute(_SET_DUE_SQL, {"id": ident, "due_on": due_on})
            conn.commit()
    except psycopg.Error as exc:
        raise _translate("Поправить срок", exc) from exc


def _locked_status(cur: psycopg.Cursor[Any], ident: str) -> str:
    cur.execute(_LOCK_REQUEST_SQL, (ident,))
    row = cur.fetchone()
    if row is None:
        raise ActionPlanError("Запроса нет")
    return str(row[0])


def review(request_id: str, *, actor: str, verdict: str, comment: str) -> None:
    """Принять последнюю версию или вернуть её с обязательным комментарием."""
    who = _actor(actor)
    if verdict not in VERDICTS:
        raise ActionPlanError(f"Вердикт «{verdict}» неизвестен: {', '.join(VERDICTS)}")
    text = (comment or "").strip()
    if verdict == VERDICT_RETURNED and not text:
        raise ActionPlanError("Вернуть план можно только с комментарием: что исправить")
    ident = _uuid_or_none(request_id)
    if ident is None:
        raise ActionPlanError("Запроса нет")
    try:
        with _admin_write("Вынести вердикт") as conn, conn.cursor() as cur:
            if _locked_status(cur, ident) != STATUS_ON_REVIEW:
                raise ActionPlanError("План не на приёмке — принимать или возвращать нечего")
            cur.execute(_LAST_FILE_SQL, (ident,))
            last = cur.fetchone()
            if last is None or last[1] is not None:
                raise ActionPlanError("Новой версии плана нет — выносить вердикт не по чему")
            cur.execute(
                _INSERT_REVIEW_SQL,
                {"file_id": last[0], "verdict": verdict, "comment": text or None, "actor": who},
            )
            new_status = STATUS_ACCEPTED if verdict == VERDICT_ACCEPTED else STATUS_REQUESTED
            cur.execute(_SET_STATUS_SQL, {"id": ident, "status": new_status})
            conn.commit()
    except psycopg.Error as exc:
        raise _translate("Вынести вердикт", exc) from exc


# ── Запись: загрузка версии партнёром (роль приложения) ────────────────────


def clean_file_name(raw: str) -> str:
    """Имя файла для истории и выдачи: без пути и управляющих символов."""
    name = (raw or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(ch for ch in name if ch.isprintable()).strip()
    return name[:MAX_FILE_NAME] or "plan"


def _clean_content_type(raw: str) -> str:
    value = "".join(ch for ch in (raw or "") if ch.isprintable()).strip()
    return value[:MAX_CONTENT_TYPE] or DEFAULT_CONTENT_TYPE


def object_key(request_id: str, file_id: str) -> str:
    """Ключ версии в хранилище — только идентификаторы (как у кадров)."""
    return f"{STORAGE_PREFIX}/{request_id}/{file_id}"


def upload_version(
    request_id: str,
    *,
    reach: Reach,
    tenant: str,
    actor: str,
    file_name: str,
    content_type: str,
    data: bytes,
    max_bytes: int,
    storage: PhotoStorage | None = None,
) -> int:
    """Положить новую версию плана и отправить запрос на приёмку. Возвращает номер версии.

    Запрос вне охвата отвечает «нет», как несуществующий. Что кладёт только
    партнёр этой страны и только в запрошенный запрос — держит ещё и триггер.
    """
    who = _actor(actor)
    if not data:
        raise ActionPlanError("Файл пустой — класть нечего")
    if len(data) > max_bytes:
        raise ActionPlanError(
            f"Файл больше предела {max_bytes // (1024 * 1024)} МБ (ATTACHMENT_MAX_MB)"
        )
    if tenant == HQ_TENANT:
        raise ActionPlanError("План кладёт партнёр страны, а не УК")
    ident = _uuid_or_none(request_id)
    if ident is None:
        raise ActionPlanError("Запроса нет")
    store = storage if storage is not None else S3PhotoStorage(load_storage_settings())
    file_id = str(uuid.uuid4())
    key = object_key(ident, file_id)
    # Файл кладётся ДО транзакции: заливка до 25 МБ не держит ни соединение, ни
    # замок строки запроса. Строка не легла (чужой запрос, не та стадия,
    # отказ базы) — объект убирается. Обратный порядок оставил бы в истории
    # версию, которой нет в хранилище.
    uri = store.put(key, data, content_type=_clean_content_type(content_type))
    try:
        version = _record_version(
            ident,
            reach=reach,
            row={
                "id": file_id,
                "request_id": ident,
                "storage_path": uri,
                "file_name": clean_file_name(file_name),
                "size_bytes": len(data),
                "content_type": _clean_content_type(content_type),
                "uploaded_by": who,
                "uploaded_tenant": tenant,
            },
        )
    except (ActionPlanError, psycopg.Error) as exc:
        _drop_orphan(store, key)
        if isinstance(exc, psycopg.Error):
            raise _translate("Загрузить план", exc) from exc
        raise
    return version


def _record_version(ident: str, *, reach: Reach, row: dict[str, Any]) -> int:
    """Строка версии и перевод на приёмку — под замком строки запроса."""
    with psycopg.connect(check_environment().dsn) as conn, conn.cursor() as cur:
        cur.execute(_LOCK_FOR_UPLOAD_SQL, {"id": ident, **require_reach(reach).params()})
        head = cur.fetchone()
        if head is None:
            raise ActionPlanError("Запроса нет")
        if head[0] != STATUS_REQUESTED:
            raise ActionPlanError(
                "План уже на приёмке или принят — новую версию кладут после возврата"
            )
        cur.execute(_NEXT_VERSION_SQL, (ident,))
        version_row = cur.fetchone()
        version = int(version_row[0]) if version_row else 1
        cur.execute(_INSERT_FILE_SQL, {**row, "version": version})
        cur.execute(_SET_STATUS_SQL, {"id": ident, "status": STATUS_ON_REVIEW})
        conn.commit()
        return version


def _drop_orphan(store: PhotoStorage, key: str) -> None:
    """Убрать объект, строка которого не легла. Не вышло — в журнал, а не молча."""
    try:
        store.delete(key)
    except StorageError as exc:
        logger.warning("объект %s без строки в базе не убран: %s", key, exc)
