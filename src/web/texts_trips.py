"""Тексты поездок «Календаря» (D505, D506): сетка, карточка, план, отказы.

Отдельным модулем, а не строками в `texts.py`: тот уже длиннее предела файла.
Ключи `trip.err.*` — коды отказов `src/db/trips.py` (`TripError.code`).
"""

from __future__ import annotations

TRIP_TEXTS: dict[str, dict[str, str]] = {
    "trip.add": {"ru": "Поездка", "en": "Trip"},
    "trip.new": {"ru": "Новая поездка", "en": "New trip"},
    "trip.title": {"ru": "Поездка", "en": "Trip"},
    "trip.count": {"ru": "поездок: {count}", "en": "trips: {count}"},
    "trip.who": {"ru": "Кто едет", "en": "Who travels"},
    "trip.who.hint": {
        "ru": "Начните писать — подскажем людей вашего пространства. Можно вписать любое имя.",
        "en": "Start typing to see people of your space. Any name can be entered.",
    },
    "trip.who.self": {
        "ru": "Вы планируете свою поездку: исполнитель — вы.",
        "en": "You are planning your own trip: you are the traveller.",
    },
    "trip.who.linked": {"ru": "пользователь", "en": "user"},
    "trip.country": {"ru": "Страна", "en": "Country"},
    "trip.country.none": {"ru": "Не выбрана", "en": "Not selected"},
    "trip.from": {"ru": "С", "en": "From"},
    "trip.to": {"ru": "По", "en": "To"},
    "trip.status": {"ru": "Статус", "en": "Status"},
    "trip.status.planned": {"ru": "Запланирована", "en": "Planned"},
    "trip.status.done": {"ru": "Прошла", "en": "Done"},
    "trip.status.cancelled": {"ru": "Отменена", "en": "Cancelled"},
    "trip.note": {"ru": "Заметка", "en": "Note"},
    "trip.save": {"ru": "Сохранить", "en": "Save"},
    "trip.create": {"ru": "Создать поездку", "en": "Create trip"},
    "trip.saved": {"ru": "Сохранено.", "en": "Saved."},
    "trip.delete": {"ru": "Удалить поездку", "en": "Delete trip"},
    "trip.delete.text": {
        "ru": "Поездка и весь её план будут удалены. Отменить нельзя.",
        "en": "The trip and its whole plan will be deleted. This cannot be undone.",
    },
    "trip.delete.yes": {"ru": "Удалить", "en": "Delete"},
    "trip.readonly": {
        "ru": "Править может админ пространства или сам исполнитель.",
        "en": "Only a space admin or the traveller can edit this trip.",
    },
    "trip.plan": {"ru": "План", "en": "Plan"},
    "trip.plan.empty": {
        "ru": "На этот день ничего не запланировано.",
        "en": "Nothing planned for this day.",
    },
    "trip.plan.after_create": {
        "ru": "План по дням появится после создания поездки.",
        "en": "The day-by-day plan becomes available once the trip is created.",
    },
    "trip.step.add": {"ru": "Добавить в план", "en": "Add to plan"},
    "trip.step.day": {"ru": "День", "en": "Day"},
    "trip.step.at": {"ru": "Время", "en": "Time"},
    "trip.step.kind": {"ru": "Что", "en": "What"},
    "trip.step.unit": {"ru": "Пиццерия", "en": "Pizzeria"},
    "trip.step.unit.none": {"ru": "Без пиццерии", "en": "No pizzeria"},
    "trip.step.body": {"ru": "Подробности", "en": "Details"},
    "trip.step.body.hint": {
        "ru": "Например: «рейс 8:40, встреча с партнёром в офисе»",
        "en": "E.g. “flight 8:40, meeting the partner at the office”",
    },
    "trip.step.delete": {"ru": "Убрать", "en": "Remove"},
    "trip.step.done": {"ru": "проверка {grade}", "en": "inspection {grade}"},
    "trip.kind.road": {"ru": "Дорога", "en": "Travel"},
    "trip.kind.inspection": {"ru": "Проверка", "en": "Inspection"},
    "trip.kind.meeting": {"ru": "Встреча", "en": "Meeting"},
    "trip.kind.other": {"ru": "Другое", "en": "Other"},
    "trip.not_found": {
        "ru": "Поездка не найдена.",
        "en": "Trip not found.",
    },
    "trip.failed": {"ru": "Не сохранено: {reason}", "en": "Not saved: {reason}"},
    "trip.read_failed": {
        "ru": "Поездки не прочитались — сетка показывает только проверки.",
        "en": "Trips could not be read — the grid shows inspections only.",
    },
    "trip.err.space": {"ru": "не опознано пространство", "en": "the space is unknown"},
    "trip.err.db": {"ru": "база недоступна ({what})", "en": "the database is unavailable ({what})"},
    "trip.err.name": {"ru": "укажите, кто едет", "en": "enter who travels"},
    "trip.err.name_long": {
        "ru": "имя длиннее {n} знаков",
        "en": "the name is longer than {n} characters",
    },
    "trip.err.dates": {"ru": "укажите даты поездки", "en": "enter the trip dates"},
    "trip.err.order": {
        "ru": "дата окончания раньше даты начала",
        "en": "the end date is before the start date",
    },
    "trip.err.long": {"ru": "поездка длиннее {n} дней", "en": "the trip is longer than {n} days"},
    "trip.err.status": {"ru": "непонятный статус", "en": "unknown status"},
    "trip.err.note": {
        "ru": "заметка длиннее {n} знаков",
        "en": "the note is longer than {n} characters",
    },
    "trip.err.country": {
        "ru": "страна вне вашего охвата",
        "en": "the country is outside your reach",
    },
    "trip.err.self": {
        "ru": "вы можете планировать только свои поездки",
        "en": "you can only plan your own trips",
    },
    "trip.err.steps_outside": {
        "ru": "в плане есть шаги вне новых дат ({n}) — сначала уберите их",
        "en": "the plan has steps outside the new dates ({n}) — remove them first",
    },
    "trip.err.step_day": {"ru": "день вне дат поездки", "en": "the day is outside the trip dates"},
    "trip.err.step_kind": {"ru": "непонятный вид шага", "en": "unknown step type"},
    "trip.err.step_long": {
        "ru": "текст длиннее {n} знаков",
        "en": "the text is longer than {n} characters",
    },
    "trip.err.step_unit": {
        "ru": "для проверки выберите пиццерию",
        "en": "choose a pizzeria for the inspection",
    },
    "trip.err.step_text": {
        "ru": "напишите, что будет происходить",
        "en": "describe what will happen",
    },
    "trip.err.unit": {
        "ru": "пиццерия вне вашего охвата",
        "en": "the pizzeria is outside your reach",
    },
}
