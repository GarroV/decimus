"""Списки копий писем УК по видам рассылки (0103, D608, #1130).

Почты сотрудников УК, которые подставляются в «Копию» черновика письма. Только хранение:
отправки из системы нет, черновик в почту кладёт сам человек. Читает роль приложения (из
пространства УК, политика `0103`), пишет администратор истории; кто из УК вправе, решает
веб (`mailing.manage`).

Адрес уходит в заголовок `Cc:`, поэтому приводится к нижнему регистру и проверяется здесь
(`clean_email`) и ещё раз базой.
"""

from __future__ import annotations

import logging
import unicodedata

import psycopg

from .config import check_environment, load_retraction_settings
from .errors import MailingCcError, MailingCcInputError, PrescriptionError
from .pool import connection
from .prescriptions import parse_recipients

logger = logging.getLogger(__name__)

KIND_INSPECTION = "inspection"
KIND_PRESCRIPTION = "prescription"
KIND_PLAN = "plan"
#: Виды рассылки в порядке показа: письма по проверкам, предписания, экшн-планы (D608).
KINDS = (KIND_INSPECTION, KIND_PRESCRIPTION, KIND_PLAN)

#: Предел адреса в базе (`mailing_cc.email`).
EMAIL_MAX = 200


def clean_email(raw: str) -> str:
    """Один адрес в нижнем регистре; пусто, несколько адресов или кривой адрес — отказ."""
    try:
        итог = parse_recipients(raw)
    except PrescriptionError as exc:
        raise MailingCcInputError(str(exc)) from exc
    if not итог:
        raise MailingCcInputError("Впишите адрес почты")
    if ", " in итог:
        raise MailingCcInputError("Адрес один за раз: впишите одну почту")
    if any(unicodedata.category(ch) == "Cc" for ch in итог):
        raise MailingCcInputError("В адресе почты есть недопустимые управляющие знаки")
    if len(итог) > EMAIL_MAX:
        raise MailingCcInputError(f"Адрес слишком длинный: не больше {EMAIL_MAX} знаков")
    return итог.lower()


def _kind(kind: str) -> str:
    if kind not in KINDS:
        raise MailingCcInputError("Такого вида рассылки нет")
    return kind


def read(kind: str) -> tuple[str, ...]:
    """Список копий вида в порядке заведения. Не прочиталось — `MailingCcError`."""
    try:
        with connection(check_environment().dsn) as conn:
            rows = conn.execute(
                "select email from mailing_cc where kind = %s order by added_at, email",
                (_kind(kind),),
            ).fetchall()
    except psycopg.Error as exc:
        raise MailingCcError(
            f"Список копий не прочитался: база отказала ({type(exc).__name__})"
        ) from exc
    return tuple(str(r[0]) for r in rows)


def counts() -> dict[str, int]:
    """Сколько адресов в списке каждого вида одним запросом (пустой вид — 0)."""
    try:
        with connection(check_environment().dsn) as conn:
            rows = conn.execute("select kind, count(*) from mailing_cc group by kind").fetchall()
    except psycopg.Error as exc:
        raise MailingCcError(
            f"Списки копий не прочитались: база отказала ({type(exc).__name__})"
        ) from exc
    итог = dict.fromkeys(KINDS, 0)
    итог.update({str(r[0]): int(r[1]) for r in rows})
    return итог


def _run(sql: str, params: tuple[object, ...]) -> int:
    try:
        with psycopg.connect(load_retraction_settings().dsn) as conn:
            return conn.execute(sql, params).rowcount
    except psycopg.errors.IntegrityError as exc:
        raise MailingCcError("Адрес не сохранён: база отказала в значении") from exc
    except psycopg.Error as exc:
        raise MailingCcError(
            f"Список копий не изменён ({type(exc).__name__}). Ничего не изменено"
        ) from exc


def add(kind: str, email: str, *, actor: str) -> bool:
    """Добавить адрес в список вида. Уже есть — ничего не делает и отдаёт `False`."""
    who = (actor or "").strip()
    if not who:
        raise MailingCcError("Не назван, кто правит список копий: запись подписывается")
    hit = _run(
        "insert into mailing_cc (kind, email, added_by) values (%s, %s, %s) "
        "on conflict (kind, email) do nothing",
        (_kind(kind), clean_email(email), who),
    )
    return bool(hit)


def remove(kind: str, email: str) -> None:
    """Убрать адрес из списка вида. Такого адреса нет — `MailingCcError`."""
    hit = _run(
        "delete from mailing_cc where kind = %s and email = %s",
        (_kind(kind), (email or "").strip().lower()),
    )
    if not hit:
        raise MailingCcInputError("Такого адреса в списке нет")
