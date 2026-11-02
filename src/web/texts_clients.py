"""Клиентские оценки: язык интерфейса не меняет источник и вес данных."""

CLIENT_TEXTS: dict[str, dict[str, str]] = {
    "ratings.clients.failed": {
        "ru": (
            "Не удалось обновить или прочитать клиентские оценки. Сохранённые данные, если "
            "доступны, показаны ниже."
        ),
        "en": (
            "Customer ratings could not be refreshed or read. Saved data, when available, "
            "is shown below."
        ),
    },
    "ratings.clients.incomplete": {
        "ru": (
            "Для части стран нет успешной загрузки клиентских оценок. Сводка может быть неполной."
        ),
        "en": (
            "Some countries have no successful customer-rating collection. The summary may "
            "be incomplete."
        ),
    },
    "ratings.clients.loaded": {
        "ru": "Последняя успешная загрузка выбранных стран: {at} UTC",
        "en": "Last successful collection for the selected countries: {at} UTC",
    },
    "ratings.clients.monthsOnly": {
        "ru": (
            "Источник хранит месячные агрегаты. Неполные месяцы на границах отбора "
            "исключены; текущий месяц доступен с первого числа по сегодня. Оценки не "
            "делятся пропорционально дням."
        ),
        "en": (
            "The source stores monthly aggregates. Partial boundary months are excluded; "
            "the current month is available from its first day through today. Ratings are "
            "not prorated by day."
        ),
    },
    "ratings.clients.noData": {
        "ru": "За выбранные полные месяцы клиентских оценок нет.",
        "en": "No customer ratings are available for the selected complete months.",
    },
    "ratings.clients.latest": {
        "ru": "Открыть последний месяц с данными: {month}",
        "en": "Open the latest month with data: {month}",
    },
    "ratings.clients.coverage": {
        "ru": "Месячные агрегаты за {begin} — {end}.",
        "en": "Monthly aggregates for {begin} — {end}.",
    },
    "ratings.clients.months": {"ru": "Месяцы с оценками:", "en": "Months with ratings:"},
    "ratings.clients.total": {"ru": "Все оценки · из 5", "en": "All ratings · out of 5"},
    "ratings.clients.dine": {"ru": "Зал · из 5", "en": "Dine-in · out of 5"},
    "ratings.clients.delivery": {"ru": "Доставка · из 5", "en": "Delivery · out of 5"},
    "ratings.clients.count": {"ru": "Оценок: {n}", "en": "Ratings: {n}"},
    "ratings.clients.units": {"ru": "Оценки по пиццериям", "en": "Ratings by pizzeria"},
    "ratings.clients.unit": {"ru": "Пиццерия", "en": "Pizzeria"},
    "ratings.clients.weighted": {
        "ru": "Средние взвешены числом оценок; в скобках — число оценок.",
        "en": "Averages are weighted by rating count; counts are in parentheses.",
    },
}
