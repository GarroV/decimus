"""Подписи общей истории проверок: страна и раздел рейтингов."""

TIMELINE_TEXTS = {
    "ratings.sec.inspections": {"ru": "Проверки", "en": "Inspections"},
    "history.title": {"ru": "История проверок", "en": "Inspection history"},
    "history.note": {
        "ru": (
            "Вся история принятых проверок, включая загруженные старые отчёты. "
            "Период страницы на график не влияет. Средняя — по проверкам; "
            "пропуск означает, что проверок не было."
        ),
        "en": (
            "All accepted inspections, including imported historical reports. "
            "The page period does not limit this chart. Average is per inspection; "
            "a gap means no inspections."
        ),
    },
    "history.results": {"ru": "Динамика результатов", "en": "Score history"},
    "history.scale": {"ru": "Результат, % · шкала 0–100", "en": "Score, % · 0–100 scale"},
    "history.volume": {"ru": "Количество проверок", "en": "Inspection count"},
    "history.date": {"ru": "Дата проверки", "en": "Inspection date"},
    "history.daily": {
        "ru": (
            "Точки — даты обхода; несколько проверок за день объединены в среднюю. "
            "Линия связывает только даты с проверками."
        ),
        "en": (
            "Points mark inspection dates; multiple inspections on one day share an average. "
            "The line connects observed dates only."
        ),
    },
    "history.single": {
        "ru": "Пока есть только одна дата — изменение результата ещё не видно.",
        "en": "There is only one date so far; a change in score is not yet available.",
    },
    "history.empty_period": {
        "ru": "За выбранный год проверок нет.",
        "en": "No inspections in the selected year.",
    },
    "history.years": {"ru": "По годам", "en": "By year"},
    "history.months": {"ru": "По месяцам", "en": "By month"},
    "history.year": {"ru": "Год для месяцев", "en": "Year for months"},
    "history.period": {"ru": "Период", "en": "Period"},
    "history.count": {"ru": "Проверок", "en": "Inspections"},
    "history.average": {"ru": "Средний результат, %", "en": "Average score, %"},
    "history.show": {"ru": "Показать", "en": "Show"},
    "history.empty": {"ru": "Принятых проверок пока нет.", "en": "No accepted inspections yet."},
    "history.failed": {
        "ru": "Не удалось прочитать историю проверок. Обновите страницу.",
        "en": "Could not load inspection history. Refresh the page.",
    },
    "history.table": {"ru": "Данные графика", "en": "Chart data"},
}
