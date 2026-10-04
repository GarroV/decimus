"""Предписания: черновик, отправка через Gmail сотрудника, ответ партнёра, закрытие (волна 3).

Предписание — официальное письмо УК партнёру страны (D266). Сотрудник УК
вставляет текст сам (D270), письмо ложится черновиком в его почту, и с этого
момента предписание «действует». Партнёр отвечает комментарием и файлом, УК
закрывает с комментарием. Отправленное не правится: исправление — закрытие и
новое предписание.

**Кто что пишет — держит база (`0037`), а не этот модуль.** Черновик, его
связи, отправка и закрытие — ролью администратора истории; роль приложения
может только ответить на действующее предписание своей страны. Здесь —
понятные человеку отказы до похода в базу и охват.

**Охват.** УК читает всё, партнёр — предписания своих стран (D284) и никогда не
черновики. Чужое по угаданному id отвечает тем же `None`, что несуществующее.

**«Просрочено» не хранится**, а считается на чтении (`is_overdue`).

**Писем система не шлёт.** `issue` получает функцию, которая кладёт черновик в
почту сотрудника (её даёт веб); отправляет письмо человек сам.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import psycopg

from src.domain.tenants import HQ_TENANT, canonical_tenant

from .action_plans import FileReader
from .config import check_environment, load_storage_settings
from .errors import PrescriptionError, StorageError
from .reach import Reach, require_reach
from .storage import S3PhotoStorage, key_of_uri

logger = logging.getLogger(__name__)

STATUS_DRAFT = "draft"
STATUS_ISSUED = "issued"
STATUS_CLOSED = "closed"
STATUSES = (STATUS_DRAFT, STATUS_ISSUED, STATUS_CLOSED)

#: Состояние для экрана: статус базы плюс посчитанная просрочка.
STATE_DRAFT = "draft"
STATE_ACTIVE = "active"
STATE_OVERDUE = "overdue"
STATE_CLOSED = "closed"

MAX_SUBJECT = 300
MAX_BODY = 20_000
MAX_RECIPIENTS = 2_000
#: Сколько предписаний читается в список за раз.
LIST_LIMIT = 500
#: Сколько последних проверок страны предлагается в основания.
BASES_LIMIT = 60

_EMAIL = re.compile(r"[^@\s,;<>\"']+@[^@\s,;<>\"']+\.[^@\s,;<>\"']+")


def today() -> date:
    """Сегодня для срока и просрочки — по UTC, как у экшн-планов."""
    return datetime.now(UTC).date()


# ── Ядро: чистые правила ────────────────────────────────────────────────────


def _require_status(status: str) -> str:
    if status not in STATUSES:
        raise PrescriptionError(f"Статус предписания «{status}» неизвестен: {', '.join(STATUSES)}")
    return status


def is_overdue(status: str, due_on: date, *, today: date) -> bool:
    """Просрочено: срок прошёл, а предписание всё ещё действует."""
    return _require_status(status) == STATUS_ISSUED and today > due_on


def state_of(status: str, due_on: date, *, today: date) -> str:
    """Состояние для экрана: черновик / действует / просрочено / закрыто."""
    if _require_status(status) == STATUS_DRAFT:
        return STATE_DRAFT
    if status == STATUS_CLOSED:
        return STATE_CLOSED
    return STATE_OVERDUE if is_overdue(status, due_on, today=today) else STATE_ACTIVE


def parse_recipients(raw: str) -> str:
    """Адресаты письма: адреса через запятую, точку с запятой или с новой строки.

    Возвращается одна строка «a@x.ge, b@y.ge» — так она ложится в заголовок
    `To:` и в память страны. Кривой адрес — отказ с его текстом, а не тихий
    пропуск: письмо без адресата, которого человек вписал, ушло бы не всем.
    """
    части = [часть.strip() for часть in re.split(r"[,;\n\r]+", raw or "")]
    адреса: list[str] = []
    for часть in части:
        if not часть:
            continue
        if not _EMAIL.fullmatch(часть):
            raise PrescriptionError(f"«{часть[:80]}» не похоже на адрес почты")
        if часть.lower() not in (а.lower() for а in адреса):
            адреса.append(часть)
    итог = ", ".join(адреса)
    if len(итог) > MAX_RECIPIENTS:
        raise PrescriptionError("Адресатов слишком много для одного письма")
    return итог


@dataclass(frozen=True)
class Draft:
    """Содержимое черновика, как его вписал сотрудник УК."""

    country: str
    due_on: date
    recipients: str
    subject: str
    body: str
    unit_ids: tuple[str, ...] = ()
    inspection_ids: tuple[str, ...] = ()


def check_draft(draft: Draft, *, on: date) -> Draft:
    """Черновик, приведённый к виду базы, — или понятный отказ."""
    if not re.fullmatch(r"[A-Z]{2}", draft.country or ""):
        raise PrescriptionError("Страна не выбрана")
    тема = (draft.subject or "").strip()
    текст = (draft.body or "").strip()
    if not тема:
        raise PrescriptionError("Нет темы письма")
    if len(тема) > MAX_SUBJECT:
        raise PrescriptionError(f"Тема длиннее {MAX_SUBJECT} знаков")
    if not текст:
        raise PrescriptionError("Нет текста письма — вставьте его")
    if len(текст) > MAX_BODY:
        raise PrescriptionError(f"Текст письма длиннее {MAX_BODY} знаков")
    if draft.due_on < on:
        raise PrescriptionError(
            f"Срок {draft.due_on.isoformat()} уже прошёл — назначьте будущую дату"
        )
    точки = _ids(draft.unit_ids, "пиццерии")
    основания = _ids(draft.inspection_ids, "проверки")
    return Draft(
        country=draft.country,
        due_on=draft.due_on,
        recipients=parse_recipients(draft.recipients),
        subject=тема,
        body=текст,
        unit_ids=точки,
        inspection_ids=основания,
    )


def _ids(values: Iterable[str], what: str) -> tuple[str, ...]:
    итог: list[str] = []
    for value in values:
        ident = uuid_or_none(value)
        if ident is None:
            raise PrescriptionError(f"Идентификатор {what} «{str(value)[:40]}» не разобран")
        if ident not in итог:
            итог.append(ident)
    return tuple(итог)


def uuid_or_none(value: str | None) -> str | None:
    """Идентификатор из адреса: кривой — это «нет такого», а не ошибка базы."""
    if value is None:
        return None
    try:
        return str(uuid.UUID(str(value).strip()))
    except ValueError:
        return None


# ── Модель чтения ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class UnitRef:
    """Пиццерия предписания и её страна сейчас."""

    id: str
    name: str
    country: str | None


@dataclass(frozen=True)
class BaseRef:
    """Проверка-основание. `known` — проверка видна читающему (не отклонена, в охвате)."""

    inspection_id: str
    known: bool
    unit_name: str = ""
    inspection_date: date | None = None
    grade: str | None = None
    pct: float | None = None


@dataclass(frozen=True)
class Reply:
    """Ответ партнёра: комментарий и, если приложен, файл."""

    id: str
    comment: str
    file_name: str | None
    size_bytes: int | None
    replied_by: str
    replied_tenant: str
    replied_at: datetime


@dataclass(frozen=True)
class Event:
    """Строка истории: кто, что, когда."""

    action: str
    actor: str
    detail: str | None
    at: datetime


@dataclass(frozen=True)
class Prescription:
    """Предписание с пиццериями, основаниями, ответами и историей."""

    id: str
    country: str
    due_on: date
    recipients: str
    subject: str
    body: str
    status: str
    created_by: str
    created_at: datetime
    issued_by: str | None
    issued_at: datetime | None
    closed_by: str | None
    closed_at: datetime | None
    close_comment: str | None
    units: tuple[UnitRef, ...] = ()
    bases: tuple[BaseRef, ...] = ()
    replies: tuple[Reply, ...] = ()
    events: tuple[Event, ...] = ()

    def overdue(self, on: date) -> bool:
        return is_overdue(self.status, self.due_on, today=on)

    def state(self, on: date) -> str:
        return state_of(self.status, self.due_on, today=on)

    @property
    def whole_country(self) -> bool:
        return not self.units


@dataclass(frozen=True)
class PrescriptionList:
    """Страница списка: строки и упёрся ли он в предел (тогда это сказано на экране)."""

    rows: tuple[Prescription, ...]
    truncated: bool


@dataclass(frozen=True)
class FileRef:
    """Файл ответа к выдаче: где лежит и как назывался."""

    storage_path: str
    file_name: str
    content_type: str
    size_bytes: int


@dataclass(frozen=True)
class Choice:
    """Строка выбора в форме: пиццерия или проверка-основание."""

    id: str
    title: str
    detail: str = ""


# ── Запросы ─────────────────────────────────────────────────────────────────

# Охват предписаний — литералом `PRESCRIPTION_REACH_SQL` в каждом чтении
# (сверка `tests/test_db_reach_static.py`). Партнёр не видит черновиков: условие
# стоит в той же скобке, что и его страны, и снаружи его не обойти.
PRESCRIPTION_REACH_SQL = (
    "(%(countries)s::text[] is null or (p.country = any(%(countries)s) and p.status <> 'draft'))"
)

_COLUMNS = """p.id, p.country, p.due_on, p.recipients, p.subject, p.body, p.status,
       p.created_by, p.created_at, p.issued_by, p.issued_at, p.closed_by, p.closed_at,
       p.close_comment"""

# Очередь — только открытые; условие статуса литералом, чтобы его узнал
# частичный индекс `prescriptions_open_idx`.
_OPEN_SQL = f"""
select {_COLUMNS}
from prescriptions p
where (%(countries)s::text[] is null or (p.country = any(%(countries)s) and p.status <> 'draft'))
  and p.status <> 'closed'
  and (%(country)s::text is null or p.country = %(country)s)
order by p.due_on, p.created_at
limit %(limit)s
"""  # noqa: S608 — в склейке только имена колонок модуля, данные идут параметрами

_CLOSED_SQL = f"""
select {_COLUMNS}
from prescriptions p
where (%(countries)s::text[] is null or (p.country = any(%(countries)s) and p.status <> 'draft'))
  and p.status = 'closed'
  and (%(country)s::text is null or p.country = %(country)s)
order by p.closed_at desc
limit %(limit)s
"""  # noqa: S608

# Экран страны: отправленные и закрытые, свежие сверху; черновиков нет никому.
_COUNTRY_SQL = f"""
select {_COLUMNS}
from prescriptions p
where (%(countries)s::text[] is null or (p.country = any(%(countries)s) and p.status <> 'draft'))
  and p.status <> 'draft'
  and p.country = %(country)s
order by (p.status = 'closed'), p.due_on, p.issued_at desc
limit %(limit)s
"""  # noqa: S608

ONE_SQL = f"""
select {_COLUMNS}
from prescriptions p
where (%(countries)s::text[] is null or (p.country = any(%(countries)s) and p.status <> 'draft'))
  and p.id = %(id)s
"""  # noqa: S608

_UNITS_SQL = """
select pu.prescription_id, u.id, u.name, u.country
from prescription_units pu
join units u on u.id = pu.unit_id
where pu.prescription_id = any(%(ids)s::uuid[])
order by pu.prescription_id, u.name
"""

# Основание вне охвата или отклонённое (роль приложения его не видит, 0010)
# остаётся строкой без подробностей: «проверка отклонена или недоступна».
_BASES_SQL = """
select pi.prescription_id, pi.inspection_id, u.name, i.inspection_date, i.grade, i.pct
from prescription_inspections pi
left join inspections i on i.id = pi.inspection_id and i.retracted_at is null
left join units u on u.id = i.unit_id and (%(tenants)s::text[] is null or i.tenant_code = any(%(tenants)s)) and (%(countries)s::text[] is null or u.country = any(%(countries)s))
where pi.prescription_id = any(%(ids)s::uuid[])
order by pi.prescription_id, i.inspection_date desc nulls last
"""  # noqa: E501 — условие охвата вписано литералом целиком

_REPLIES_SQL = """
select r.prescription_id, r.id, r.comment, r.file_name, r.size_bytes, r.replied_by,
       r.replied_tenant, r.replied_at
from prescription_replies r
where r.prescription_id = any(%(ids)s::uuid[])
order by r.prescription_id, r.replied_at, r.id
"""

_EVENTS_SQL = """
select e.prescription_id, e.action, e.actor, e.detail, e.at
from prescription_events e
where e.prescription_id = any(%(ids)s::uuid[])
order by e.prescription_id, e.at, e.id
"""

_FILE_SQL = """
select r.storage_path, r.file_name, r.content_type, r.size_bytes
from prescription_replies r
join prescriptions p on p.id = r.prescription_id
where (%(countries)s::text[] is null or (p.country = any(%(countries)s) and p.status <> 'draft'))
  and r.id = %(id)s
  and r.storage_path is not null
"""

_RECIPIENTS_SQL = "select recipients from country_recipients where country = %s"

# Форма: пиццерии страны из справочника УК.
_UNIT_CHOICES_SQL = """
select u.id, u.name, coalesce(u.city, '')
from units u
where u.tenant_code = 'HQ' and (%(countries)s::text[] is null or u.country = any(%(countries)s))
  and u.country = %(country)s
order by u.name
"""

# Форма: последние принятые проверки УК страны — кандидаты в основания.
_BASE_CHOICES_SQL = """
select i.id, u.name, i.inspection_date, i.grade, i.pct
from inspections i
join units u on u.id = i.unit_id
where (%(tenants)s::text[] is null or i.tenant_code = any(%(tenants)s)) and (%(countries)s::text[] is null or u.country = any(%(countries)s))
  and i.tenant_code = 'HQ'
  and i.status = 'finalized'
  and i.retracted_at is null
  and u.country = %(country)s
order by i.inspection_date desc, u.name
limit %(limit)s
"""  # noqa: E501

# ── Чтение ──────────────────────────────────────────────────────────────────


def reach_params(reach: Reach) -> dict[str, Any]:
    """Параметры охвата предписаний. Без ограничения стран — только УК.

    Охват без стран у партнёра (`own_reach`) здесь сужается до «ничего»: он
    значит «справочник без сужения», а предписания чужих стран партнёр не
    читает ни при каком охвате. Закрыто по умолчанию.
    """
    проверенный = require_reach(reach)
    params: dict[str, Any] = dict(проверенный.params())
    if canonical_tenant(проверенный.tenant) != HQ_TENANT and params["countries"] is None:
        params["countries"] = []
    return params


def connect_read() -> psycopg.Connection[Any]:
    return psycopg.connect(check_environment().dsn)


def read_with(
    cur: psycopg.Cursor[Any], sql: str, params: dict[str, Any]
) -> tuple[Prescription, ...]:
    cur.execute(sql, params)
    heads = cur.fetchall()
    ids = [str(row[0]) for row in heads]
    side = {**params, "ids": ids}
    cur.execute(_UNITS_SQL, side)
    units = cur.fetchall()
    cur.execute(_BASES_SQL, side)
    bases = cur.fetchall()
    cur.execute(_REPLIES_SQL, side)
    replies = cur.fetchall()
    cur.execute(_EVENTS_SQL, side)
    events = cur.fetchall()
    return tuple(_assemble(row, units, bases, replies, events) for row in heads)


def _read_conn(sql: str, params: dict[str, Any]) -> tuple[Prescription, ...]:
    try:
        with connect_read() as conn, conn.cursor() as cur:
            return read_with(cur, sql, params)
    except psycopg.Error as exc:
        raise PrescriptionError(f"Не удалось прочитать предписания ({type(exc).__name__})") from exc


def _mine(rows: list[tuple[Any, ...]], ident: str) -> list[tuple[Any, ...]]:
    return [row for row in rows if str(row[0]) == ident]


def _assemble(
    head: tuple[Any, ...],
    units: list[tuple[Any, ...]],
    bases: list[tuple[Any, ...]],
    replies: list[tuple[Any, ...]],
    events: list[tuple[Any, ...]],
) -> Prescription:
    ident = str(head[0])
    return Prescription(
        id=ident,
        country=str(head[1]),
        due_on=head[2],
        recipients=str(head[3]),
        subject=str(head[4]),
        body=str(head[5]),
        status=str(head[6]),
        created_by=str(head[7]),
        created_at=head[8],
        issued_by=head[9],
        issued_at=head[10],
        closed_by=head[11],
        closed_at=head[12],
        close_comment=head[13],
        units=tuple(
            UnitRef(id=str(r[1]), name=str(r[2]), country=r[3]) for r in _mine(units, ident)
        ),
        bases=tuple(_base(r) for r in _mine(bases, ident)),
        replies=tuple(
            Reply(
                id=str(r[1]),
                comment=str(r[2]),
                file_name=r[3],
                size_bytes=None if r[4] is None else int(r[4]),
                replied_by=str(r[5]),
                replied_tenant=str(r[6]),
                replied_at=r[7],
            )
            for r in _mine(replies, ident)
        ),
        events=tuple(
            Event(action=str(r[1]), actor=str(r[2]), detail=r[3], at=r[4])
            for r in _mine(events, ident)
        ),
    )


def _base(row: tuple[Any, ...]) -> BaseRef:
    if row[2] is None:
        return BaseRef(inspection_id=str(row[1]), known=False)
    return BaseRef(
        inspection_id=str(row[1]),
        known=True,
        unit_name=str(row[2]),
        inspection_date=row[3],
        grade=row[4],
        pct=None if row[5] is None else float(row[5]),
    )


def list_prescriptions(
    *, reach: Reach, country: str | None = None, closed: bool = False
) -> PrescriptionList:
    """Открытые предписания в охвате (и стране) по сроку; `closed` — закрытые.

    Читается на одну строку больше предела: так видно, что список обрезан, и
    экран говорит об этом, а не молчит.
    """
    params = {**reach_params(reach), "country": country or None, "limit": LIST_LIMIT + 1}
    rows = _read_conn(_CLOSED_SQL if closed else _OPEN_SQL, params)
    return PrescriptionList(rows=rows[:LIST_LIMIT], truncated=len(rows) > LIST_LIMIT)


def country_prescriptions(country: str, *, reach: Reach) -> PrescriptionList:
    """Отправленные и закрытые предписания страны: действующие по сроку, закрытые ниже."""
    params = {**reach_params(reach), "country": country, "limit": LIST_LIMIT + 1}
    rows = _read_conn(_COUNTRY_SQL, params)
    return PrescriptionList(rows=rows[:LIST_LIMIT], truncated=len(rows) > LIST_LIMIT)


def get_prescription(prescription_id: str, *, reach: Reach) -> Prescription | None:
    """Предписание по id в охвате. Чужое, черновик для партнёра и несуществующее — `None`."""
    ident = uuid_or_none(prescription_id)
    if ident is None:
        return None
    found = _read_conn(ONE_SQL, {**reach_params(reach), "id": ident})
    return found[0] if found else None


def file_for_download(reply_id: str, *, reach: Reach) -> FileRef | None:
    """Файл ответа в охвате читающего. Чужой и несуществующий — одинаково `None`."""
    ident = uuid_or_none(reply_id)
    if ident is None:
        return None
    try:
        with connect_read() as conn, conn.cursor() as cur:
            cur.execute(_FILE_SQL, {"id": ident, **reach_params(reach)})
            row = cur.fetchone()
    except psycopg.Error as exc:
        raise PrescriptionError(f"Не удалось прочитать файл ответа ({type(exc).__name__})") from exc
    if row is None:
        return None
    return FileRef(
        storage_path=str(row[0]),
        file_name=str(row[1]),
        content_type=str(row[2]),
        size_bytes=int(row[3]),
    )


def fetch_file(ref: FileRef, *, storage: FileReader | None = None) -> bytes:
    """Байты файла из хранилища. Пустой объект — отказ, а не пустой файл."""
    store = storage if storage is not None else S3PhotoStorage(load_storage_settings())
    data = store.get(key_of_uri(ref.storage_path))
    if not data:
        raise StorageError(f"Хранилище отдало пустой объект вместо ответа: {ref.storage_path}")
    return data


def remembered_recipients(country: str) -> str:
    """Адресаты, запомненные для страны на последней отправке (D275), или пусто."""
    try:
        with connect_read() as conn, conn.cursor() as cur:
            cur.execute(_RECIPIENTS_SQL, (country,))
            row = cur.fetchone()
    except psycopg.Error as exc:
        raise PrescriptionError(
            f"Не удалось прочитать адресатов страны ({type(exc).__name__})"
        ) from exc
    return "" if row is None else str(row[0])


def choices(country: str, *, reach: Reach) -> tuple[tuple[Choice, ...], tuple[Choice, ...]]:
    """Пиццерии страны и последние принятые проверки УК — для формы предписания."""
    params = {**require_reach(reach).params(), "country": country, "limit": BASES_LIMIT}
    try:
        with connect_read() as conn, conn.cursor() as cur:
            cur.execute(_UNIT_CHOICES_SQL, params)
            units = cur.fetchall()
            cur.execute(_BASE_CHOICES_SQL, params)
            bases = cur.fetchall()
    except psycopg.Error as exc:
        raise PrescriptionError(
            f"Не удалось прочитать пиццерии страны ({type(exc).__name__})"
        ) from exc
    return (
        tuple(Choice(id=str(r[0]), title=str(r[1]), detail=str(r[2])) for r in units),
        tuple(
            Choice(
                id=str(r[0]),
                title=f"{r[1]} · {r[2]}",
                detail=" ".join(
                    part
                    for part in (str(r[3] or ""), "" if r[4] is None else f"{float(r[4]):.1f}%")
                    if part
                ),
            )
            for r in bases
        ),
    )
