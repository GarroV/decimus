"""Периоды и месяцы раздела «Рейтинги» словами, а не ключами (`2026-Q3`, `2026-10`).

Ни одного вычисления оценок: только подпись по уже выбранному периоду и списку месяцев.
"""

from __future__ import annotations

from datetime import date

from src.ratings.periods import KIND_MONTH, KIND_QUARTER, ReportPeriod

from .texts import t

_ROMAN = ("I", "II", "III", "IV")


def month_name(month: date, lang: str) -> str:
    """«октябрь» / «October»; год отдельно."""
    return t(f"ratings.monthfull.{month.month}", lang)


def month_title(month: date, lang: str) -> str:
    """«октябрь 2026»."""
    return t("ratings.period.title.month", lang, month=month_name(month, lang), year=month.year)


def _join(items: list[str], lang: str) -> str:
    if len(items) <= 1:
        return "".join(items)
    return f"{', '.join(items[:-1])} {t('ratings.and', lang)} {items[-1]}"


def months_phrase(months: tuple[date, ...], lang: str) -> str:
    """«октябрь и ноябрь 2026»; месяцы разных лет — «декабрь 2025 и январь 2026»."""
    years: dict[int, list[str]] = {}
    for month in months:
        years.setdefault(month.year, []).append(month_name(month, lang))
    return _join([f"{_join(names, lang)} {year}" for year, names in years.items()], lang)


def period_title(period: ReportPeriod, lang: str) -> str | None:
    """Месяц и квартал словами; остальные виды периода — `None` (их называет вызывающий)."""
    if period.kind == KIND_MONTH:
        return month_title(period.begin, lang)
    if period.kind == KIND_QUARTER:
        quarter = (period.begin.month - 1) // 3 + 1
        return t(
            "ratings.period.title.quarter",
            lang,
            q=_ROMAN[quarter - 1] if lang == "ru" else f"Q{quarter}",
            year=period.begin.year,
        )
    return None
