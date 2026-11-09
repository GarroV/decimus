"""D730: часовой пояс страны и «когда шла проверка» по часам этой страны.

Ядро по правилу «ошибка молчалива»: неверный пояс даёт правдоподобное, но чужое время
в отчёте партнёру, а не ошибку.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

import pytest

from src.domain.geo import COUNTRY_NAMES
from src.domain.timing import COUNTRY_ZONES, local_span, zone_for_country

START = "2026-11-09T03:15:00+00:00"
END = "2026-11-09T05:40:30+00:00"


def test_каждая_страна_справочника_имеет_зону() -> None:
    assert set(COUNTRY_NAMES) <= set(COUNTRY_ZONES), set(COUNTRY_NAMES) - set(COUNTRY_ZONES)
    for zone in COUNTRY_ZONES.values():
        ZoneInfo(zone)  # название зоны существует


@pytest.mark.parametrize(
    ("country", "zone"),
    [
        ("ID", "Asia/Jakarta"),
        ("mn", "Asia/Ulaanbaatar"),
        ("KZ", "Asia/Almaty"),
        ("RU", "Europe/Moscow"),
        ("US", "America/New_York"),
        ("MX", "America/Mexico_City"),
        ("CN", "Asia/Shanghai"),
    ],
)
def test_зона_по_стране(country: str, zone: str) -> None:
    assert zone_for_country(country) == zone


def test_неизвестная_страна_без_зоны() -> None:
    assert zone_for_country("ZZ") is None
    assert zone_for_country(None) is None
    assert zone_for_country("") is None


def test_время_переводится_в_местное() -> None:
    span = local_span(START, END, "Asia/Jakarta")
    assert span is not None
    assert (span.start, span.end, span.minutes, span.utc) == ("10:15", "12:40", 145, False)


def test_переход_через_полночь() -> None:
    span = local_span("2026-11-09T16:50:00+00:00", "2026-11-09T18:10:00+00:00", "Asia/Jakarta")
    assert span is not None
    assert (span.start, span.end, span.minutes) == ("23:50", "01:10", 80)


def test_нет_конца_только_начало() -> None:
    span = local_span(START, None, "Asia/Jakarta")
    assert span is not None
    assert (span.start, span.end, span.minutes) == ("10:15", None, None)


def test_конец_раньше_начала_не_печатается() -> None:
    span = local_span(END, START, "Asia/Jakarta")
    assert span is not None and span.end is None


def test_нет_начала_ничего_не_досчитывается() -> None:
    assert local_span(None, END, "Asia/Jakarta") is None


def test_неизвестная_зона_это_utc_с_пометкой() -> None:
    span = local_span(START, END, None)
    assert span is not None
    assert (span.start, span.end, span.utc) == ("03:15", "05:40", True)


def test_перевод_стрелок_не_искажает_длительность() -> None:
    # Нью-Йорк, 2026-11-01: в 02:00 часы идут назад. 05:30Z -> 01:30 EDT, 07:30Z -> 02:30 EST.
    span = local_span("2026-11-01T05:30:00+00:00", "2026-11-01T07:30:00+00:00", "America/New_York")
    assert span is not None
    assert (span.start, span.end, span.minutes) == ("01:30", "02:30", 120)


def test_строка_карточки_на_обоих_языках() -> None:
    from src.web.dates import human_inspection_time

    assert human_inspection_time(START, END, "Asia/Jakarta", "ru") == "10:15–12:40 · 2 ч 25 мин"
    assert human_inspection_time(START, END, "Asia/Jakarta", "en") == "10:15–12:40 · 2 h 25 min"
    assert human_inspection_time(START, None, "Asia/Jakarta", "en") == "started 10:15"
    assert human_inspection_time(START, END, None, "ru") == "03:15–05:40 UTC · 2 ч 25 мин"
    assert human_inspection_time(None, END, "Asia/Jakarta", "ru") == "Не зафиксирована"
    assert human_inspection_time(START, "2026-11-09T03:55:00+00:00", "Asia/Jakarta", "ru") == (
        "10:15–10:55 · 40 мин"
    )
