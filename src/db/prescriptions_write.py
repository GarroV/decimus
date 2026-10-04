"""Предписания: запись — черновик, отправка, закрытие (УК) и ответ партнёра (волна 3).

Чтение, модель и правила — `src/db/prescriptions.py`; здесь двери записи.
Черновик, связи, отправка и закрытие идут ролью администратора истории, ответ —
ролью приложения. Что кому можно, держит база (`0037`); здесь — понятные
человеку отказы до похода в базу.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

import psycopg

from src.domain.tenants import HQ_TENANT, canonical_tenant

from .action_plans import clean_file_name
from .config import load_retraction_settings, load_storage_settings
from .errors import IssuedDraftLostError, PrescriptionError, StorageError
from .prescriptions import (
    ONE_SQL,
    STATUS_DRAFT,
    STATUS_ISSUED,
    Draft,
    Prescription,
    check_draft,
    connect_read,
    reach_params,
    read_with,
    today,
    uuid_or_none,
)
from .reach import Reach
from .storage import PhotoStorage, S3PhotoStorage

logger = logging.getLogger(__name__)

#: Префикс файлов в хранилище кадров (D268): удаление кадров после вычитки
#: (D202) ходит по `inspections/`, сюда не заглядывает.
STORAGE_PREFIX = "prescriptions"
DEFAULT_CONTENT_TYPE = "application/octet-stream"
MAX_CONTENT_TYPE = 255
MAX_REPLY = 4_000
MAX_COMMENT = 2_000

_INSERT_SQL = """
insert into prescriptions (country, due_on, recipients, subject, body, created_by)
values (%(country)s, %(due_on)s, %(recipients)s, %(subject)s, %(body)s, %(actor)s)
returning id
"""

_INSERT_UNIT_SQL = "insert into prescription_units (prescription_id, unit_id) values (%s, %s)"
_INSERT_BASE_SQL = (
    "insert into prescription_inspections (prescription_id, inspection_id) values (%s, %s)"
)
_DELETE_UNITS_SQL = "delete from prescription_units where prescription_id = %s"
_DELETE_BASES_SQL = "delete from prescription_inspections where prescription_id = %s"
_LOCK_SQL = "select status, country from prescriptions where id = %s for update"
_SIGN_SQL = "select set_config('decimus.prescription_actor', %s, true)"
_UPDATE_SQL = """
update prescriptions
set due_on = %(due_on)s, recipients = %(recipients)s, subject = %(subject)s, body = %(body)s
where id = %(id)s
"""
_ISSUE_SQL = "update prescriptions set status = 'issued', issued_by = %(actor)s where id = %(id)s"
_CLOSE_SQL = """
update prescriptions
set status = 'closed', closed_by = %(actor)s, close_comment = %(comment)s
where id = %(id)s
"""

# Ответ: статус предписания в охвате отвечающего, охват — тем же литералом.
# Замка нет: `for update` требует права UPDATE, которого у роли приложения нет
# и быть не должно. Гонку с закрытием держит триггер вставки ответа (0037).
_HEAD_FOR_REPLY_SQL = """
select p.status
from prescriptions p
where (%(countries)s::text[] is null or (p.country = any(%(countries)s) and p.status <> 'draft'))
  and p.id = %(id)s
"""

_INSERT_REPLY_SQL = """
insert into prescription_replies
    (id, prescription_id, comment, storage_path, file_name, size_bytes, content_type,
     replied_by, replied_tenant)
values
    (%(id)s, %(prescription_id)s, %(comment)s, %(storage_path)s, %(file_name)s, %(size_bytes)s,
     %(content_type)s, %(replied_by)s, %(replied_tenant)s)
"""


# ── Запись: двери УК (администратор истории) ───────────────────────────────


def _actor(actor: str) -> str:
    value = (actor or "").strip()
    if not value:
        raise PrescriptionError("Не назван, кто действует: в истории каждое действие подписано")
    return value


def _admin(what: str) -> psycopg.Connection[Any]:
    try:
        return psycopg.connect(load_retraction_settings().dsn)
    except psycopg.Error as exc:
        raise PrescriptionError(f"{what}: база не на связи ({type(exc).__name__})") from exc


def _translate(what: str, exc: psycopg.Error) -> PrescriptionError:
    # Тип, а не текст драйвера: в тексте бывает адрес базы, а отказ — на экране.
    # Отказ триггера — исключение: его текст написан для человека (0037).
    if isinstance(exc, psycopg.errors.RaiseException | psycopg.errors.CheckViolation):
        причина = getattr(exc.diag, "message_primary", None) or type(exc).__name__
        return PrescriptionError(f"{what} не удалось: {причина}. Ничего не изменено")
    return PrescriptionError(f"{what} не удалось ({type(exc).__name__}). Ничего не изменено")


def _links(cur: psycopg.Cursor[Any], ident: str, draft: Draft) -> None:
    for unit_id in draft.unit_ids:
        cur.execute(_INSERT_UNIT_SQL, (ident, unit_id))
    for inspection_id in draft.inspection_ids:
        cur.execute(_INSERT_BASE_SQL, (ident, inspection_id))


def create_draft(draft: Draft, *, actor: str) -> str:
    """Завести черновик предписания. Возвращает его id."""
    who = _actor(actor)
    чистый = check_draft(draft, on=today())
    try:
        with _admin("Сохранить предписание") as conn, conn.cursor() as cur:
            cur.execute(
                _INSERT_SQL,
                {
                    "country": чистый.country,
                    "due_on": чистый.due_on,
                    "recipients": чистый.recipients,
                    "subject": чистый.subject,
                    "body": чистый.body,
                    "actor": who,
                },
            )
            row = cur.fetchone()
            if row is None:
                raise PrescriptionError("Предписание не легло в базу")
            ident = str(row[0])
            _links(cur, ident, чистый)
            conn.commit()
            return ident
    except psycopg.Error as exc:
        raise _translate("Сохранить предписание", exc) from exc


def _locked(cur: psycopg.Cursor[Any], ident: str) -> tuple[str, str]:
    cur.execute(_LOCK_SQL, (ident,))
    row = cur.fetchone()
    if row is None:
        raise PrescriptionError("Предписания нет")
    return str(row[0]), str(row[1])


def update_draft(prescription_id: str, draft: Draft, *, actor: str) -> None:
    """Поправить черновик. Отправленное не правится — его закрывают и составляют новое."""
    who = _actor(actor)
    ident = uuid_or_none(prescription_id)
    if ident is None:
        raise PrescriptionError("Предписания нет")
    try:
        with _admin("Сохранить предписание") as conn, conn.cursor() as cur:
            статус, страна = _locked(cur, ident)
            if статус != STATUS_DRAFT:
                raise PrescriptionError(
                    "Предписание уже отправлено — оно не правится. Закройте его с "
                    "комментарием и составьте новое"
                )
            чистый = check_draft(replace(draft, country=страна), on=today())
            cur.execute(_SIGN_SQL, (who,))
            cur.execute(
                _UPDATE_SQL,
                {
                    "id": ident,
                    "due_on": чистый.due_on,
                    "recipients": чистый.recipients,
                    "subject": чистый.subject,
                    "body": чистый.body,
                },
            )
            cur.execute(_DELETE_UNITS_SQL, (ident,))
            cur.execute(_DELETE_BASES_SQL, (ident,))
            _links(cur, ident, чистый)
            conn.commit()
    except psycopg.Error as exc:
        raise _translate("Сохранить предписание", exc) from exc


#: Кладёт письмо черновиком в почту сотрудника. Даёт веб; база о Gmail не знает.
PutDraft = Callable[[Prescription], None]


def issue(prescription_id: str, *, actor: str, put_draft: PutDraft) -> Prescription:
    """Положить письмо черновиком в почту сотрудника и отметить предписание «действует».

    Под замком строки: письмо собирается из того, что лежит в базе, и в той
    же транзакции предписание фиксируется — между ними текст поменяться не
    может. Не легло в почту (`put_draft` бросил) — откат, предписание остаётся
    черновиком. Легло, а отметка не легла — `IssuedDraftLostError`: в почте
    лежит черновик, который надо удалить.
    """
    who = _actor(actor)
    ident = uuid_or_none(prescription_id)
    if ident is None:
        raise PrescriptionError("Предписания нет")
    with _admin("Отправить предписание") as conn:
        try:
            cur = conn.cursor()
            статус = _locked(cur, ident)[0]
            if статус != STATUS_DRAFT:
                raise PrescriptionError("Предписание уже отправлено")
            found = read_with(cur, ONE_SQL, {"countries": None, "tenants": None, "id": ident})
            предписание = found[0]
            if not предписание.recipients.strip():
                raise PrescriptionError("Нет адресатов — впишите хотя бы один адрес")
            if предписание.due_on < today():
                raise PrescriptionError("Срок уже прошёл — поправьте его в черновике")
        except psycopg.Error as exc:
            raise _translate("Отправить предписание", exc) from exc
        put_draft(предписание)
        try:
            cur.execute(_ISSUE_SQL, {"id": ident, "actor": who})
            conn.commit()
        except psycopg.Error as exc:
            logger.warning("предписание %s: черновик в почте лёг, отметка нет: %s", ident, exc)
            raise IssuedDraftLostError(
                f"Черновик письма лёг в вашу почту, но предписание не отмечено отправленным: "
                f"{_translate('Отправить предписание', exc)}. Удалите этот черновик из почты, "
                f"поправьте предписание и отправьте снова"
            ) from exc
    return предписание


def close(prescription_id: str, *, actor: str, comment: str) -> None:
    """Закрыть действующее предписание с обязательным комментарием."""
    who = _actor(actor)
    текст = (comment or "").strip()
    if not текст:
        raise PrescriptionError("Закрывают с комментарием: выполнено или снято и почему")
    if len(текст) > MAX_COMMENT:
        raise PrescriptionError(f"Комментарий длиннее {MAX_COMMENT} знаков")
    ident = uuid_or_none(prescription_id)
    if ident is None:
        raise PrescriptionError("Предписания нет")
    try:
        with _admin("Закрыть предписание") as conn, conn.cursor() as cur:
            статус = _locked(cur, ident)[0]
            if статус != STATUS_ISSUED:
                raise PrescriptionError(
                    "Закрыть можно только действующее предписание"
                    if статус == STATUS_DRAFT
                    else "Предписание уже закрыто"
                )
            cur.execute(_CLOSE_SQL, {"id": ident, "actor": who, "comment": текст})
            conn.commit()
    except psycopg.Error as exc:
        raise _translate("Закрыть предписание", exc) from exc


# ── Запись: ответ партнёра (роль приложения) ───────────────────────────────


@dataclass(frozen=True)
class Attachment:
    """Файл ответа, как его прислал браузер."""

    name: str
    content_type: str
    data: bytes


def _clean_content_type(raw: str) -> str:
    value = "".join(ch for ch in (raw or "") if ch.isprintable()).strip()
    return value[:MAX_CONTENT_TYPE] or DEFAULT_CONTENT_TYPE


def object_key(prescription_id: str, reply_id: str) -> str:
    """Ключ файла ответа в хранилище — только идентификаторы."""
    return f"{STORAGE_PREFIX}/{prescription_id}/{reply_id}"


def reply(
    prescription_id: str,
    *,
    reach: Reach,
    tenant: str,
    actor: str,
    comment: str,
    attachment: Attachment | None,
    max_bytes: int,
    storage: PhotoStorage | None = None,
) -> str:
    """Ответ партнёра на действующее предписание своей страны. Возвращает id ответа.

    Чужое предписание отвечает «нет», как несуществующее. Что отвечает только
    партнёр этой страны и только на действующее — держит ещё и триггер.
    """
    who = _actor(actor)
    текст = (comment or "").strip()
    if not текст:
        raise PrescriptionError("Напишите комментарий: что сделано")
    if len(текст) > MAX_REPLY:
        raise PrescriptionError(f"Комментарий длиннее {MAX_REPLY} знаков")
    if canonical_tenant(tenant) == HQ_TENANT:
        raise PrescriptionError("На предписание отвечает партнёр страны, а не УК")
    ident = uuid_or_none(prescription_id)
    if ident is None:
        raise PrescriptionError("Предписания нет")
    reply_id = str(uuid.uuid4())
    row: dict[str, Any] = {
        "id": reply_id,
        "prescription_id": ident,
        "comment": текст,
        "storage_path": None,
        "file_name": None,
        "size_bytes": None,
        "content_type": None,
        "replied_by": who,
        "replied_tenant": canonical_tenant(tenant),
    }
    if attachment is None:
        _record_reply(ident, reach=reach, row=row)
        return reply_id
    if not attachment.data:
        raise PrescriptionError("Файл пустой — класть нечего")
    if len(attachment.data) > max_bytes:
        raise PrescriptionError(
            f"Файл больше предела {max_bytes // (1024 * 1024)} МБ (ATTACHMENT_MAX_MB)"
        )
    store = storage if storage is not None else S3PhotoStorage(load_storage_settings())
    key = object_key(ident, reply_id)
    тип = _clean_content_type(attachment.content_type)
    # Файл кладётся ДО транзакции, как у экшн-планов: заливка не держит замок.
    # Строка не легла — объект убирается.
    uri = store.put(key, attachment.data, content_type=тип)
    try:
        _record_reply(
            ident,
            reach=reach,
            row={
                **row,
                "storage_path": uri,
                "file_name": clean_file_name(attachment.name),
                "size_bytes": len(attachment.data),
                "content_type": тип,
            },
        )
    except PrescriptionError:
        _drop_orphan(store, key)
        raise
    return reply_id


def _record_reply(ident: str, *, reach: Reach, row: dict[str, Any]) -> None:
    try:
        with connect_read() as conn, conn.cursor() as cur:
            cur.execute(_HEAD_FOR_REPLY_SQL, {"id": ident, **reach_params(reach)})
            head = cur.fetchone()
            if head is None:
                raise PrescriptionError("Предписания нет")
            if head[0] != STATUS_ISSUED:
                raise PrescriptionError("Предписание закрыто — ответ к нему не кладут")
            cur.execute(_INSERT_REPLY_SQL, row)
            conn.commit()
    except psycopg.Error as exc:
        raise _translate("Ответить на предписание", exc) from exc


def _drop_orphan(store: PhotoStorage, key: str) -> None:
    """Убрать объект, строка которого не легла. Не вышло — в журнал, а не молча."""
    try:
        store.delete(key)
    except StorageError as exc:
        logger.warning("объект %s без строки в базе не убран: %s", key, exc)
