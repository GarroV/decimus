"""Тексты блока «Журнал обхода» на карточке проверки (D710)."""

from __future__ import annotations

WALK_LOG_TEXTS: dict[str, dict[str, str]] = {
    "walklog.title": {"ru": "Журнал обхода", "en": "Walk log"},
    "walklog.sub": {
        "ru": (
            "Что аудитор вводил в мини-аппе и что отвечала система на каждом шаге — "
            "для разбора спорных случаев. Время указано по UTC."
        ),
        "en": (
            "What the auditor entered in the mini-app and what the system answered at each "
            "step, for reviewing disputed cases. Times are UTC."
        ),
    },
    "walklog.unknown": {
        "ru": "Журнал обхода сейчас не прочитался.",
        "en": "The walk log could not be read right now.",
    },
    "walklog.run": {"ru": "Обход: {unit}", "en": "Walk: {unit}"},
    "walklog.who": {"ru": "аудитор {login}", "en": "auditor {login}"},
    "walklog.step.suggest": {"ru": "Подбор пункта", "en": "Item search"},
    "walklog.step.class": {"ru": "Определение класса", "en": "Class check"},
    "walklog.step.class_facts": {"ru": "Уточнение фактов", "en": "Facts clarified"},
    "walklog.step.class_manual": {"ru": "Класс выбран вручную", "en": "Class chosen by hand"},
    "walklog.step.save": {"ru": "Сохранение записи", "en": "Finding saved"},
    "walklog.step.edit": {"ru": "Правка записи", "en": "Finding edited"},
    "walklog.step.remove": {"ru": "Удаление записи", "en": "Finding removed"},
    "walklog.step.other": {"ru": "Другое действие с записью", "en": "Other finding action"},
    "walklog.outcome.ok": {"ru": "прошло", "en": "done"},
    "walklog.outcome.refused": {"ru": "система отказала", "en": "refused"},
    "walklog.outcome.error": {"ru": "сбой", "en": "failure"},
    "walklog.said": {"ru": "Аудитор: «{words}»", "en": "Auditor: “{words}”"},
    "walklog.photos": {"ru": "Фото: {n}", "en": "Photos: {n}"},
    "walklog.item": {"ru": "Пункт: {item}", "en": "Item: {item}"},
    "walklog.zone": {"ru": "Зона: {zone}", "en": "Zone: {zone}"},
    "walklog.level": {"ru": "Класс: {level}", "en": "Class: {level}"},
    "walklog.offered": {"ru": "Система предложила: {offer}", "en": "The system offered: {offer}"},
    "walklog.offered_none": {
        "ru": "Система не нашла подходящего пункта",
        "en": "The system found no matching item",
    },
    "walklog.via.model": {"ru": "Путь: модель", "en": "Path: model"},
    "walklog.via.fast": {
        "ru": "Путь: быстрый поиск без модели",
        "en": "Path: quick search, no model",
    },
    "walklog.via.phrase": {"ru": "Путь: выученная фраза", "en": "Path: learned phrase"},
    "walklog.via.fallback": {
        "ru": "Модель недоступна — пункт выбирается вручную",
        "en": "The model is unavailable, the item is picked by hand",
    },
    "walklog.via.other": {"ru": "Путь: {via}", "en": "Path: {via}"},
    "walklog.verdict.ready": {"ru": "Класс определён", "en": "Class determined"},
    "walklog.verdict.needs_fact": {
        "ru": "Не хватает факта для класса",
        "en": "A fact is missing to decide the class",
    },
    "walklog.verdict.not_established": {
        "ru": "Нарушение по этим фактам не установлено",
        "en": "No violation established from these facts",
    },
    "walklog.verdict.manual": {"ru": "Класс выбран вручную", "en": "Class chosen by hand"},
    "walklog.verdict.other": {"ru": "Вердикт: {verdict}", "en": "Verdict: {verdict}"},
    "walklog.provisional": {
        "ru": "Предварительный класс: {level}",
        "en": "Provisional class: {level}",
    },
    "walklog.reason": {"ru": "Причина: {reason}", "en": "Reason: {reason}"},
    "walklog.question": {"ru": "Вопрос системы: {question}", "en": "System question: {question}"},
    "walklog.facts": {"ru": "Уточнений от аудитора: {n}", "en": "Auditor clarifications: {n}"},
    "walklog.text": {"ru": "Текст записи: «{text}»", "en": "Finding text: “{text}”"},
    "walklog.class_by_system": {
        "ru": "Класс принят от системы",
        "en": "Class taken from the system",
    },
    "walklog.refusal": {"ru": "Отказ: {message}", "en": "Refusal: {message}"},
    "walklog.error": {"ru": "Сбой: {error}", "en": "Failure: {error}"},
    "walklog.duration": {"ru": "{ms} мс", "en": "{ms} ms"},
    "walklog.class.D1": {"ru": "отклонение (D1)", "en": "deviation (D1)"},
    "walklog.class.D2": {"ru": "значительное (D2)", "en": "significant (D2)"},
    "walklog.class.D3": {"ru": "критическое (D3)", "en": "critical (D3)"},
    "walklog.class.D0": {"ru": "замер (D0)", "en": "measurement (D0)"},
    "walklog.class.R": {"ru": "рекомендация", "en": "recommendation"},
}
