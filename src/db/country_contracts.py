"""Договор страны: юрлицо партнёра, договор одной строкой, контакты по ДКК (0088, D603).

ДКК в системе не моделируется: название и дата договора — свободный текст. Из
таблицы нужно одно живое поле — `dkk_emails`: форма предписания подставляет его в
«Кому» (`dkk_recipients`). Читает роль приложения (из пространства УК, политика
`0088`), пишет администратор истории; кто из УК вправе писать, решает веб
(`contract.manage`), база видит лишь подпись `updated_by`.

Почты уходят в заголовок письма, поэтому приводятся к виду «a@x.ge, b@y.ge» здесь
(`normalize_emails`) и проверяются ещё раз базой.
"""

from __future__ import annotations

import logging
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg

from .config import check_environment, load_retraction_settings
from .errors import CountryContractError, PrescriptionError
from .pool import connection
from .prescriptions import parse_recipients

logger = logging.getLogger(__name__)

#: Пределы полей — как CHECK в `0088`; экран подрезает по тем же числам.
LIMITS: dict[str, int] = {
    "legal_name": 200,
    "registration_country": 100,
    "company_number": 60,
    "address": 300,
    "agreement": 300,
    "dkk_emails": 2000,
}
#: Однострочные текстовые поля договора, в порядке показа.
TEXT_FIELDS = ("legal_name", "registration_country", "company_number", "address", "agreement")

_SELECT_SQL = """
select id, country, legal_name, registration_country, company_number, address, agreement,
       dkk_emails, updated_by, updated_at
from country_contracts
where country = %s
order by created_at, id
"""
_INSERT_SQL = """
insert into country_contracts (country, legal_name, registration_country, company_number,
                               address, agreement, dkk_emails, updated_by)
values (%(country)s, %(legal_name)s, %(registration_country)s, %(company_number)s,
        %(address)s, %(agreement)s, %(dkk_emails)s, %(actor)s)
"""
_UPDATE_SQL = """
update country_contracts
set legal_name = %(legal_name)s, registration_country = %(registration_country)s,
    company_number = %(company_number)s, address = %(address)s, agreement = %(agreement)s,
    dkk_emails = %(dkk_emails)s, updated_by = %(actor)s, updated_at = now()
where id = %(id)s and country = %(country)s
"""
_DELETE_SQL = "delete from country_contracts where id = %s and country = %s"


@dataclass(frozen=True)
class Contract:
    """Одна строка договора страны."""

    id: str
    country: str
    legal_name: str = ""
    registration_country: str = ""
    company_number: str = ""
    address: str = ""
    agreement: str = ""
    dkk_emails: str = ""
    updated_by: str = ""
    updated_at: datetime | None = None


@dataclass(frozen=True)
class ContractFields:
    """Что вписал человек: те же поля без id и подписи."""

    legal_name: str = ""
    registration_country: str = ""
    company_number: str = ""
    address: str = ""
    agreement: str = ""
    dkk_emails: str = ""


def _one_line(value: str) -> str:
    """Пробелы и переносы схлопываются в один пробел; прочие управляющие знаки — отказ."""
    text = " ".join((value or "").split())
    if any(unicodedata.category(ch) == "Cc" for ch in text):
        raise CountryContractError("В тексте договора есть недопустимые управляющие знаки")
    return text


def normalize_emails(raw: str) -> str:
    """Почты через запятую, точку с запятой или строку → «a@x.ge, b@y.ge».

    Кривой адрес — отказ с его текстом, а не тихий пропуск. Управляющие знаки внутри
    адреса (кроме переводов строк-разделителей) — отказ: адрес уходит в заголовок `To:`.
    """
    try:
        итог = parse_recipients(raw)
    except PrescriptionError as exc:
        raise CountryContractError(str(exc)) from exc
    if any(unicodedata.category(ch) == "Cc" for ch in итог):
        raise CountryContractError("В адресе почты есть недопустимые управляющие знаки")
    return итог


def clean(fields: ContractFields) -> ContractFields:
    """Привести ввод к виду, который принимает база; нарушение — `CountryContractError`."""
    значения: dict[str, str] = {name: _one_line(getattr(fields, name)) for name in TEXT_FIELDS}
    значения["dkk_emails"] = normalize_emails(fields.dkk_emails)
    for name, предел in LIMITS.items():
        if len(значения[name]) > предел:
            raise CountryContractError(f"Поле слишком длинное: не больше {предел} знаков")
    if not any(значения.values()):
        raise CountryContractError("Заполните хотя бы одно поле договора")
    return ContractFields(**значения)


def read(country: str) -> tuple[Contract, ...]:
    """Строки договора страны в порядке заведения. Не прочиталось — `CountryContractError`."""
    try:
        with connection(check_environment().dsn) as conn, conn.cursor() as cur:
            cur.execute(_SELECT_SQL, (country,))
            rows = cur.fetchall()
    except psycopg.Error as exc:
        raise CountryContractError(
            f"Не удалось прочитать договор страны ({type(exc).__name__})"
        ) from exc
    return tuple(
        Contract(
            id=str(r[0]),
            country=str(r[1]),
            legal_name=str(r[2]),
            registration_country=str(r[3]),
            company_number=str(r[4]),
            address=str(r[5]),
            agreement=str(r[6]),
            dkk_emails=str(r[7]),
            updated_by=str(r[8]),
            updated_at=r[9],
        )
        for r in rows
    )


def dkk_recipients(country: str) -> str:
    """Контакты по ДКК страны одной строкой «Кому»: все строки договора, без повторов, или пусто."""
    адреса: list[str] = []
    for строка in read(country):
        for адрес in (a for a in строка.dkk_emails.split(", ") if a):
            if адрес.lower() not in (x.lower() for x in адреса):
                адреса.append(адрес)
    return ", ".join(адреса)


def _admin() -> psycopg.Connection[Any]:
    try:
        return psycopg.connect(load_retraction_settings().dsn)
    except psycopg.Error as exc:
        raise CountryContractError(
            f"Договор страны не сохранён: база не на связи ({type(exc).__name__})"
        ) from exc


def _actor(actor: str) -> str:
    value = (actor or "").strip()
    if not value:
        raise CountryContractError("Не назван, кто правит договор: запись подписывается")
    return value


def _run(sql: str, params: dict[str, Any] | tuple[Any, ...], *, must_hit: bool) -> None:
    try:
        with _admin() as conn:
            hit = conn.execute(sql, params).rowcount
    except psycopg.errors.IntegrityError as exc:
        raise CountryContractError("Договор не сохранён: база отказала в значении поля") from exc
    except psycopg.Error as exc:
        raise CountryContractError(
            f"Договор страны не сохранён ({type(exc).__name__}). Ничего не изменено"
        ) from exc
    if must_hit and not hit:
        raise CountryContractError("Такой строки договора в этой стране нет")


def save(
    country: str, fields: ContractFields, *, actor: str, contract_id: str | None = None
) -> None:
    """Завести строку договора страны или (с `contract_id`) поправить существующую."""
    чистые = clean(fields)
    params: dict[str, Any] = {
        "country": country,
        "actor": _actor(actor),
        **{name: getattr(чистые, name) for name in (*TEXT_FIELDS, "dkk_emails")},
    }
    if contract_id is None:
        _run(_INSERT_SQL, params, must_hit=False)
        return
    try:
        params["id"] = str(uuid.UUID(contract_id))
    except ValueError as exc:
        raise CountryContractError("Такой строки договора в этой стране нет") from exc
    _run(_UPDATE_SQL, params, must_hit=True)


def remove(country: str, contract_id: str) -> None:
    """Снять строку договора страны."""
    try:
        ident = str(uuid.UUID(contract_id))
    except ValueError as exc:
        raise CountryContractError("Такой строки договора в этой стране нет") from exc
    _run(_DELETE_SQL, (ident, country), must_hit=True)
