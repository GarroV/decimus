"""Тексты экрана «Страна» (D467): шапка, сегменты, плитки, таблица пиццерий, панель.

Отдельным модулем, а не строками в `texts.py`: тот уже длиннее предела файла.
Сливаются в общий каталог (`texts.TEXTS`) — `t()` знает один словарь.
"""

from __future__ import annotations

COUNTRY_TEXTS: dict[str, dict[str, str]] = {
    "country.seg.label": {"ru": "Разделы страны", "en": "Country sections"},
    "country.seg.summary": {"ru": "Сводка", "en": "Summary"},
    "country.seg.units": {"ru": "Пиццерии", "en": "Pizzerias"},
    "country.dev.label": {"ru": "Девелопер", "en": "Developer"},
    "country.dev.all": {"ru": "Все", "en": "All"},
    "country.dev.countries": {"ru": "Стран: {n}", "en": "Countries: {n}"},
    "country.dev.note": {
        "ru": "РС, РКО и оценки на картах по группе стран не складываются из средних: "
        "они — на экране каждой страны.",
        "en": "RS, CX and map ratings are not summed from country averages: "
        "see them on each country's screen.",
    },
    "country.facts.developer": {"ru": "Девелопер: {name}", "en": "Developer: {name}"},
    "country.facts.partner": {"ru": "Партнёр: {name}", "en": "Partner: {name}"},
    "country.facts.partners": {
        "ru": "Партнёры: {names} и ещё {n}",
        "en": "Partners: {names} and {n} in total",
    },
    "country.facts.units": {"ru": "Пиццерий: {total}", "en": "Pizzerias: {total}"},
    "country.figures.title": {"ru": "Ключевые цифры", "en": "Key figures"},
    "country.tile.average": {"ru": "Средняя оценка", "en": "Average score"},
    "country.tile.inspections": {"ru": "по проверкам: {n}", "en": "over {n} inspections"},
    "country.tile.checked": {"ru": "Проверено", "en": "Inspected"},
    "country.tile.of": {"ru": "{checked} из {total}", "en": "{checked} of {total}"},
    "country.tile.units": {"ru": "пиццерий", "en": "pizzerias"},
    "country.tile.letters": {"ru": "Буквы", "en": "Grades"},
    "country.tile.rs.hint": {
        "ru": "Среднее РС по пиццериям страны (как на «Рейтингах»)",
        "en": "Average RS across the country's pizzerias (as on Ratings)",
    },
    "country.tile.rko.hint": {
        "ru": "Среднее РКО по пиццериям страны (как на «Рейтингах»)",
        "en": "Average CX across the country's pizzerias (as on Ratings)",
    },
    "country.none.period": {
        "ru": "За период проверок не было.",
        "en": "No inspections in the period.",
    },
    "country.none.all_time": {"ru": "Показать за всё время", "en": "Show all time"},
    "country.none.ever": {
        "ru": "Проверок в этой стране ещё не было.",
        "en": "There have been no inspections in this country yet.",
    },
    "country.hurt.title": {"ru": "Где болит", "en": "Pain points"},
    "country.hurt.systemic": {
        "ru": "Нарушено сразу в нескольких пиццериях",
        "en": "Violated in several pizzerias at once",
    },
    "country.hurt.zones": {
        "ru": "Где страна теряет больше всего",
        "en": "Where the country loses most",
    },
    "country.units.title": {"ru": "Пиццерии", "en": "Pizzerias"},
    "country.units.hint": {
        "ru": "Проверка — последняя за выбранный период. Нажмите строку: сведения и история.",
        "en": "Inspection — the latest in the selected period. Click a row: details and history.",
    },
    "country.units.empty": {
        "ru": "В стране нет ни одной пиццерии.",
        "en": "There are no pizzerias in this country.",
    },
    "country.units.not_checked": {
        "ru": "за период не проверяли",
        "en": "not inspected in the period",
    },
    "country.units.closed": {"ru": "Закрытые: {n}", "en": "Closed: {n}"},
    "country.units.profiles_failed": {
        "ru": "Свод пиццерий не прочитался: партнёр, адрес и статус пока не показаны.",
        "en": "The pizzeria register could not be read: partner, address and status are not shown.",
    },
    "country.units.ratings_failed": {
        "ru": "Оценки РС / РКО не прочитались.",
        "en": "RS / CX ratings could not be read.",
    },
    "country.units.maps_failed": {
        "ru": "Оценки на картах не прочитались.",
        "en": "Map ratings could not be read.",
    },
    "country.col.unit": {"ru": "Пиццерия", "en": "Pizzeria"},
    "country.col.last": {"ru": "Последняя проверка", "en": "Latest inspection"},
    "country.col.country": {"ru": "Страна", "en": "Country"},
    "country.col.checked": {"ru": "Проверено", "en": "Inspected"},
    "country.col.inspections": {"ru": "Проверок", "en": "Inspections"},
    "country.panel.facts": {"ru": "Сведения", "en": "Details"},
    "country.panel.address": {"ru": "Адрес", "en": "Address"},
    "country.panel.ratings": {"ru": "Рейтинги", "en": "Ratings"},
    "country.panel.history": {"ru": "Последние проверки", "en": "Latest inspections"},
    "country.panel.history_empty": {"ru": "Проверок не было.", "en": "No inspections yet."},
    "country.panel.no_card": {
        "ru": "Карточки пиццерии нет: точки нет в справочнике, она есть только в своде.",
        "en": "No pizzeria card: the unit is not in the directory, only in the register.",
    },
}
