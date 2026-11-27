"""Подписи чек-листа исправлений принятой проверки, RU/EN."""

REPAIR_TEXTS = {
    "repair.title": {"ru": "Исправления", "en": "Corrections"},
    "repair.link": {"ru": "Исправление", "en": "Correction"},
    "repair.progress": {"ru": "Закрыто {closed} из {total}", "en": "{closed} of {total} closed"},
    "repair.hint": {
        "ru": (
            "Список сформирован из нарушений проверки. Добавьте подтверждения и "
            "передайте исправление проверяющему. Закрытие подтверждает проверяющий."
        ),
        "en": (
            "Generated from inspection findings. Add evidence and submit the "
            "correction for review. A reviewer confirms closure."
        ),
    },
    "repair.status.open": {"ru": "Нужно исправить", "en": "To correct"},
    "repair.status.submitted": {"ru": "На проверке", "en": "Awaiting review"},
    "repair.status.confirmed": {"ru": "Закрыто", "en": "Closed"},
    "repair.original": {"ru": "Фото из проверки", "en": "Inspection photos"},
    "repair.evidence": {"ru": "Подтверждения и комментарии", "en": "Evidence and comments"},
    "repair.no_evidence": {"ru": "Подтверждений пока нет.", "en": "No evidence yet."},
    "repair.photo": {"ru": "Фото исправления", "en": "Correction photo"},
    "repair.comment": {"ru": "Комментарий к исправлению", "en": "Correction comment"},
    "repair.comment.hint": {
        "ru": "Что исправлено или что нужно уточнить…",
        "en": "Describe the correction or ask a question…",
    },
    "repair.file": {"ru": "Фото или документ", "en": "Photo or document"},
    "repair.add": {"ru": "Добавить подтверждение", "en": "Add evidence"},
    "repair.submit": {"ru": "Передать на проверку", "en": "Submit for review"},
    "repair.confirm": {
        "ru": "Подтвердить исправление и закрыть",
        "en": "Confirm correction and close",
    },
    "repair.return": {"ru": "Вернуть на доработку", "en": "Return for correction"},
    "repair.reopen": {"ru": "Открыть повторно", "en": "Reopen"},
    "repair.reason": {"ru": "Причина", "en": "Reason"},
    "repair.closed_hint": {
        "ru": (
            "Исправление подтверждено. Материалы сохранены; обсуждение всей проверки доступно ниже."
        ),
        "en": (
            "Correction confirmed. Evidence is preserved; the inspection discussion "
            "remains available below."
        ),
    },
    "repair.history": {"ru": "История исправления", "en": "Correction history"},
    "repair.empty": {
        "ru": "Нарушений для исправления нет.",
        "en": "No findings requiring correction.",
    },
    "repair.event.evidence": {"ru": "Добавлены материалы", "en": "Evidence added"},
    "repair.event.submitted": {"ru": "Передано на проверку", "en": "Submitted for review"},
    "repair.event.confirmed": {"ru": "Исправление подтверждено", "en": "Correction confirmed"},
    "repair.event.returned": {"ru": "Возвращено на доработку", "en": "Returned for correction"},
    "repair.event.reopened": {"ru": "Открыто повторно", "en": "Reopened"},
    "repair.error.conflict": {
        "ru": "Материалы изменились. Обновите страницу и проверьте актуальную версию.",
        "en": "Evidence has changed. Refresh the page and review the current version.",
    },
    "repair.error.reason": {
        "ru": "Укажите причину длиной до 5000 знаков.",
        "en": "Enter a reason up to 5000 characters.",
    },
    "repair.error.evidence": {
        "ru": "Сначала добавьте подтверждение исправления.",
        "en": "Add correction evidence first.",
    },
    "repair.error.missing": {
        "ru": "Пункт исправления недоступен.",
        "en": "Correction item is unavailable.",
    },
    "repair.error.state": {
        "ru": "Состояние изменилось. Обновите страницу.",
        "en": "The status has changed. Refresh the page.",
    },
    "repair.error.review": {
        "ru": "Подтверждать исправление может проверяющий этого пространства.",
        "en": "Only a reviewer from the inspection's space can confirm the correction.",
    },
    "repair.error.actor": {
        "ru": "Не определён автор изменения.",
        "en": "The author could not be identified.",
    },
    "repair.error.action": {"ru": "Действие недоступно.", "en": "Action unavailable."},
    "work.error.item": {
        "ru": "Пункт закрыт или недоступен. Обновите страницу.",
        "en": "The item is closed or unavailable. Refresh the page.",
    },
}
