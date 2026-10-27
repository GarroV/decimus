"""Шаблоны писем УК с историей версий (0104, D550, D608, #977, #1130).

Админ УК хранит свой текст письма партнёру на слот (вид письма) и язык; движок собирает
письмо по текущей версии слота, а нет её — по встроенному тексту (`engine/report.py`).
Читает роль приложения (из пространства УК, политика `0104`), пишет администратор истории;
кто из УК вправе писать, решает веб (`mailing.manage`).

Строка не правится: каждое сохранение — новая версия с автором и временем. «Вернуть
встроенный» — тоже версия (`body` пусто), чтобы история показывала, кто и когда вернул.
Подстановки проверяются до записи (`domain.letter_template.problem`): неизвестная — отказ
с причиной, а не пустое место в письме партнёру.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

import psycopg

from src.domain import letter_template as lt

from .config import check_environment, load_retraction_settings
from .errors import MailingTemplateError, MailingTemplateInputError
from .pool import connection

logger = logging.getLogger(__name__)

#: Вид рассылки, у которого есть шаблон (остальные виды — только копии, этапы #1130).
KIND_INSPECTION = "inspection"

#: Сколько прежних версий слота показывает история.
HISTORY_LIMIT = 10


@dataclass(frozen=True)
class Version:
    """Версия шаблона слота: номер, текст (`None` — встроенный), кто и когда сохранил."""

    version: int
    body: str | None
    saved_by: str
    saved_at: datetime


def _slot(kind: str, slot: str, lang: str) -> None:
    if kind != KIND_INSPECTION or slot not in lt.SLOTS or lang not in lt.LANGS:
        raise MailingTemplateInputError("Такого шаблона нет")


def _row(r: tuple[object, ...]) -> Version:
    return Version(int(str(r[0])), None if r[1] is None else str(r[1]), str(r[2]), r[3])  # type: ignore[arg-type]


def current(kind: str = KIND_INSPECTION) -> dict[tuple[str, str], Version]:
    """Текущая версия каждого слота вида одним запросом: `{(слот, язык): версия}`.

    Слота без строк в словаре нет. Не прочиталось — `MailingTemplateError`.
    """
    try:
        with connection(check_environment().dsn) as conn:
            rows = conn.execute(
                "select distinct on (slot, lang) slot, lang, version, body, saved_by, saved_at "
                "from mailing_templates where kind = %s "
                "order by slot, lang, version desc",
                (kind,),
            ).fetchall()
    except psycopg.Error as exc:
        raise MailingTemplateError(
            f"Шаблоны писем не прочитались: база отказала ({type(exc).__name__})"
        ) from exc
    return {(str(r[0]), str(r[1])): _row(r[2:]) for r in rows}


def bodies(kind: str = KIND_INSPECTION) -> dict[str, dict[str, str]]:
    """Сохранённые тексты письма: `{язык: {слот: текст}}` одним запросом.

    Слоты со встроенным текстом (нет строки или последняя версия «встроенный») не входят:
    для них движок берёт свой текст.
    """
    итог: dict[str, dict[str, str]] = {}
    for (slot, lang), v in current(kind).items():
        if v.body is not None:
            итог.setdefault(lang, {})[slot] = v.body
    return итог


def history(
    slot: str, lang: str, kind: str = KIND_INSPECTION, *, limit: int = HISTORY_LIMIT
) -> tuple[Version, ...]:
    """Версии слота, новые первыми. Не прочиталось — `MailingTemplateError`."""
    _slot(kind, slot, lang)
    try:
        with connection(check_environment().dsn) as conn:
            rows = conn.execute(
                "select version, body, saved_by, saved_at from mailing_templates "
                "where kind = %s and slot = %s and lang = %s order by version desc limit %s",
                (kind, slot, lang, limit),
            ).fetchall()
    except psycopg.Error as exc:
        raise MailingTemplateError(
            f"История шаблона не прочиталась: база отказала ({type(exc).__name__})"
        ) from exc
    return tuple(_row(r) for r in rows)


def save(slot: str, lang: str, body: str | None, *, actor: str, kind: str = KIND_INSPECTION) -> int:
    """Сохранить слот новой версией; `body=None` — вернуть встроенный текст. Отдаёт номер версии.

    Текст проверяется до базы: пустой, длинный, с неизвестной подстановкой — отказ с причиной.
    Две правки одновременно: вторая получает отказ «повторите» (ключ версии занят), а не тихо
    затирает первую.
    """
    _slot(kind, slot, lang)
    who = (actor or "").strip()
    if not who:
        raise MailingTemplateInputError("Не назван, кто правит шаблон: запись подписывается")
    if body is not None:
        body = body.replace("\r\n", "\n").strip("\n")
        why = lt.problem(body)
        if why:
            raise MailingTemplateInputError(why)
    try:
        with psycopg.connect(load_retraction_settings().dsn) as conn:
            row = conn.execute(
                "insert into mailing_templates (kind, slot, lang, version, body, saved_by) "
                "select %(k)s, %(s)s, %(l)s, coalesce(max(version), 0) + 1, %(b)s, %(w)s "
                "from mailing_templates where kind = %(k)s and slot = %(s)s and lang = %(l)s "
                "returning version",
                {"k": kind, "s": slot, "l": lang, "b": body, "w": who},
            ).fetchone()
    except psycopg.errors.UniqueViolation as exc:
        raise MailingTemplateError("Шаблон правили одновременно: повторите сохранение") from exc
    except psycopg.errors.IntegrityError as exc:
        raise MailingTemplateInputError("Шаблон не сохранён: база отказала в значении") from exc
    except psycopg.Error as exc:
        raise MailingTemplateError(
            f"Шаблон не сохранён ({type(exc).__name__}). Ничего не изменено"
        ) from exc
    return int(str(row[0])) if row else 0
