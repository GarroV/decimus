"""Тексты раздела «Проверки» в раскладке «список слева, карточка справа».

Отдельным модулем, а не строками в `texts.py`: тот длиннее предела файла.
Сливаются в общий каталог (`texts.TEXTS`). Здесь только то, что появилось с
правой колонкой и периодом; тексты карточки проверки — в `texts.py` (`card.*`,
`accept.*`, `retract.*`, `move.*`), панель берёт их оттуда же.
"""

from __future__ import annotations

_MONTHS: dict[str, dict[str, str]] = {
    "registry.month.1": {"ru": "Январь", "en": "January"},
    "registry.month.2": {"ru": "Февраль", "en": "February"},
    "registry.month.3": {"ru": "Март", "en": "March"},
    "registry.month.4": {"ru": "Апрель", "en": "April"},
    "registry.month.5": {"ru": "Май", "en": "May"},
    "registry.month.6": {"ru": "Июнь", "en": "June"},
    "registry.month.7": {"ru": "Июль", "en": "July"},
    "registry.month.8": {"ru": "Август", "en": "August"},
    "registry.month.9": {"ru": "Сентябрь", "en": "September"},
    "registry.month.10": {"ru": "Октябрь", "en": "October"},
    "registry.month.11": {"ru": "Ноябрь", "en": "November"},
    "registry.month.12": {"ru": "Декабрь", "en": "December"},
}

_PERIOD: dict[str, dict[str, str]] = {
    "registry.period.label": {"ru": "Период", "en": "Period"},
    "registry.period.all": {"ru": "Всё время", "en": "All time"},
    "registry.period.this_month": {"ru": "Текущий месяц", "en": "This month"},
    "registry.period.from": {"ru": "С", "en": "From"},
    "registry.period.to": {"ru": "По", "en": "To"},
    "registry.period.apply": {"ru": "Показать", "en": "Show"},
    "registry.period.prev": {"ru": "Предыдущий период", "en": "Previous period"},
    "registry.period.next": {"ru": "Следующий период", "en": "Next period"},
    "registry.period.empty.title": {
        "ru": "За этот период проверок нет",
        "en": "No inspections in this period",
    },
    "registry.period.empty.text": {
        "ru": "Листните стрелкой назад или откройте всё время.",
        "en": "Step back with the arrow or show all time.",
    },
}

_BAR: dict[str, dict[str, str]] = {
    "registry.search": {"ru": "Пиццерия", "en": "Pizzeria"},
    "registry.search.apply": {"ru": "Найти", "en": "Search"},
    "registry.filter.reset": {"ru": "Сбросить", "en": "Reset"},
    "registry.history": {"ru": "История", "en": "History"},
}

_PANEL: dict[str, dict[str, str]] = {
    "registry.drawer.title": {"ru": "Проверка", "en": "Inspection"},
    "registry.panel.open": {"ru": "Открыть полностью", "en": "Open in full"},
    "registry.panel.pick_title": {"ru": "Выберите проверку", "en": "Pick an inspection"},
    "registry.panel.pick_text": {
        "ru": "Карточка откроется здесь: оценка, потери по блокам, записи и действия.",
        "en": "The card opens here: score, losses by block, findings and actions.",
    },
    "registry.panel.missing.title": {
        "ru": "Такой проверки нет",
        "en": "No such inspection",
    },
    "registry.panel.missing.text": {
        "ru": "Её нет в вашем охвате или ссылка устарела. Выберите проверку в списке.",
        "en": "It is outside your reach or the link is out of date. Pick one from the list.",
    },
    "registry.panel.failed.title": {
        "ru": "Карточка сейчас не открылась",
        "en": "The card did not open just now",
    },
    "registry.panel.failed.text": {
        "ru": "База не ответила на запрос карточки. Список жив; откройте проверку полностью.",
        "en": "The database did not answer for the card. The list works; open it in full.",
    },
    "registry.panel.score": {"ru": "Итог", "en": "Total"},
    "registry.panel.facts": {"ru": "Проверка", "en": "Inspection"},
    "registry.panel.date": {"ru": "Дата обхода", "en": "Visit date"},
    "registry.panel.kind": {"ru": "Вид", "en": "Kind"},
    "registry.panel.checklist": {"ru": "Чек-лист", "en": "Checklist"},
    "registry.panel.actions": {"ru": "Действия", "en": "Actions"},
    "registry.panel.findings_more": {
        "ru": "Ещё {n} — в полной карточке",
        "en": "{n} more in the full card",
    },
    "registry.panel.review_go": {"ru": "Вычитать и подтвердить", "en": "Review and accept"},
    "registry.panel.review_read": {
        "ru": "Вычитка — в полной карточке: там весь чек-лист по зонам.",
        "en": "Review in the full card: it shows the whole checklist by zone.",
    },
    "registry.panel.move_go": {
        "ru": "Исправить дату или пиццерию",
        "en": "Correct date or pizzeria",
    },
    "registry.panel.plan_go": {"ru": "Запросить экшн-план", "en": "Request an action plan"},
    "registry.panel.retract_text": {
        "ru": "Проверка останется в истории с пометкой и причиной, в отчёты её числа не пойдут.",
        "en": "The inspection stays in history, marked with the reason; its numbers leave reports.",
    },
}

REGISTRY_TEXTS: dict[str, dict[str, str]] = {**_MONTHS, **_PERIOD, **_BAR, **_PANEL}
