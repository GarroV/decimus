"""Server refusals for explicit technical checkpoint confirmations."""

TECHNICAL_ERROR_TEXTS = {
    "walk.technical.err.invalid": {
        "ru": "Не удалось принять отметку. Обновите экран и повторите.",
        "en": "The confirmation could not be accepted. Refresh and try again.",
    },
    "walk.technical.err.stale": {
        "ru": "Проверка изменилась. Обновите экран перед подтверждением.",
        "en": "The inspection changed. Refresh before confirming.",
    },
    "walk.technical.err.photo": {
        "ru": "Для этого пункта нужна запись с фотографией и комментарием.",
        "en": "This checkpoint requires a finding with a photo and comment.",
    },
    "walk.technical.err.reason": {
        "ru": "Укажите, почему этот пункт неприменим.",
        "en": "Explain why this checkpoint is not applicable.",
    },
    "walk.technical.err.issue": {
        "ru": "Выберите подходящую запись с фотографией и комментарием.",
        "en": "Select a matching finding with a photo and comment.",
    },
    "walk.technical.err.pending": {
        "ru": "Подтвердите обязательные пункты технического состояния перед завершением проверки.",
        "en": "Confirm the required technical checkpoints before completing this inspection.",
    },
}
