"""Тексты разделов «Рейтингов» (D660): подменю, шапка раздела, плитки, «Агрегаторы».

Отдельным модулем: `texts_ratings.py` у предела размера файла. Сливается в
`RATINGS_TEXTS`, а оттуда — в общий каталог.
"""

from __future__ import annotations

SECTION_TEXTS: dict[str, dict[str, str]] = {
    "ratings.sec.nav": {"ru": "Разделы рейтингов", "en": "Ratings sections"},
    "ratings.sec.pick": {"ru": "Раздел", "en": "Section"},
    "ratings.sec.rs": {"ru": "Рейтинг стандарт (РС)", "en": "Standards rating (RS)"},
    "ratings.sec.rko": {"ru": "РКО", "en": "Customer experience (CX)"},
    "ratings.sec.clients": {"ru": "Оценки клиентов", "en": "Customer ratings"},
    "ratings.sec.maps": {"ru": "Карты", "en": "Maps"},
    "ratings.sec.agg": {"ru": "Агрегаторы", "en": "Delivery apps"},
    "ratings.sec.risk": {"ru": "Стабильно ниже порога", "en": "Consistently below threshold"},
    "ratings.sec.compare": {"ru": "Девелоперы и страны", "en": "Developers and countries"},
    "ratings.sec.fresh.rs": {
        "ru": "данные за {span} · пришли {at}",
        "en": "data for {span} · arrived {at}",
    },
    "ratings.sec.fresh.rko": {
        "ru": "данные за неделю {span} · пришли {at}",
        "en": "data for the week {span} · arrived {at}",
    },
    "ratings.sec.fresh.pull": {"ru": "пришли {at}", "en": "arrived {at}"},
    "ratings.sec.fresh.none": {"ru": "оценок ещё нет", "en": "no scores yet"},
    "ratings.src.avg": {"ru": "Средняя", "en": "Average"},
    "ratings.src.avg.sub": {"ru": "пиццерий: {n}", "en": "pizzerias: {n}"},
    "ratings.src.viol": {"ru": "Нарушений", "en": "Violations"},
    "ratings.src.viol.sub": {"ru": "на проверку {x}", "en": "per check {x}"},
    "ratings.src.hard": {"ru": "Хард", "en": "Hard"},
    "ratings.src.hard.sub": {"ru": "пиццерий с хардом: {n}", "en": "pizzerias with hard: {n}"},
    "ratings.src.checked": {"ru": "Проверено", "en": "Checked"},
    "ratings.src.checked.of": {"ru": "{n} из {m}", "en": "{n} of {m}"},
    "ratings.src.checked.sub": {"ru": "работающих в реестре", "en": "working in the registry"},
    "ratings.src.countries": {"ru": "По странам", "en": "By country"},
    "ratings.src.col.country": {"ru": "Страна", "en": "Country"},
    "ratings.src.col.violations": {"ru": "Нарушений", "en": "Violations"},
    "ratings.src.col.hard": {"ru": "Хард", "en": "Hard"},
    "ratings.src.col.units": {"ru": "Пиццерий", "en": "Pizzerias"},
    "ratings.src.top": {"ru": "Топ-10", "en": "Top 10"},
    "ratings.src.bottom": {"ru": "Bottom-10", "en": "Bottom 10"},
    "ratings.src.hard.title": {"ru": "Хард-нарушения", "en": "Hard violations"},
    "ratings.agg.tiles": {"ru": "Площадки", "en": "Platforms"},
    "ratings.agg.tile.sub": {"ru": "привязано {n} из {m}", "en": "linked {n} of {m}"},
    "ratings.agg.by_country": {"ru": "Страна × площадка", "en": "Country × platform"},
    "ratings.agg.by_country.hint": {
        "ru": "оценка · сколько пиццерий привязано; нажми страну — её пиццерии",
        "en": "rating · how many pizzerias are linked; click a country for its pizzerias",
    },
    "ratings.agg.no_units": {
        "ru": "В реестре нет работающих пиццерий этой страны.",
        "en": "No working pizzerias of this country in the registry.",
    },
    "ratings.agg.gaps": {"ru": "Чего не хватает", "en": "What is missing"},
    "ratings.agg.gaps.hint": {
        "ru": "пиццерии без точки или без оценки на площадке — и почему",
        "en": "pizzerias with no listing or rating on a platform, and why",
    },
    "ratings.agg.gaps.none": {
        "ru": "Все ожидаемые точки на месте.",
        "en": "All expected listings are in place.",
    },
    "ratings.agg.reason.unlinked": {
        "ru": "{platform}: не привязана — точка рядом с пиццерией не нашлась",
        "en": "{platform}: not linked — no listing found near the pizzeria",
    },
    "ratings.agg.reason.paused": {
        "ru": "{platform}: площадка на паузе, точки не ищем",
        "en": "{platform}: the platform is paused, listings are not searched",
    },
    "ratings.agg.reason.unrated": {
        "ru": "{platform}: точка привязана, оценок у неё ещё нет",
        "en": "{platform}: linked, but it has no ratings yet",
    },
    "ratings.agg.reason.stale": {
        "ru": "{platform}: оценка не обновляется с {date}",
        "en": "{platform}: the rating has not updated since {date}",
    },
    "ratings.maps.units": {"ru": "Пиццерии на картах", "en": "Pizzerias on maps"},
    "ratings.maps.units.hint": {
        "ru": "оценка пиццерии на каждой карте; △ — новые оценки не приходят",
        "en": "the pizzeria's rating on each map; △ — no new ratings arriving",
    },
    "ratings.maps.units.none": {
        "ru": "Реестр пиццерий пуст — карты привязать не к чему.",
        "en": "The pizzeria registry is empty — nothing to match maps to.",
    },
}
