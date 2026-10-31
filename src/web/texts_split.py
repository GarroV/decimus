"""Human split and its source history; shared by the walk and history card."""

SPLIT_TEXTS: dict[str, dict[str, str]] = {
    "walk.split.save_first": {
        "ru": "Сначала сохраните или отмените текущие правки записи",
        "en": "Save or discard the current finding edits first",
    },
    "walk.split.open": {"ru": "Разделить запись…", "en": "Split this finding…"},
    "walk.split.title": {"ru": "Разделение записи", "en": "Split a finding"},
    "walk.split.source": {"ru": "Исходная запись", "en": "Original finding"},
    "walk.split.history": {"ru": "История разделений", "en": "Split history"},
    "walk.split.part": {"ru": "Часть {n}", "en": "Part {n}"},
    "walk.split.item": {"ru": "Пункт", "en": "Item"},
    "walk.split.level": {"ru": "Класс", "en": "Class"},
    "walk.split.zone": {"ru": "Зона", "en": "Zone"},
    "walk.split.text": {"ru": "Наблюдение", "en": "Observation"},
    "walk.split.comment": {"ru": "Рекомендация", "en": "Recommendation"},
    "walk.split.repeat": {"ru": "Повтор", "en": "Repeat"},
    "walk.split.reading": {
        "ru": "Температура, °C (если есть)",
        "en": "Temperature, °C (if applicable)",
    },
    "walk.split.photo": {"ru": "Фото {n}", "en": "Photo {n}"},
    "walk.split.photo_count": {"ru": "Кадров: {n}", "en": "Photos: {n}"},
    "walk.split.choose": {"ru": "Выберите…", "en": "Choose…"},
    "walk.split.hint": {
        "ru": (
            "Заполните каждую часть и распределите все исходные кадры. "
            "Ничего не копируется автоматически."
        ),
        "en": "Fill in each part and assign every original photo. Nothing is copied automatically.",
    },
    "walk.split.add": {"ru": "Добавить часть", "en": "Add a part"},
    "walk.split.remove": {"ru": "Убрать часть", "en": "Remove part"},
    "walk.split.review": {"ru": "Проверить разделение", "en": "Review split"},
    "walk.split.edit": {"ru": "Вернуться к частям", "en": "Edit parts"},
    "walk.split.shared": {
        "ru": "Подтверждаю: выбранные общие кадры относятся к каждой отмеченной части",
        "en": "I confirm the shared photos belong to every selected part",
    },
    "walk.split.confirmed": {
        "ru": "Я проверил все части, их классы, зоны и назначение кадров",
        "en": "I reviewed every part, its class, zone and photo assignment",
    },
    "walk.split.confirm": {"ru": "Подтвердить разделение", "en": "Confirm split"},
    "walk.split.invalid": {
        "ru": "Выберите пункт, класс, зону и текст каждой части; назначьте все исходные кадры.",
        "en": "Choose an item, class, zone and text for each part; assign every original photo.",
    },
    "walk.split.conflict": {
        "ru": "Исходная запись изменилась. Обновите обход и проверьте разделение заново.",
        "en": "The original finding changed. Refresh the walk and review the split again.",
    },
    "walk.split.saved": {
        "ru": "Запись разделена, исходник сохранён в истории",
        "en": "Finding split; the original is kept in history",
    },
}
