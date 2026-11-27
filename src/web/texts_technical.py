"""Technical condition report and comparison labels, RU/EN."""

TECHNICAL_TEXTS = {
    "technical.matrix.ok": {"ru": "Исправно", "en": "Working"},
    "technical.matrix": {
        "ru": "История технического состояния",
        "en": "Technical condition history",
    },
    "technical.matrix.point": {"ru": "Контрольная точка", "en": "Checkpoint"},
    "technical.matrix.absent": {"ru": "Нет данных", "en": "No data"},
    "technical.matrix.note": {
        "ru": (
            "Эта проверка и до пяти предыдущих принятых проверок. "
            "Нет данных — пункт тогда не проверялся явно."
        ),
        "en": (
            "This inspection and up to five previous accepted inspections. "
            "No data means no explicit check was recorded."
        ),
    },
    "refusal.domain.accept_technical_pending": {
        "ru": "Повторно подтвердите технические пункты после правки связанных записей.",
        "en": "Reconfirm the technical checkpoints after editing their linked records.",
    },
    "technical.confirm": {"ru": "Подтвердить ответ", "en": "Confirm answer"},
    "technical.reviewed": {
        "ru": "Я проверил пункт и подтверждаю выбранный ответ",
        "en": "I checked this checkpoint and confirm the selected answer",
    },
    "technical.answer": {"ru": "Результат осмотра", "en": "Inspection result"},
    "technical.reason": {"ru": "Причина / комментарий", "en": "Reason / comment"},
    "technical.evidence": {"ru": "Связанная запись", "en": "Linked record"},
    "technical.saved": {"ru": "Ответ подтверждён", "en": "Answer confirmed"},
    "technical.failed": {
        "ru": "Ответ не сохранён. Проверьте результат, связанную запись и причину неприменимости.",
        "en": "Answer not saved. Check the result, linked record and reason for non-applicability.",
    },
    "technical.title": {"ru": "Техническое состояние", "en": "Technical condition"},
    "technical.absent": {
        "ru": "В этой проверке явное подтверждение технического состояния не собиралось.",
        "en": "This inspection did not collect explicit technical confirmations.",
    },
    "technical.coverage": {
        "ru": "Проверено {checked} из {total}",
        "en": "Checked {checked} of {total}",
    },
    "technical.note": {
        "ru": "Подтверждения относятся к дате проверки. Нарушения учтены в записях один раз.",
        "en": (
            "Confirmations describe the inspection date. "
            "Violations are counted once in the records."
        ),
    },
    "technical.pending": {"ru": "Не проверено", "en": "Not checked"},
    "technical.ok": {"ru": "Проверено — исправно", "en": "Checked — working"},
    "technical.issue": {"ru": "Нарушение", "en": "Violation"},
    "technical.na": {"ru": "Не применимо", "en": "Not applicable"},
    "technical.recorded": {"ru": "Данные зафиксированы", "en": "Evidence recorded"},
    "technical.finding": {"ru": "Запись № {n}", "en": "Record #{n}"},
    "technical.previous": {
        "ru": "Предыдущая проверка: {date}",
        "en": "Previous inspection: {date}",
    },
    "technical.no_previous": {
        "ru": "Предыдущей проверки для сравнения нет.",
        "en": "No previous inspection to compare.",
    },
    "technical.previous_absent": {
        "ru": "В предыдущей проверке эти данные не собирались.",
        "en": "The previous inspection did not collect these data.",
    },
    "technical.previous_failed": {
        "ru": "Сравнение сейчас недоступно. Результаты этой проверки показаны ниже.",
        "en": "Comparison is unavailable. This inspection's results are shown below.",
    },
    "technical.fixed": {"ru": "Исправлено", "en": "Fixed"},
    "technical.new_issue": {"ru": "Новое нарушение", "en": "New violation"},
    "technical.persists": {"ru": "Нарушение сохраняется", "en": "Violation persists"},
    "technical.unchanged": {"ru": "Без изменений", "en": "Unchanged"},
    "technical.uncompared": {"ru": "Нет сопоставимого ответа", "en": "No comparable answer"},
    "technical.details": {"ru": "Все контрольные точки", "en": "All checkpoints"},
}
