"""Клиентские оценки: язык интерфейса не меняет источник и вес данных."""

CLIENT_TEXTS: dict[str, dict[str, str]] = {
    "ratings.clients.failed": {
        "ru": "Оценки клиентов сейчас не прочитались. Показано то, что сохранено.",
        "en": "Customer ratings could not be read right now. Showing what is saved.",
    },
    "ratings.clients.incomplete": {
        "ru": "Для части стран нет загрузки оценок клиентов.",
        "en": "Some countries have no customer ratings loaded.",
    },
    "ratings.clients.loaded": {"ru": "Загружено: {at}", "en": "Loaded: {at}"},
    "ratings.clients.monthsOnly": {
        "ru": (
            "Оценки приходят по месяцам целиком. Если период захватывает месяц не "
            "полностью, этот месяц не учитывается. Текущий месяц — с 1-го числа по "
            "сегодня."
        ),
        "en": (
            "Ratings come in whole months. If the period only partly covers a month, "
            "that month is left out. The current month runs from the 1st through "
            "today."
        ),
    },
    "ratings.clients.noData": {
        "ru": "За выбранный период нет полных месяцев с оценками клиентов.",
        "en": "There are no complete months with customer ratings in the selected period.",
    },
    "ratings.clients.latest": {
        "ru": "Открыть последний месяц с данными: {month}",
        "en": "Open the latest month with data: {month}",
    },
    "ratings.clients.coverage": {
        "ru": "Учтены оценки за {months} (по {end}).",
        "en": "Ratings included: {months} (through {end}).",
    },
    "ratings.clients.total": {"ru": "Все оценки · из 5", "en": "All ratings · out of 5"},
    "ratings.clients.dine": {"ru": "Зал · из 5", "en": "Dine-in · out of 5"},
    "ratings.clients.delivery": {"ru": "Доставка · из 5", "en": "Delivery · out of 5"},
    "ratings.clients.count": {"ru": "Оценок: {n}", "en": "Ratings: {n}"},
    "ratings.clients.units": {"ru": "Оценки по пиццериям", "en": "Ratings by pizzeria"},
    "ratings.clients.unit": {"ru": "Пиццерия", "en": "Pizzeria"},
    "ratings.clients.weighted": {
        "ru": (
            "Средняя считается с учётом числа оценок: месяц с большим числом оценок "
            "влияет сильнее. В скобках — сколько было оценок."
        ),
        "en": (
            "The average accounts for how many ratings there were: a month with more "
            "ratings counts for more. In parentheses: the number of ratings."
        ),
    },
}
