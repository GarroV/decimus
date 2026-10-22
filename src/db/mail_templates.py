"""Версии шаблонов писем и документов (0089, D601, D608).

Версия только добавляется: прежняя не правится и не удаляется, предписание
помнит, по какой версии собрано. Читает роль приложения (из пространства УК —
в шаблоне бывают реальные реквизиты франчайзора), пишет администратор истории.

Предписание по проверке берёт последнюю версию вида `prescription_inspection` на
английском (D601). Версии в базе нет — встроенный обезличенный шаблон из
репозитория кладётся первой версией (`ensure_latest`), чтобы предписание помнило
точный текст, по которому собрано, даже когда встроенный потом изменится.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg

from .config import check_environment, load_retraction_settings
from .errors import PrescriptionError
from .pool import connection

KINDS = (
    "inspection_letter",
    "prescription_inspection",
    "prescription_ratings",
    "prescription_other",
    "action_plan",
)
MAX_BODY = 100_000
#: Подпись автора версии, когда её кладёт сама система (встроенный шаблон).
SYSTEM_ACTOR = "system:builtin"

_COLUMNS = "id, kind, lang, version, body, created_by, created_at"
_LATEST_SQL = f"""
select {_COLUMNS} from mail_templates
where kind = %s and lang = %s
order by version desc limit 1
"""  # noqa: S608 — в склейке только имена колонок модуля
_ONE_SQL = f"select {_COLUMNS} from mail_templates where id = %s"  # noqa: S608
_ALL_SQL = f"""
select {_COLUMNS} from mail_templates
where kind = %s and lang = %s order by version desc
"""  # noqa: S608
_INSERT_SQL = """
insert into mail_templates (kind, lang, version, body, created_by)
values (%s, %s, %s, %s, %s)
returning id, kind, lang, version, body, created_by, created_at
"""
_LOCK_SQL = "select pg_advisory_xact_lock(hashtextextended(%s, 0))"
_NEXT_SQL = "select coalesce(max(version), 0) + 1 from mail_templates where kind = %s and lang = %s"


@dataclass(frozen=True)
class TemplateVersion:
    """Одна версия шаблона."""

    id: str
    kind: str
    lang: str
    version: int
    body: str
    created_by: str
    created_at: datetime


def _row(row: tuple[Any, ...]) -> TemplateVersion:
    return TemplateVersion(
        id=str(row[0]),
        kind=str(row[1]),
        lang=str(row[2]),
        version=int(row[3]),
        body=str(row[4]),
        created_by=str(row[5]),
        created_at=row[6],
    )


def _check_kind(kind: str, lang: str) -> None:
    if kind not in KINDS:
        raise PrescriptionError(f"Вид шаблона «{kind}» неизвестен: {', '.join(KINDS)}")
    if len(lang) != 2 or not lang.isalpha() or not lang.islower():
        raise PrescriptionError(f"Язык шаблона «{lang}» — две строчные латинские буквы")


def _read(sql: str, params: tuple[Any, ...]) -> list[tuple[Any, ...]]:
    try:
        with connection(check_environment().dsn) as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    except psycopg.Error as exc:
        raise PrescriptionError(f"Не удалось прочитать шаблон ({type(exc).__name__})") from exc


def latest(kind: str, lang: str) -> TemplateVersion | None:
    """Последняя версия вида и языка, или `None`, если в базе её ещё нет."""
    _check_kind(kind, lang)
    rows = _read(_LATEST_SQL, (kind, lang))
    return _row(rows[0]) if rows else None


def versions(kind: str, lang: str) -> tuple[TemplateVersion, ...]:
    """Все версии вида и языка, свежие первыми."""
    _check_kind(kind, lang)
    return tuple(_row(r) for r in _read(_ALL_SQL, (kind, lang)))


def get(version_id: str | None) -> TemplateVersion | None:
    """Версия по идентификатору; кривой и несуществующий — `None`."""
    if not version_id:
        return None
    try:
        ident = str(uuid.UUID(str(version_id)))
    except ValueError:
        return None
    rows = _read(_ONE_SQL, (ident,))
    return _row(rows[0]) if rows else None


def add_in(
    cur: psycopg.Cursor[Any], kind: str, lang: str, body: str, actor: str
) -> TemplateVersion:
    """Добавить следующую версию на чужом курсоре (в транзакции вызывающего)."""
    _check_kind(kind, lang)
    текст = body
    if not текст.strip():
        raise PrescriptionError("Текст шаблона пуст")
    if len(текст) > MAX_BODY:
        raise PrescriptionError(f"Шаблон длиннее {MAX_BODY} знаков")
    cur.execute(_LOCK_SQL, (f"mail_templates:{kind}:{lang}",))
    cur.execute(_NEXT_SQL, (kind, lang))
    found = cur.fetchone()
    номер = int(found[0]) if found else 1
    cur.execute(_INSERT_SQL, (kind, lang, номер, текст, actor))
    created = cur.fetchone()
    if created is None:
        raise PrescriptionError("Версия шаблона не легла в базу")
    return _row(created)


def ensure_latest(cur: psycopg.Cursor[Any], kind: str, lang: str, builtin: str) -> TemplateVersion:
    """Последняя версия на чужом курсоре; нет ни одной — встроенный текст первой версией."""
    _check_kind(kind, lang)
    cur.execute(_LOCK_SQL, (f"mail_templates:{kind}:{lang}",))
    cur.execute(_LATEST_SQL, (kind, lang))
    found = cur.fetchone()
    if found is not None:
        return _row(found)
    return add_in(cur, kind, lang, builtin, SYSTEM_ACTOR)


def add_version(kind: str, lang: str, body: str, *, actor: str) -> TemplateVersion:
    """Загрузить новую версию (`tools/prescription_template.py`). Роль — администратор истории."""
    who = (actor or "").strip()
    if not who:
        raise PrescriptionError("Не назван, кто загружает шаблон: версия подписывается")
    try:
        with psycopg.connect(load_retraction_settings().dsn) as conn, conn.cursor() as cur:
            return add_in(cur, kind, lang, body, who)
    except psycopg.Error as exc:
        raise PrescriptionError(
            f"Шаблон не сохранён ({type(exc).__name__}). Ничего не изменено"
        ) from exc
