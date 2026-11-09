"""Дата для человека: «6 сен 2026», а не `2026-09-06` и не `06.09.2026` (#963).

`10.12.2026` читается и как 10 декабря, и как 12 октября — смотря чьи привычки
у читателя, а площадки у нас в разных странах. Месяц словом не путается ни у
кого. Здесь одно место, где дата становится строкой экрана; разбор работает и
на ответах информационной части, которые хранятся текстом так, как их печатает
движок (`walk_write._info_value`).

Строка, которая не похожа на дату целиком, возвращается как есть: ответ «вчера
в 15:00» или «Нет» — это слова аудитора, и переписывать их нельзя.
"""

from __future__ import annotations

import re
from datetime import date, datetime

from ..domain.timing import local_span
from .texts import t


def human_inspection_time(
    started_at: str | None, finished_at: str | None, zone: str | None, lang: str
) -> str:
    """Когда шла проверка: «10:15–12:40 · 2 ч 25 мин» по часам страны пиццерии (D730).

    Начала нет — «Не зафиксирована»: ничего не досчитывается. Конца нет — «начало 10:15».
    Зоны нет — UTC с пометкой, а не молчаливо «местное».
    """
    span = local_span(started_at, finished_at, zone)
    if span is None:
        return t("card.fact.duration_unknown", lang)
    suffix = " UTC" if span.utc else ""
    if span.end is None or span.minutes is None:
        return t("card.fact.time_started", lang, time=f"{span.start}{suffix}")
    hours, minutes = divmod(span.minutes, 60)
    parts = [t("card.fact.hours", lang, n=hours)] if hours else []
    if minutes or not hours:
        parts.append(t("card.fact.minutes", lang, n=minutes))
    return f"{span.start}\u2013{span.end}{suffix} \u00b7 {' '.join(parts)}"


_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}:\d{2}))?")
_DOTTED = re.compile(r"^(\d{2})\.(\d{2})\.(\d{4})(?:\s+(\d{2}:\d{2}))?$")


def _words(day: date, clock: str | None, lang: str) -> str:
    text = f"{day.day} {t(f'date.mon.{day.month}', lang)} {day.year}"
    return f"{text}, {clock}" if clock else text


def _parsed(value: str) -> tuple[date, str | None] | None:
    iso = _ISO.match(value)
    if iso and (len(value) == 10 or iso.group(4)):
        y, m, d, clock = int(iso[1]), int(iso[2]), int(iso[3]), iso[4]
    else:
        dotted = _DOTTED.match(value)
        if not dotted:
            return None
        d, m, y, clock = int(dotted[1]), int(dotted[2]), int(dotted[3]), dotted[4]
    try:
        return date(y, m, d), clock
    except ValueError:
        return None


def human_day(value: date | datetime | str | None, lang: str) -> str:
    """`date`, ISO или `ДД.ММ.ГГГГ[ ЧЧ:ММ]` → «6 сен 2026[, 14:30]»; иное — как есть."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return _words(value.date(), value.strftime("%H:%M"), lang)
    if isinstance(value, date):
        return _words(value, None, lang)
    text = str(value).strip()
    found = _parsed(text)
    return _words(found[0], found[1], lang) if found else text
