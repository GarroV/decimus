"""Manual edit history and recoverable, revision-bound edit drafts."""

EDIT_TEXTS = {
    "walk.edit.photo_refs": {
        "ru": "Ссылок на кадры на момент правки: {n}",
        "en": "Photo references at the time of edit: {n}",
    },
    "walk.edit.clarification": {"ru": "Уточнение класса", "en": "Class clarification"},
    "walk.edit.question": {"ru": "Вопрос системы", "en": "System question"},
    "walk.edit.answer": {"ru": "Ответ аудитора", "en": "Auditor answer"},
    "walk.edit.conflict": {
        "ru": "Запись изменилась. Обновите обход и проверьте правку заново.",
        "en": "The record changed. Refresh the walk and review your edit.",
    },
    "walk.edit.history": {"ru": "История изменений", "en": "Change history"},
    "walk.edit.before": {"ru": "До правки", "en": "Before edit"},
    "walk.edit.after": {"ru": "После правки", "en": "After edit"},
    "walk.edit.recovery": {
        "ru": "Сохранённая правка прежней версии",
        "en": "Saved edit of an earlier version",
    },
    "walk.edit.changed": {
        "ru": (
            "Запись изменилась после сохранения черновика. "
            "Сравните значения перед переносом. Исходная копия сохранится."
        ),
        "en": (
            "The record changed after this draft was saved. "
            "Compare the values before restoring. The source copy will be kept."
        ),
    },
    "walk.edit.restore": {
        "ru": "Перенести правку и новые кадры",
        "en": "Restore edit and new photos",
    },
    "walk.edit.discard": {"ru": "Удалить этот черновик", "en": "Discard this draft"},
    "walk.edit.removed": {"ru": "Снятых кадров: {n}", "en": "Removed photos: {n}"},
    "walk.edit.pending": {"ru": "Новых кадров в черновике: {n}", "en": "New draft photos: {n}"},
    "walk.edit.photo_recovery": {
        "ru": "Кадры прежней версии сохранены отдельно. Перенос требует явного нажатия кнопки.",
        "en": (
            "Earlier-version photos are kept separately. "
            "Use the restore button to explicitly transfer them."
        ),
    },
}
