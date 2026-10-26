"""Тексты экрана «Обучение» (D578, #906): колонка, плитки, списки, пустое состояние.

Отдельным модулем, как у «Стран» (`texts_country.py`): `texts.py` уже длиннее предела
файла. Сливаются в общий каталог (`texts.TEXTS`) — `t()` знает один словарь.
"""

from __future__ import annotations

TRAINING_TEXTS: dict[str, dict[str, str]] = {
    "section.training.title": {"ru": "Обучение", "en": "Training"},
    "training.kicker.network": {"ru": "Обучение · сеть", "en": "Training · network"},
    "training.kicker.country": {"ru": "Обучение · страна", "en": "Training · country"},
    "training.network": {"ru": "Все страны", "en": "All countries"},
    "training.filter.title": {"ru": "Страны и пиццерии", "en": "Countries and pizzerias"},
    "training.rail.units": {"ru": "пиццерий: {n}", "en": "pizzerias: {n}"},
    "training.asof": {"ru": "Данные на {date}", "en": "Data as of {date}"},
    "training.asof.hint": {
        "ru": "Состояние на день последней загрузки из iSpring; обновляется раз в сутки.",
        "en": "State on the day of the last iSpring load; refreshed once a day.",
    },
    "training.tile.trained": {"ru": "Обученность", "en": "Trained"},
    "training.tile.trained_sub": {
        "ru": "завершено {done} из {total} курсов",
        "en": "{done} of {total} courses completed",
    },
    "training.tile.trained_hint": {
        "ru": "Завершённые курсы к назначенным: из сумм, а не среднее по пиццериям.",
        "en": "Completed courses over assigned ones: from sums, not an average of pizzerias.",
    },
    "training.tile.people": {"ru": "Полностью обучены", "en": "Fully trained"},
    "training.tile.people_sub": {
        "ru": "{done} из {total} сотрудников",
        "en": "{done} of {total} employees",
    },
    "training.tile.people_hint": {
        "ru": "Сотрудники, у которых завершено всё назначенное. Имён и списков людей не храним.",
        "en": "Employees who completed everything assigned. No names or people lists are stored.",
    },
    "training.tile.overdue": {"ru": "Просрочено", "en": "Overdue"},
    "training.tile.overdue_sub": {
        "ru": "назначений с истёкшим сроком",
        "en": "past-due assignments",
    },
    "training.tile.overdue_hint": {
        "ru": "Назначения с истёкшим сроком, которые не завершены.",
        "en": "Assignments past their due date that are not completed.",
    },
    "training.tile.time": {"ru": "Среднее время на курс", "en": "Average time per course"},
    "training.tile.time_sub": {
        "ru": "по {n} завершённым с данными о времени",
        "en": "over {n} completed with time data",
    },
    "training.tile.time_hint": {
        "ru": "Только завершённые курсы, по которым iSpring отдаёт время.",
        "en": "Completed courses only, where iSpring reports time spent.",
    },
    "training.tile.pass": {"ru": "Сдали тест", "en": "Passed the test"},
    "training.tile.pass_sub": {
        "ru": "по {n} попыткам с итогом",
        "en": "over {n} attempts with a result",
    },
    "training.tile.pass_hint": {
        "ru": "Сдали / (сдали + не сдали); курсы без теста не считаются.",
        "en": "Passed / (passed + failed); courses without a test are not counted.",
    },
    "training.dur.min": {"ru": "{n} мин", "en": "{n} min"},
    "training.dur.hour": {"ru": "{h} ч {m} мин", "en": "{h} h {m} min"},
    "training.block.countries": {
        "ru": "Страны — хуже всего сверху",
        "en": "Countries — worst first",
    },
    "training.block.units": {"ru": "Пиццерии — хуже всего сверху", "en": "Pizzerias — worst first"},
    "training.block.courses": {"ru": "Курсы", "en": "Courses"},
    "training.block.courses_hint": {
        "ru": "по числу назначений",
        "en": "by number of assignments",
    },
    "training.block.courses_cut": {
        "ru": "Показаны {shown} из {total}",
        "en": "Showing {shown} of {total}",
    },
    "training.col.name": {"ru": "Название", "en": "Name"},
    "training.col.trained": {"ru": "Обученность", "en": "Trained"},
    "training.col.assigned": {"ru": "Назначено", "en": "Assigned"},
    "training.col.completed": {"ru": "Завершено", "en": "Completed"},
    "training.col.overdue": {"ru": "Просрочено", "en": "Overdue"},
    "training.col.time": {"ru": "Время", "en": "Time"},
    "training.nothing": {
        "ru": "У выбранного нет назначенных курсов.",
        "en": "The selection has no assigned courses.",
    },
    "training.lost.title": {"ru": "Не сопоставлены", "en": "Not matched"},
    "training.lost.hint": {
        "ru": "Подразделения iSpring, которые не нашлись среди пиццерий рейтингов: в цифры "
        "страны и сети не входят",
        "en": "iSpring departments with no pizzeria in the ratings: not included in country "
        "and network figures",
    },
    "training.empty.title": {
        "ru": "Данные из iSpring ещё не загружены",
        "en": "iSpring data is not loaded yet",
    },
    "training.empty.text": {
        "ru": "Загрузка идёт раз в сутки, как только заданы ключи iSpring. После первой "
        "загрузки здесь появятся страны и пиццерии.",
        "en": "The load runs once a day as soon as the iSpring keys are set. After the first "
        "load, countries and pizzerias will appear here.",
    },
    "training.empty.keys": {
        "ru": "Ключи iSpring ставятся на экране «Ключи и API»",
        "en": "The iSpring keys are set on the Keys & API screen",
    },
    "training.empty.keys_open": {"ru": "Открыть «Ключи и API»", "en": "Open Keys & API"},
    "training.empty.ask": {
        "ru": "Ключи ставит главный администратор.",
        "en": "The keys are set by the main administrator.",
    },
    "training.failed": {
        "ru": "Данные об обучении сейчас не прочитались. Попробуйте позже.",
        "en": "Training data could not be read right now. Try again later.",
    },
}
