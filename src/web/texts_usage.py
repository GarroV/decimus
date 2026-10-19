"""Тексты экрана «Расход модели» (D537): вкладка «Администрирования», расход токенов."""

from __future__ import annotations

USAGE_TEXTS: dict[str, dict[str, str]] = {
    "usage.tab": {"ru": "Расход модели", "en": "Model usage"},
    "usage.sub": {
        "ru": (
            "Сколько токенов и денег уходит на нейросеть: по дням, видам вызова, людям и проверкам."
        ),
        "en": (
            "How many tokens and how much money go to the model: "
            "by day, kind of call, person and inspection."
        ),
    },
    "usage.estimate": {"ru": "оценка", "en": "estimate"},
    "usage.estimate.note": {
        "ru": (
            "Деньги — оценка по публичным ценам провайдера на день сверки; "
            "счёт провайдера может отличаться."
        ),
        "en": (
            "Money is an estimate from the provider's public prices on the day they were "
            "checked; the provider's invoice may differ."
        ),
    },
    "usage.stat.calls": {"ru": "Вызовов", "en": "Calls"},
    "usage.stat.input": {"ru": "Токенов на входе", "en": "Input tokens"},
    "usage.stat.output": {"ru": "Токенов на выходе", "en": "Output tokens"},
    "usage.stat.total": {"ru": "Токенов всего", "en": "Total tokens"},
    "usage.stat.cost": {"ru": "Стоимость", "en": "Cost"},
    "usage.stat.failed": {"ru": "из них неудачных: {count}", "en": "of which failed: {count}"},
    "usage.stat.partial": {
        "ru": "без моделей, у которых нет цены",
        "en": "excluding models with no price",
    },
    "usage.stat.noprice": {
        "ru": "цены модели нет в прейскуранте",
        "en": "no price for the model in the price list",
    },
    "usage.stat.vs": {"ru": "{value} к прошлому периоду", "en": "{value} vs previous period"},
    "usage.stat.novs": {"ru": "нет данных для сравнения", "en": "nothing to compare with"},
    "usage.days.title": {"ru": "По дням", "en": "By day"},
    "usage.days.unit": {"ru": "токенов", "en": "tokens"},
    "usage.kinds.title": {"ru": "По видам вызова", "en": "By kind of call"},
    "usage.people.title": {"ru": "По людям", "en": "By person"},
    "usage.inspections.title": {
        "ru": "Проверки с наибольшим расходом",
        "en": "Inspections with the highest usage",
    },
    "usage.inspections.note": {
        "ru": "Номер проверки в базе или метка проверки в боте до сдачи.",
        "en": "The inspection id in the database, or the bot's run label before handover.",
    },
    "usage.col.name": {"ru": "Кто / что", "en": "Who / what"},
    "usage.col.calls": {"ru": "Вызовов", "en": "Calls"},
    "usage.col.tokens": {"ru": "Токенов", "en": "Tokens"},
    "usage.col.cost": {"ru": "Оценка, $", "en": "Estimate, $"},
    "usage.person.unknown": {"ru": "не определён", "en": "unknown"},
    "usage.kind.recognize": {"ru": "Распознавание записи", "en": "Recognising a record"},
    "usage.kind.suggest": {"ru": "Подбор пункта на экране", "en": "Item suggestion on screen"},
    "usage.kind.revise": {"ru": "Правка записи", "en": "Record correction"},
    "usage.kind.merge": {"ru": "Сведение комментария", "en": "Merging a comment"},
    "usage.kind.translate": {"ru": "Перевод", "en": "Translation"},
    "usage.kind.transcribe": {"ru": "Расшифровка голосового", "en": "Voice transcription"},
    "usage.kind.other": {"ru": "Прочее", "en": "Other"},
    "usage.empty.title": {"ru": "За этот период вызовов нет", "en": "No calls in this period"},
    "usage.empty.text": {
        "ru": "Вызовы модели за выбранный период появятся здесь.",
        "en": "Model calls in the selected period will appear here.",
    },
    "usage.failed.short": {"ru": "неудачных: {count}", "en": "failed: {count}"},
    "usage.failed.title": {"ru": "Расход не прочитан", "en": "Usage could not be read"},
    "usage.failed.text": {
        "ru": "База не ответила. Попробуйте обновить страницу.",
        "en": "The database did not answer. Try reloading the page.",
    },
}
