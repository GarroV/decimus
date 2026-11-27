"""Подписи экрана явного контроля технического состояния в обходе."""

TECHNICAL_UI_TEXTS = {
    "walk.technical.guidance": {"ru": "Что проверить", "en": "What to check"},
    "walk.technical.title": {"ru": "На контроле", "en": "Focus checks"},
    "walk.technical.subtitle": {
        "ru": "Техническое состояние · подтвердите каждый важный пункт",
        "en": "Technical condition · confirm each important check",
    },
    "walk.technical.progress": {
        "ru": "Подтверждено: {done} из {total}",
        "en": "Confirmed: {done} of {total}",
    },
    "walk.technical.remaining": {
        "ru": "Обязательных без ответа: {count}",
        "en": "Required checks remaining: {count}",
    },
    "walk.technical.open": {"ru": "Все контрольные точки →", "en": "All focus checks →"},
    "walk.technical.zone": {"ru": "Зона", "en": "Zone"},
    "walk.technical.all_zones": {"ru": "Все зоны", "en": "All zones"},
    "walk.technical.show": {"ru": "Показать", "en": "Show"},
    "walk.technical.filter.pending": {"ru": "Без ответа", "en": "Unanswered"},
    "walk.technical.filter.all": {"ru": "Все пункты", "en": "All checks"},
    "walk.technical.filter.issue": {"ru": "С замечаниями", "en": "With issues"},
    "walk.technical.required": {"ru": "Обязательный", "en": "Required"},
    "walk.technical.optional": {"ru": "При наличии", "en": "If applicable"},
    "walk.technical.status.pending": {"ru": "Не проверено", "en": "Not checked"},
    "walk.technical.status.ok": {"ru": "Проверено · всё хорошо", "en": "Checked · all good"},
    "walk.technical.status.issue": {"ru": "Есть замечание", "en": "Issue recorded"},
    "walk.technical.status.recorded": {"ru": "Сведения записаны", "en": "Information recorded"},
    "walk.technical.status.na": {"ru": "Не применяется", "en": "Not applicable"},
    "walk.technical.ok": {"ru": "✓ Проверено, всё хорошо", "en": "✓ Checked, all good"},
    "walk.technical.issue": {"ru": "Есть замечание…", "en": "Record an issue…"},
    "walk.technical.info": {"ru": "Фото и сведения…", "en": "Photo and information…"},
    "walk.technical.link": {"ru": "Учесть существующую запись…", "en": "Use an existing finding…"},
    "walk.technical.link_hint": {
        "ru": "В обходе уже есть подходящие записи. Подтвердите, какая относится к этому пункту.",
        "en": "Matching findings exist in this walk. Confirm which belongs to this check.",
    },
    "walk.technical.choose": {"ru": "Выберите запись", "en": "Choose a finding"},
    "walk.technical.new": {"ru": "Добавить новую запись", "en": "Add a new finding"},
    "walk.technical.choose_item": {"ru": "Что требует внимания?", "en": "What needs attention?"},
    "walk.technical.na": {"ru": "Не применяется…", "en": "Not applicable…"},
    "walk.technical.reason": {
        "ru": "Почему пункт не применяется?",
        "en": "Why does this check not apply?",
    },
    "walk.technical.reason_hint": {
        "ru": "Например: в пиццерии нет террасы. Причина войдёт в отчёт.",
        "en": "For example: this pizzeria has no terrace. The reason goes into the report.",
    },
    "walk.technical.save": {"ru": "Сохранить причину", "en": "Save reason"},
    "walk.technical.cancel": {"ru": "Отмена", "en": "Cancel"},
    "walk.technical.reset": {"ru": "Снять подтверждение", "en": "Clear confirmation"},
    "walk.technical.empty": {
        "ru": "По выбранному фильтру пунктов нет",
        "en": "No checks match this filter",
    },
    "walk.technical.saved": {"ru": "Ответ сохранён", "en": "Response saved"},
    "walk.technical.after_record": {
        "ru": "После сохранения записи вернитесь в «На контроле» и подтвердите её связь с пунктом.",
        "en": "After saving, return to Focus checks and confirm the finding belongs to this check.",
    },
    "walk.technical.finish_blocked": {
        "ru": "Перед завершением подтвердите обязательные пункты технического состояния.",
        "en": "Confirm the required technical checks before finishing.",
    },
}
