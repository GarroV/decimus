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
    "ratings.sec.risk": {"ru": "Пиццерии в зоне риска", "en": "Pizzerias at risk"},
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


# D746 shared ratings surface.
SECTION_TEXTS.update(
    {
        "ratings.sec.overview": {"ru": "Обзор РС и РКО", "en": "RS and CER overview"},
        "ratings.sec.violations": {"ru": "Нарушения", "en": "Violations"},
        "ratings.d746.mine": {"ru": "Мои страны", "en": "My countries"},
        "ratings.d746.all": {"ru": "Все страны", "en": "All countries"},
        "ratings.d746.choose_countries": {"ru": "Выбрать мои страны", "en": "Choose my countries"},
        "ratings.d746.save_countries": {"ru": "Сохранить выбор", "en": "Save selection"},
        "ratings.d746.reset_countries": {"ru": "Сбросить выбор", "en": "Reset selection"},
        "ratings.d746.country_topics": {"ru": "Рейтинги страны", "en": "Country ratings"},
        "ratings.d746.periods.rs": {"ru": "Периоды РС", "en": "RS periods"},
        "ratings.d746.periods.rko": {"ru": "Недели РКО", "en": "CER weeks"},
        "ratings.d746.period.closed": {"ru": "завершился", "en": "ended"},
        "ratings.d746.period.current": {"ru": "идёт", "en": "in progress"},
        "ratings.d746.period.upcoming": {"ru": "впереди", "en": "upcoming"},
        "ratings.d746.source.dodois": {"ru": "Оценки Dodo IS", "en": "Dodo IS scores"},
        "ratings.d746.source.sheet": {"ru": "Сохранённые рейтинги", "en": "Saved ratings"},
        "ratings.d746.source.mixed": {
            "ru": "Оценки Dodo IS и сохранённые рейтинги",
            "en": "Dodo IS scores and saved ratings",
        },
        "ratings.d746.source.none": {
            "ru": "Оценок за выбранный период пока нет",
            "en": "No scores for the selected period yet",
        },
        "ratings.d746.no_actual_periods": {
            "ru": "Даты периодов пока не получены",
            "en": "Period dates are not available yet",
        },
        "ratings.d746.scored": {"ru": "С оценкой", "en": "With scores"},
        "ratings.d746.eligibility": {
            "ru": "Число обязательных участников периода пока не подтверждено",
            "en": "The number of required participants is not confirmed yet",
        },
        "ratings.d746.scored_n": {
            "ru": "Пиццерий с оценкой: {n}",
            "en": "Pizzerias with scores: {n}",
        },
        "ratings.d746.cases_n": {"ru": "Случаев нарушений: {n}", "en": "Violation cases: {n}"},
        "ratings.d746.violation": {"ru": "Нарушение", "en": "Violation"},
        "ratings.d746.share": {"ru": "Доля", "en": "Share"},
        "ratings.d746.cases": {"ru": "Случаи", "en": "Cases"},
        "ratings.d746.open_violations": {"ru": "Нарушения", "en": "Violations"},
        "ratings.d746.top_violations": {
            "ru": "Частые нарушения среза",
            "en": "Frequent violations in this slice",
        },
        "ratings.d746.all_violations": {
            "ru": "Все нарушения среза",
            "en": "All violations in this slice",
        },
        "ratings.d746.no_violations_data": {
            "ru": "Детальных данных о нарушениях за этот период нет",
            "en": "No detailed violation data for this period",
        },
        "ratings.d746.share_help": {
            "ru": (
                "Доля — от числа случаев нарушений выбранного среза. "
                "Изменение — число случаев к прошлому периоду."
            ),
            "en": (
                "Share of violation cases in the selected slice. "
                "Change is the case count against the previous period."
            ),
        },
        "ratings.d746.violation_source": {"ru": "Источник нарушений", "en": "Violation source"},
        "ratings.d746.source_checks": {"ru": "Исходные проверки", "en": "Source checkups"},
        "ratings.d746.source_check": {"ru": "Открыть проверку", "en": "Open checkup"},
        "ratings.d746.no_source_photos": {
            "ru": (
                "В сохранённых данных источника нет фотографий. "
                "Доступны ссылки на исходные проверки."
            ),
            "en": (
                "The saved source data contains no photos. Links to source checkups are available."
            ),
        },
        "ratings.d746.country_overview": {
            "ru": "По странам · РС и РКО",
            "en": "By country · RS and CER",
        },
        "ratings.d746.close": {"ru": "Закрыть", "en": "Close"},
    }
)

SECTION_TEXTS["ratings.d746.bar_scale"] = {"ru": "Шкала полос: 70–100", "en": "Bar scale: 70–100"}

SECTION_TEXTS["ratings.d746.period_units"] = {
    "ru": "пиццерий: {n}",
    "en": "pizzerias: {n}",
}

SECTION_TEXTS.update(
    {
        "ratings.d746.whole_period": {"ru": "Весь период", "en": "Whole period"},
        "ratings.d746.period_average": {
            "ru": "Средняя за выбранный период",
            "en": "Average for the selected period",
        },
        "ratings.d746.shown": {"ru": "Показано:", "en": "Showing:"},
        "ratings.d746.country_profile": {"ru": "Карточка страны", "en": "Country profile"},
        "ratings.d746.both_up": {"ru": "Оба рейтинга выросли", "en": "Both ratings improved"},
        "ratings.d746.any_down": {
            "ru": "Снизился хотя бы один рейтинг",
            "en": "At least one rating declined",
        },
        "ratings.d746.biggest_rs": {"ru": "Самый большой рост РС", "en": "Largest RS improvement"},
        "ratings.d746.signal": {"ru": "Динамика", "en": "Trend"},
        "ratings.d746.signal.both_down": {"ru": "Оба снижаются", "en": "Both declining"},
        "ratings.d746.signal.rs_down": {"ru": "РС снижается", "en": "RS declining"},
        "ratings.d746.signal.rko_down": {"ru": "РКО снижается", "en": "CER declining"},
        "ratings.d746.signal.stable": {"ru": "Без снижения", "en": "No decline"},
        "ratings.d746.signal.unknown": {"ru": "Нет сравнения", "en": "No comparison"},
        "ratings.d746.countries_count": {"ru": "стран", "en": "countries"},
        "ratings.d746.export": {"ru": "Скачать список", "en": "Download list"},
    }
)
SECTION_TEXTS.update(
    {
        "ratings.d746.open_source": {"ru": "Открыть {source}", "en": "Open {source}"},
        "ratings.d746.comparable": {
            "ru": "Стран с сопоставимыми периодами: {n}",
            "en": "Countries with comparable periods: {n}",
        },
        "ratings.d746.sort": {"ru": "Сортировка", "en": "Sort"},
        "ratings.d746.sort.rs": {"ru": "По РС", "en": "By RS"},
        "ratings.d746.sort.rko": {"ru": "По РКО", "en": "By CER"},
        "ratings.d746.sort.rs_delta": {"ru": "По росту РС", "en": "By RS change"},
        "ratings.d746.sort.rko_delta": {"ru": "По росту РКО", "en": "By CER change"},
    }
)

SECTION_TEXTS.update(
    {
        "ratings.d746.maps.all": {"ru": "Все пиццерии", "en": "All pizzerias"},
        "ratings.d746.maps.low": {"ru": "Google ниже 4,0", "en": "Google below 4.0"},
        "ratings.d746.maps.stale": {"ru": "Данные устарели", "en": "Stale ratings"},
        "ratings.d746.maps.missing": {"ru": "Нет привязки Google", "en": "Google not linked"},
        "ratings.d746.maps.difference": {"ru": "Яндекс − Google", "en": "Yandex − Google"},
    }
)

SECTION_TEXTS["ratings.d746.maps.scale"] = {
    "ru": "Шкала полос: 4,0–5,0",
    "en": "Bar scale: 4.0–5.0",
}

SECTION_TEXTS["ratings.d746.no_hard_data"] = {
    "ru": "Данных о хард-нарушениях за выбранный период нет",
    "en": "Hard-violation data is unavailable for the selected period",
}
