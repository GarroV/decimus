"""Люди и партнёры открытого демо: учётки с почтой и ролями, партнёры стран.

Без этого «Люди и доступ» в демо — четыре технические учётки без почты, «Партнёры» на
странице страны пусты. Всё пишется дверями продукта:
`web_access` (учётки), `unit_profiles` (свод пиццерий, откуда страница страны берёт
партнёра).

Имена — те же, что в проверках и рейтингах демо (Olivia Hart, Marco Bianchi, Lena Novak,
Nina Petrosyan): человек на экране «Люди» тот же, кто подписан под проверкой. Почты и
имена партнёров выдуманные, домен `example.com` зарезервирован под примеры: писем никому не уйдёт.
Каждая функция повторима на той же базе — готовое пропускает.
"""

from __future__ import annotations

import secrets
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import open_demo_ratings
import psycopg

from src.db import unit_profiles
from src.db.space import apply_space
from src.db.web_access import create_account, find_by_login, set_email, set_name_latin
from src.domain.demo import DEMO_PARTNER_TENANT, DEMO_ROLES
from src.domain.tenants import HQ_TENANT
from src.ratings.svod import normalize

EMAIL_DOMAIN = "example.com"


@dataclass(frozen=True)
class Person:
    login: str
    name: str
    tenant: str
    role: str


#: Люди сверх четырёх ролей входа `/demo`: развилка ролей УК и сотрудники партнёра.
EXTRA_PEOPLE = (
    Person("nina.petrosyan", "Nina Petrosyan", HQ_TENANT, "developer"),
    Person("tom.walker", "Tom Walker", HQ_TENANT, "admin"),
    Person("daniel.reyes", "Daniel Reyes", HQ_TENANT, "control"),
    Person("priya.shah", "Priya Shah", HQ_TENANT, "osb"),
    Person("ivan.kovacs", "Ivan Kovacs", DEMO_PARTNER_TENANT, "auditor"),
    Person("mia.horvat", "Mia Horvat", DEMO_PARTNER_TENANT, "auditor"),
)


def email_of(name: str) -> str:
    return f"{name.lower().replace(' ', '.')}@{EMAIL_DOMAIN}"


def seed_people() -> int:
    """Почта и имя у учёток ролей входа, плюс остальные люди. Возвращает, сколько человек в демо."""
    everyone = [Person(r.login, r.name, r.tenant, r.role) for r in DEMO_ROLES] + list(EXTRA_PEOPLE)
    for person in everyone:
        if find_by_login(person.login) is None:
            create_account(
                person.login,
                tenant=person.tenant,
                password=secrets.token_urlsafe(24),
                role=person.role,
            )
        if not set_email(person.login, tenant=person.tenant, email=email_of(person.name)):
            raise RuntimeError(f"почта учётки {person.login} не записана")
        if not set_name_latin(person.login, tenant=person.tenant, name=person.name):
            raise RuntimeError(f"имя учётки {person.login} не записано")
    return len(everyone)


@dataclass(frozen=True)
class Partner:
    """Франчайзи страны: юрлицо и кто на связи."""

    name: str
    contact: str


PARTNERS = {
    "RS": Partner("Sava Pizza d.o.o.", "Jelena Maric"),
    "GE": Partner("Kolkheti Foods LLC", "Giorgi Beridze"),
    "AM": Partner("Ararat Food Group LLC", "Anahit Sargsyan"),
}  # fmt: skip
#: Год открытия отдельных точек; у остальных он выводится из номера точки.
OPENED = {"Northgate-1": 2022, "Northgate-2": 2023, "Westfield-1": 2024}


def _unit_ids(dsn: str) -> dict[str, str]:
    with psycopg.connect(dsn) as conn:
        apply_space(conn)
        rows = conn.execute("select name, id::text from units where tenant_code = 'HQ'").fetchall()
    return {str(name): str(ident) for name, ident in rows}


def seed_partners(units: Sequence[tuple[str, str]], city_of: dict[str, str], dsn: str) -> int:
    """Партнёр, адрес и дата открытия у каждой пиццерии; код Dodo — как в рейтингах.

    Код Dodo точке ставит та же дверь, что у свода (`set_unit_codes`): по нему страница страны
    находит и свод, и оценки площадок.
    """
    codes = open_demo_ratings.unit_ids(units)
    unit_ids = _unit_ids(dsn)
    for n, (name, country) in enumerate(units, start=1):
        partner = PARTNERS[country]
        opened = date(OPENED.get(name, 2021 + n % 4), 1 + n % 11, 1 + n * 2 % 27)
        unit_profiles.upsert(
            unit_profiles.Profile(
                country_code=country,
                name=name,
                name_normalized=normalize(name),
                stage="open",
                status="Open",
                city=city_of[name],
                address=f"{10 + n} Main Street, {city_of[name]}",
                partner=partner.name,
                partner_email=email_of(partner.contact),
                restaurant_on=opened,
                delivery_on=opened,
                seats=24 + 4 * (n % 4),
                dodo_id=codes[name],
            )
        )
        unit_profiles.set_unit_codes([(unit_ids[name], codes[name])])
    return len(units)
