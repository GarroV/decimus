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
    "registry.period.this_month": {"ru": "Этот месяц", "en": "This month"},
    "registry.period.last_month": {"ru": "Прошлый месяц", "en": "Last month"},
    "registry.period.pick_end": {
        "ru": "Выберите конец периода",
        "en": "Pick the end of the period",
    },
    "registry.period.pick_start": {
        "ru": "Выберите начало периода",
        "en": "Pick the start of the period",
    },
    "registry.period.prev_month": {"ru": "Предыдущий месяц", "en": "Previous month"},
    "registry.period.next_month": {"ru": "Следующий месяц", "en": "Next month"},
    "registry.weekdays": {"ru": "Пн Вт Ср Чт Пт Сб Вс", "en": "Mo Tu We Th Fr Sa Su"},
    "registry.period.from": {"ru": "С", "en": "From"},
    "registry.period.to": {"ru": "По", "en": "To"},
    "registry.period.apply": {"ru": "Применить", "en": "Apply"},
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
    "registry.filters.title": {"ru": "Отбор", "en": "Filters"},
    "registry.accepted.title": {"ru": "Принятые", "en": "Accepted"},
    "registry.accepted.hint": {
        "ru": "Период и отбор действуют на принятые проверки, новые — сверху.",
        "en": "The period and filters apply to accepted inspections, newest first.",
    },
    "registry.unchecked.label": {"ru": "Пиццерии без проверки", "en": "Pizzerias without inspection"},
    "registry.unchecked.apply": {"ru": "Применить", "en": "Apply"},
}

_PANEL: dict[str, dict[str, str]] = {
    "registry.drawer.title": {"ru": "Проверка", "en": "Inspection"},
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
        "ru": "База не ответила на запрос карточки. Список жив; откройте проверку ещё раз.",
        "en": "The database did not answer for the card. The list works; try opening it again.",
    },
    "registry.panel.score": {"ru": "Итог", "en": "Total"},
    "registry.panel.facts": {"ru": "Проверка", "en": "Inspection"},
    "registry.panel.date": {"ru": "Дата обхода", "en": "Visit date"},
    "registry.panel.kind": {"ru": "Вид", "en": "Kind"},
    "registry.panel.checklist": {"ru": "Чек-лист", "en": "Checklist"},
    "registry.panel.retry": {"ru": "Повторить", "en": "Try again"},
    "registry.panel.net_error": {
        "ru": "Не удалось связаться с сервером. Попробуйте ещё раз.",
        "en": "Could not reach the server. Please try again.",
    },
}

# «Где нужно проверить» (D399; с «Главной» на «Проверки» в D418, оттуда в «Календарь» в D466).
_TOCHECK: dict[str, dict[str, str]] = {
    "registry.tocheck.title": {"ru": "Где не проведено", "en": "Not inspected yet"},
    "registry.tocheck.hint": {
        "ru": "Нет проверок за период: ни разу не проверенные — первыми, затем ждущие дольше.",
        "en": "No inspections in the period: never inspected first, then waiting longest.",
    },
    "registry.tocheck.last": {"ru": "последняя {date}", "en": "last {date}"},
    "registry.tocheck.never": {"ru": "ни разу не проверяли", "en": "never inspected"},
    "registry.tocheck.empty": {
        "ru": "За этот период везде проверено.",
        "en": "Every unit has an inspection in this period.",
    },
    "registry.tocheck.failed": {
        "ru": "Список не загрузился: база не ответила. Обновите страницу.",
        "en": "The list did not load: the database did not answer. Reload the page.",
    },
}

# Сетка «Календаря» (D497): дни недели с понедельника, клетка дня, пустой месяц.
_CALENDAR: dict[str, dict[str, str]] = {
    "calendar.period.next_month": {"ru": "Следующий месяц", "en": "Next month"},
    "calendar.wd.1": {"ru": "Пн", "en": "Mon"},
    "calendar.wd.2": {"ru": "Вт", "en": "Tue"},
    "calendar.wd.3": {"ru": "Ср", "en": "Wed"},
    "calendar.wd.4": {"ru": "Чт", "en": "Thu"},
    "calendar.wd.5": {"ru": "Пт", "en": "Fri"},
    "calendar.wd.6": {"ru": "Сб", "en": "Sat"},
    "calendar.wd.7": {"ru": "Вс", "en": "Sun"},
    "calendar.count": {"ru": "проверок: {count}", "en": "inspections: {count}"},
    "calendar.more": {"ru": "ещё {count}", "en": "{count} more"},
    "calendar.empty": {
        "ru": "За этот период проверок нет.",
        "en": "No inspections in this period.",
    },
}

REGISTRY_TEXTS: dict[str, dict[str, str]] = {
    **_MONTHS,
    **_PERIOD,
    **_BAR,
    **_PANEL,
    **_TOCHECK,
    **_CALENDAR,
}
