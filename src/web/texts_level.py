"""A selected item's severity is a read-only criterion check, never a fallback guess."""

LEVEL_TEXTS: dict[str, dict[str, str]] = {
    "walk.level.too_large": {
        "ru": "Сократите текст или число/размер кадров для проверки класса.",
        "en": "Reduce the text or number/size of photos for this class check.",
    },
    "walk.level.missing_facts": {
        "ru": "Опишите наблюдение, подтвердите показание или назначьте кадр выбранному пункту.",
        "en": (
            "Describe the observation, confirm a reading, or assign a photo to the selected item."
        ),
    },
    "walk.level.reading_unconfirmed": {
        "ru": "Подтвердите показание термометра сами перед проверкой класса.",
        "en": "Confirm the thermometer reading yourself before checking the class.",
    },
    "walk.level.no_criteria": {
        "ru": "У выбранного пункта нет критериев в издании этой проверки. Выберите класс вручную.",
        "en": (
            "This inspection's edition has no criteria for the selected item. "
            "Choose the class manually."
        ),
    },
    "walk.level.changed": {
        "ru": (
            "Проверка или издание изменились. Выберите пункт и проверьте актуальные факты заново."
        ),
        "en": (
            "The inspection or edition changed. Select the item and check the current facts again."
        ),
    },
}
