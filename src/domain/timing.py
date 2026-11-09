"""Server visit timestamps; elapsed time is derived once from the primary pair."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo


def utc_now() -> datetime:
    return datetime.now(UTC)


def parse_timestamp(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    stamp = datetime.fromisoformat(value) if isinstance(value, str) else value
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("Время проверки должно содержать часовой пояс")
    return stamp.astimezone(UTC)


def duration_seconds(started_at: datetime | None, finished_at: datetime | None) -> float | None:
    """No start or no successful finish means unknown, never zero or an estimate."""
    start, end = parse_timestamp(started_at), parse_timestamp(finished_at)
    if start is None or end is None:
        return None
    elapsed = (end - start).total_seconds()
    if elapsed < 0:
        raise ValueError("Конец проверки раньше начала")
    return elapsed


#: Часовой пояс страны — одна зона на страну (D730): поля пояса у пиццерии нет, а рабочие
#: страны, кроме перечисленных в задаче, однозонные. Ключи — все коды `geo.COUNTRY_NAMES`
#: (держит `tests/test_domain_timing_zone.py`). Новая страна сети — строка и сюда.
COUNTRY_ZONES: dict[str, str] = {
    "AE": "Asia/Dubai",
    "AM": "Asia/Yerevan",
    "AZ": "Asia/Baku",
    "BG": "Europe/Sofia",
    "BY": "Europe/Minsk",
    "CN": "Asia/Shanghai",
    "CY": "Asia/Nicosia",
    "DE": "Europe/Berlin",
    "EE": "Europe/Tallinn",
    "ES": "Europe/Madrid",
    "GB": "Europe/London",
    "GE": "Asia/Tbilisi",
    "HR": "Europe/Zagreb",
    "ID": "Asia/Jakarta",
    "IQ": "Asia/Baghdad",
    "KG": "Asia/Bishkek",
    "KZ": "Asia/Almaty",
    "LT": "Europe/Vilnius",
    "MD": "Europe/Chisinau",
    "ME": "Europe/Podgorica",
    "MN": "Asia/Ulaanbaatar",
    "MX": "America/Mexico_City",
    "NG": "Africa/Lagos",
    "PL": "Europe/Warsaw",
    "QA": "Asia/Qatar",
    "RO": "Europe/Bucharest",
    "RS": "Europe/Belgrade",
    "RU": "Europe/Moscow",
    "SI": "Europe/Ljubljana",
    "TJ": "Asia/Dushanbe",
    "TR": "Europe/Istanbul",
    "US": "America/New_York",
    "UZ": "Asia/Tashkent",
    "VN": "Asia/Ho_Chi_Minh",
}


def zone_for_country(country: str | None) -> str | None:
    """IANA-зона страны; `None` — страна неизвестна, и вызывающий печатает UTC открыто."""
    return COUNTRY_ZONES.get((country or "").strip().upper())


@dataclass(frozen=True)
class LocalSpan:
    """Начало и конец проверки по часам страны. `end` пуст, если конца нет или он до начала."""

    start: str
    end: str | None
    minutes: int | None
    utc: bool


def local_span(
    started_at: str | datetime | None, finished_at: str | datetime | None, zone: str | None
) -> LocalSpan | None:
    """Когда шла проверка: `None` — начала нет, ничего не досчитывается и не оценивается.

    Минуты считаются по показанным `ЧЧ:ММ`, чтобы «10:15–12:40» и «2 ч 25 мин» сходились.
    Нет зоны — UTC, и `utc=True` обязывает показывающего подписать это словом.
    """
    start = parse_timestamp(started_at)
    if start is None:
        return None
    tz = ZoneInfo(zone) if zone else UTC
    begin = start.replace(second=0, microsecond=0)
    end_raw = parse_timestamp(finished_at)
    end = end_raw.replace(second=0, microsecond=0) if end_raw else None
    if end is not None and end < begin:
        end = None
    return LocalSpan(
        start=begin.astimezone(tz).strftime("%H:%M"),
        end=end.astimezone(tz).strftime("%H:%M") if end else None,
        # Разность — по UTC: в одной зоне Python вычитает «стенные» часы и врёт на переводе стрелок.
        minutes=int((end - begin).total_seconds() // 60) if end else None,
        utc=not zone,
    )
