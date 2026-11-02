"""Country partner contacts and inspection mail recipients; HQ-only personal data."""

from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime
from email.errors import HeaderParseError
from email.headerregistry import Address

import psycopg

from .config import load_retraction_settings
from .errors import DbError, PrescriptionError
from .pool import connection
from .prescriptions import parse_recipients
from .reach import Reach, require_reach
from .reading import reading
from .space import SYSTEM_SPACE, current_space

PARTNER = "partner"
MAILING = "mailing"
KINDS = (PARTNER, MAILING)


class ContactError(DbError):
    """A stable error code; never include an address or driver message in logs."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class Fields:
    kind: str
    name: str = ""
    email: str = ""


@dataclass(frozen=True)
class Contact:
    id: str
    country: str
    kind: str
    name: str
    email: str
    updated_at: datetime


def clean(fields: Fields) -> Fields:
    """A partner may have a name only; each mailing row needs one real address."""
    if fields.kind not in KINDS:
        raise ContactError("invalid")
    name = " ".join(fields.name.split())
    if len(name) > 200 or any(unicodedata.category(c) == "Cc" for c in fields.name):
        raise ContactError("invalid")
    raw = fields.email.strip()
    if len(raw) > 254 or any(unicodedata.category(c) == "Cc" for c in fields.email):
        raise ContactError("invalid_email")
    if raw:
        try:
            normalized = parse_recipients(raw)
            address = Address(addr_spec=normalized)
            if "," in normalized or not address.username or not address.domain:
                raise ValueError("one address is required")
            if address.addr_spec != normalized:
                raise ValueError("address expressions are not allowed")
        except (PrescriptionError, HeaderParseError, ValueError, IndexError) as exc:
            raise ContactError("invalid_email") from exc
    if not name and not raw:
        raise ContactError("empty")
    if fields.kind == MAILING and not raw:
        raise ContactError("email_required")
    return Fields(fields.kind, name, raw)


def _country(raw: str) -> str:
    code = raw.strip().upper()
    if re.fullmatch(r"[A-Z]{2}", code) is None:
        raise ContactError("invalid")
    return code


def _id(raw: str) -> str:
    try:
        return str(uuid.UUID(raw))
    except ValueError as exc:
        raise ContactError("missing") from exc


_SELECT = "select id, country, kind, name, email, updated_at from country_contacts "


def for_country(country: str) -> tuple[Contact, ...]:
    """Read only through app-role RLS; a partner space cannot see these contacts."""
    with reading("country contacts") as conn:
        rows = conn.execute(
            _SELECT + "where country = %s order by created_at, id", (_country(country),)
        ).fetchall()
    return tuple(Contact(str(r[0]), r[1], r[2], r[3], r[4], r[5]) for r in rows)


def partner_names() -> dict[str, tuple[str, ...]]:
    """Country list labels in one query; access-space names are not contact names."""
    with reading("country partner names") as conn:
        rows = conn.execute(
            "select country, name, email from country_contacts where kind = 'partner' "
            "order by country, created_at, id"
        ).fetchall()
    result: dict[str, tuple[str, ...]] = {}
    for country, name, email in rows:
        result[country] = (*result.get(country, ()), name or email)
    return result


def _may_write() -> None:
    # The admin connection is trusted, but never cross a caller's partner-space context.
    if current_space() not in (None, SYSTEM_SPACE, "HQ"):
        raise ContactError("forbidden")


def save(country: str, fields: Fields, *, actor: str, ident: str = "") -> str:
    _may_write()
    code = _country(country)
    value = clean(fields)
    if not actor.strip():
        raise ContactError("invalid")
    params = (value.name, value.email, actor, code, value.kind)
    try:
        with connection(load_retraction_settings().dsn) as conn:
            if ident:
                row = conn.execute(
                    "update country_contacts set name=%s, email=%s, updated_by=%s, "
                    "updated_at=now() where country=%s and kind=%s and id=%s::uuid returning id",
                    (*params, _id(ident)),
                ).fetchone()
            else:
                row = conn.execute(
                    "insert into country_contacts(name,email,updated_by,country,kind) "
                    "values (%s,%s,%s,%s,%s) returning id",
                    params,
                ).fetchone()
            if row is None:
                raise ContactError("missing")
            return str(row[0])
    except psycopg.errors.UniqueViolation as exc:
        raise ContactError("duplicate") from exc
    except psycopg.Error as exc:
        raise ContactError("unavailable") from exc


def delete(country: str, ident: str, *, actor: str) -> None:
    _may_write()
    if not actor.strip():
        raise ContactError("invalid")
    try:
        with connection(load_retraction_settings().dsn) as conn:
            row = conn.execute(
                "delete from country_contacts where country=%s and id=%s::uuid returning id",
                (_country(country), _id(ident)),
            ).fetchone()
            if row is None:
                raise ContactError("missing")
    except psycopg.Error as exc:
        raise ContactError("unavailable") from exc


_INSPECTION_RECIPIENTS = """
select c.email from inspections i
join units u on u.id = i.unit_id
join country_contacts c on c.country = u.country and c.kind = 'mailing'
where i.id = %(inspection)s::uuid
  and (%(tenants)s::text[] is null or i.tenant_code = any(%(tenants)s))
  and (%(countries)s::text[] is null or u.country = any(%(countries)s))
order by c.created_at, c.id
"""


def recipients_for_inspection(inspection: str, *, reach: Reach) -> str:
    """Resolve country by inspection/unit IDs, never by translated unit names."""
    scope = require_reach(reach)
    with reading("inspection country recipients") as conn:
        rows = conn.execute(
            _INSPECTION_RECIPIENTS, {**scope.params(), "inspection": _id(inspection)}
        ).fetchall()
    return ", ".join(str(row[0]) for row in rows)
