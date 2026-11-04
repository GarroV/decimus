"""Тексты разделов «Рейтингов» (D660): подменю, шапка раздела, плитки, «Агрегаторы».

Отдельным модулем: `texts_ratings.py` у предела размера файла. Сливается в
`RATINGS_TEXTS`, а оттуда — в общий каталог.
"""

from __future__ import annotations

SECTION_TEXTS: dict[str, dict[str, str]] = {
    "ratings.sec.nav": {"ru": "Разделы рейтингов", "en": "Ratings sections"},
    "ratings.tip.label": {"ru": "Пояснение", "en": "Explanation"},
    "ratings.sec.pick": {"ru": "Раздел", "en": "Section"},
    "ratings.sec.rs": {"ru": "Рейтинг стандартов (РС)", "en": "Standards rating (RS)"},
    "ratings.sec.rko": {
        "ru": "Рейтинг клиентского опыта (РКО)",
        "en": "Customer experience rating (CX)",
    },
    "ratings.sec.clients": {"ru": "Оценки клиентов", "en": "Customer ratings"},
    "ratings.sec.maps": {"ru": "Карты", "en": "Maps"},
    "ratings.sec.agg": {"ru": "Агрегаторы", "en": "Delivery apps"},
    "ratings.sec.risk": {"ru": "Стабильно ниже порога", "en": "Consistently below threshold"},
    "ratings.sec.compare": {"ru": "Девелоперы и страны", "en": "Developers and countries"},
    "ratings.sec.fresh.rs": {
        "ru": "Данные за {span}, пришли {at}",
        "en": "Data for {span}, arrived {at}",
    },
    "ratings.sec.fresh.rko": {
        "ru": "Данные за неделю {span}, пришли {at}",
        "en": "Data for the week {span}, arrived {at}",
    },
    "ratings.sec.fresh.pull": {"ru": "Загружено {at}", "en": "Loaded {at}"},
    "ratings.sec.fresh.none": {"ru": "Оценок ещё нет", "en": "No scores yet"},
    "ratings.src.avg": {"ru": "Средняя", "en": "Average"},
    "ratings.src.avg.sub": {"ru": "пиццерий: {n}", "en": "pizzerias: {n}"},
    "ratings.src.viol": {"ru": "Нарушений", "en": "Violations"},
    "ratings.src.viol.sub": {"ru": "на проверку {x}", "en": "per check {x}"},
    "ratings.src.hard": {"ru": "Хард", "en": "Hard"},
    "ratings.src.hard.sub": {"ru": "пиццерий с хардом: {n}", "en": "pizzerias with hard: {n}"},
    "ratings.src.checked": {"ru": "Проверено", "en": "Checked"},
    "ratings.src.checked.of": {"ru": "{n} из {m}", "en": "{n} of {m}"},
    "ratings.src.checked.sub": {"ru": "работающих пиццерий", "en": "working pizzerias"},
    "ratings.src.countries": {"ru": "По странам", "en": "By country"},
    "ratings.src.col.country": {"ru": "Страна", "en": "Country"},
    "ratings.src.col.violations": {"ru": "Нарушений", "en": "Violations"},
    "ratings.src.col.hard": {"ru": "Хард", "en": "Hard"},
    "ratings.src.col.units": {"ru": "Пиццерий", "en": "Pizzerias"},
    "ratings.src.top": {"ru": "Лучшие 10", "en": "Top 10"},
    "ratings.src.bottom": {"ru": "Худшие 10", "en": "Bottom 10"},
    "ratings.src.hard.title": {"ru": "Хард-нарушения", "en": "Hard violations"},
    "ratings.agg.tiles": {"ru": "Площадки", "en": "Platforms"},
    "ratings.agg.tile.sub": {"ru": "привязано {n} из {m}", "en": "linked {n} of {m}"},
    "ratings.agg.by_country": {"ru": "Страна × площадка", "en": "Country × platform"},
    "ratings.agg.by_country.hint": {
        "ru": (
            "В ячейке — оценка и число пиццерий, по которым она посчитана. Нажмите на "
            "страну, чтобы увидеть её пиццерии."
        ),
        "en": (
            "In a cell: the rating and the number of pizzerias it is based on. Click "
            "a country to see its pizzerias."
        ),
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
    "ratings.agg.reason.candidate": {
        "ru": "{platform}: рядом есть непривязанная точка — привязать вручную",
        "en": "{platform}: an unlinked listing is nearby — link it by hand",
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
        "ru": (
            "У каждой пиццерии — её оценка на каждой карте. △ — новые оценки с этой "
            "карты не приходят."
        ),
        "en": (
            "Each pizzeria's rating on each map. △ means no new ratings are arriving from that map."
        ),
    },
    "ratings.maps.units.none": {
        "ru": "Реестр пиццерий пуст — карты привязать не к чему.",
        "en": "The pizzeria registry is empty — nothing to match maps to.",
    },
    "ratings.help.rs": {
        "ru": (
            "Рейтинг стандартов (РС) — средняя оценка пиццерий по проверкам "
            "стандартов. Выходит дважды в месяц."
        ),
        "en": (
            "The standards rating (RS) is the average pizzeria score from standards "
            "checks. Published twice a month."
        ),
    },
    "ratings.help.rko": {
        "ru": (
            "Рейтинг клиентского опыта (РКО) — оценки по фото-проверке заказов. "
            "Выходит раз в неделю."
        ),
        "en": "The customer experience rating (CX) scores orders by photo check. Published weekly.",
    },
    "ratings.help.maps": {
        "ru": (
            "Средняя оценка пиццерий на Google и Яндекс Картах — по всем отзывам на конец периода."
        ),
        "en": (
            "Average pizzeria rating on Google and Yandex Maps, over all reviews at "
            "the end of the period."
        ),
    },
    "ratings.help.agg": {
        "ru": "Оценки пиццерий в приложениях доставки. Собираются раз в сутки.",
        "en": "Pizzeria ratings in delivery apps. Collected once a day.",
    },
    "ratings.help.compare": {
        "ru": "Показаны все страны и девелоперы, независимо от выбранного среза.",
        "en": "All countries and developers are shown, whatever group is selected.",
    },
    "ratings.delta.note": {
        "ru": "Изменение — к предыдущему периоду ({prev}).",
        "en": "Change is against the previous period ({prev}).",
    },
    "ratings.monthfull.1": {"ru": "январь", "en": "January"},
    "ratings.monthfull.2": {"ru": "февраль", "en": "February"},
    "ratings.monthfull.3": {"ru": "март", "en": "March"},
    "ratings.monthfull.4": {"ru": "апрель", "en": "April"},
    "ratings.monthfull.5": {"ru": "май", "en": "May"},
    "ratings.monthfull.6": {"ru": "июнь", "en": "June"},
    "ratings.monthfull.7": {"ru": "июль", "en": "July"},
    "ratings.monthfull.8": {"ru": "август", "en": "August"},
    "ratings.monthfull.9": {"ru": "сентябрь", "en": "September"},
    "ratings.monthfull.10": {"ru": "октябрь", "en": "October"},
    "ratings.monthfull.11": {"ru": "ноябрь", "en": "November"},
    "ratings.monthfull.12": {"ru": "декабрь", "en": "December"},
    "ratings.period.title.month": {"ru": "{month} {year}", "en": "{month} {year}"},
    "ratings.period.title.quarter": {"ru": "{q} квартал {year}", "en": "{q} {year}"},
    "ratings.and": {"ru": "и", "en": "and"},
}
