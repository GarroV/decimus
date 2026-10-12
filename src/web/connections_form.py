"""Разбор формы «Подключить сервис» и правки сервиса (D425).

Ядро безопасности: что именно попадёт в `api.tokens` — права, страны, срок.
Форма приходит снаружи и принимается на слово только после этой проверки;
любой отказ — ключ текста и параметры, а в базу не уходит ничего. Слой базы
(`api_access`) проверяет права ещё раз, но страны и срок знает только он как
значения, а «что такое известная страна» — справочник «Рейтингов», поэтому
сверка стран живёт здесь.

Модуль без Flask и базы: на вход — поля формы и справочник стран, на выход —
`Draft` или `Refusal`. Так он проверяется без приложения.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from werkzeug.datastructures import MultiDict

from src.db.api_access import SCOPES

#: Код сервиса: латиница в нижнем регистре, цифры, дефис; 2–32 знака.
CODE_SHAPE = re.compile(r"^[a-z0-9][a-z0-9-]{1,31}$")
#: Код страны: ISO-2.
COUNTRY_SHAPE = re.compile(r"^[A-Z]{2}$")
MAX_NAME = 80
MAX_CONTACT = 120
#: Конец дня срока — включительно (форма говорит «действует до»).
_END_OF_DAY = time(23, 59, 59)


Form = MultiDict[str, str]
"""Поля формы: одно значение и список (галочки прав)."""


@dataclass(frozen=True)
class Draft:
    """Проверенный ввод: готов к выдаче или правке."""

    consumer: str
    title: str
    contact: str | None
    scopes: tuple[str, ...]
    #: `None` — вся сеть.
    countries: tuple[str, ...] | None
    expires_at: datetime | None


@dataclass(frozen=True)
class Refusal:
    """Отказ: ключ текста `connections.err.<key>` и подстановки."""

    key: str
    params: dict[str, Any] = field(default_factory=dict)


def raw_values(form: Form) -> dict[str, Any]:
    """Введённое как есть — чтобы после отказа форма не пустела."""
    return {
        "code": (form.get("code") or "").strip(),
        "title": (form.get("title") or "").strip(),
        "contact": (form.get("contact") or "").strip(),
        "scopes": tuple(form.getlist("scope")),
        "countries": (form.get("countries") or "").strip(),
        "expires": (form.get("expires") or "").strip(),
    }


def _countries(text: str, known: frozenset[str]) -> tuple[str, ...] | Refusal | None:
    codes = tuple(dict.fromkeys(p.upper() for p in re.split(r"[\s,;]+", text) if p))
    if not codes:
        return None
    unknown = [c for c in codes if not COUNTRY_SHAPE.match(c) or c not in known]
    if unknown:
        return Refusal("country_unknown", {"codes": " ".join(unknown)})
    return codes


def _expiry(text: str, *, today: date, keep: date | None) -> datetime | Refusal | None:
    if not text:
        return None
    try:
        day = date.fromisoformat(text)
    except ValueError:
        return Refusal("expires_bad")
    if day < today + timedelta(days=1) and day != keep:
        return Refusal("expires_past")
    return datetime.combine(day, _END_OF_DAY, tzinfo=UTC)


def parse(
    form: Form,
    *,
    known_countries: frozenset[str],
    today: date,
    with_code: bool,
    code: str = "",
    keep_expiry: date | None = None,
) -> Draft | Refusal:
    """Форма → `Draft` или первый отказ.

    `with_code` — выдача: код берётся из формы и проверяется; при правке код
    уже есть у сервиса (`code`) и из формы не читается вовсе. `keep_expiry` —
    срок, который у сервиса уже стоит: оставить его можно, даже если он
    сегодняшний (иначе нельзя было бы поправить права ключа в последний день).
    """
    values = raw_values(form)
    consumer = values["code"] if with_code else code
    if with_code and not CODE_SHAPE.match(consumer):
        return Refusal("code")
    title = values["title"]
    if not title:
        return Refusal("name_required")
    if len(title) > MAX_NAME:
        return Refusal("name_long", {"max": MAX_NAME})
    contact = values["contact"]
    if len(contact) > MAX_CONTACT:
        return Refusal("contact_long", {"max": MAX_CONTACT})
    scopes = tuple(dict.fromkeys(values["scopes"]))
    if not scopes:
        return Refusal("scopes_none")
    if any(s not in SCOPES for s in scopes):
        return Refusal("scopes_unknown")
    countries = _countries(values["countries"], known_countries)
    if isinstance(countries, Refusal):
        return countries
    expires_at = _expiry(values["expires"], today=today, keep=keep_expiry)
    if isinstance(expires_at, Refusal):
        return expires_at
    return Draft(consumer, title, contact or None, scopes, countries, expires_at)
