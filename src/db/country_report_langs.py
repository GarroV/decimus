"""Языки отчёта страны, перекрывающие файл методики (0096, D640).

Читает роль приложения (бот выбирает языки в конце проверки, `bot/report_lang.py`),
пишет администратор истории — как договор страны (`country_contracts.py`). Какие языки
допустимы, решает вызывающий (`TEXT_LANGS`); здесь — форма и подпись.

`langs_for` — единая точка «какие языки у страны»: строка базы, иначе файл методики
(`domain/report_langs.py`, который базы не знает: слои). Бот и веб зовут её, а не склеивают
сами.
"""

from __future__ import annotations

import logging

import psycopg

from src.domain import report_langs
from src.domain.models import TEXT_LANGS

from .config import check_environment, load_retraction_settings
from .errors import DbError
from .pool import connection

logger = logging.getLogger(__name__)


def read(country: str) -> tuple[str, ...] | None:
    """Перечень страны из базы; `None` — переопределения нет. Не прочиталось — `DbError`."""
    try:
        with connection(check_environment().dsn) as conn:
            row = conn.execute(
                "select langs from country_report_langs where country = %s", (country,)
            ).fetchone()
    except psycopg.Error as exc:
        raise DbError(
            f"Языки отчёта страны не прочитались: база отказала ({type(exc).__name__})"
        ) from exc
    return tuple(row[0]) if row else None


def _run(sql: str, params: tuple[object, ...]) -> None:
    try:
        with psycopg.connect(load_retraction_settings().dsn) as conn:
            conn.execute(sql, params)
    except psycopg.Error as exc:
        raise DbError(
            f"Языки отчёта страны не сохранены ({type(exc).__name__}). Ничего не изменено"
        ) from exc


def save(country: str, langs: tuple[str, ...], *, actor: str) -> None:
    """Задать перечень страны (замена прежнего). Подпись обязательна, перечень не пуст."""
    who = (actor or "").strip()
    if not who:
        raise DbError("Не назван, кто правит языки отчёта: запись подписывается")
    if not langs:
        raise DbError("Языки отчёта: нужен хотя бы один язык")
    _run(
        "insert into country_report_langs (country, langs, updated_by) values (%s, %s, %s) "
        "on conflict (country) do update set langs = excluded.langs, "
        "updated_by = excluded.updated_by, updated_at = now()",
        (country, list(langs), who),
    )


def reset(country: str) -> None:
    """Вернуть «как по умолчанию»: снять переопределение страны (его нет — ничего не делает)."""
    _run("delete from country_report_langs where country = %s", (country,))


def resolve(country: str | None) -> tuple[list[str], bool]:
    """Языки отчёта страны и признак «заданы в базе» (иначе — файл методики или `ru`, `en`).

    База не ответила или в строке нет ни одного языка методики — перечень как до
    переопределений (файл), со строкой в журнал: аудитор на точке без отчёта не остаётся.
    """
    code = (country or "").strip().upper()
    if code:
        try:
            override = read(code)
        except DbError:
            logger.warning(
                "Языки отчёта страны %s из базы не прочитались, берём файл", code, exc_info=True
            )
        else:
            kept = [lang for lang in (override or ()) if lang in TEXT_LANGS]
            if kept:
                return kept, True
    return report_langs.report_langs_for(country), False


def langs_for(country: str | None) -> list[str]:
    """Языки отчёта страны: переопределение из базы, иначе файл методики или `ru`, `en`."""
    return resolve(country)[0]
