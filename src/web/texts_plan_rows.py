"""Тексты электронного плана исправлений (#1168): строки, путь, начало отсчёта, события.

Отдельным модулем: `texts_plans.py` и `texts.py` уже длиннее предела файла. Сливаются
в общий каталог (`texts.TEXTS`) со сверкой пересечений ключей. Уведомления плана —
в `texts_notifications.py` (`notif.plan_*`).
"""

from __future__ import annotations

PLAN_ROW_TEXTS: dict[str, dict[str, str]] = {
    # --- состояния и блоки списка ------------------------------------------
    "plans.state.in_work": {"ru": "В работе", "en": "In progress"},
    "plans.state.closed": {"ru": "Закрыт", "en": "Closed"},
    "plans.block.in_work": {"ru": "В работе", "en": "In progress"},
    "plans.rail.in_work": {"ru": "в работе {n}", "en": "in progress {n}"},
    "plans.overdue_rows": {"ru": "Просрочено строк: {n}", "en": "Overdue rows: {n}"},
    # --- история -----------------------------------------------------------
    "plans.event.submitted": {
        "ru": "План отправлен на согласование",
        "en": "Plan sent for approval",
    },
    "plans.event.closed": {"ru": "План закрыт", "en": "Plan closed"},
    "plans.event.count_from_changed": {
        "ru": "Изменено начало отсчёта срока",
        "en": "Deadline start date changed",
    },
    "plans.event.row_started": {"ru": "Строка взята в работу", "en": "Row taken into work"},
    "plans.event.row_done": {"ru": "Строка сделана", "en": "Row marked done"},
    "plans.event.row_confirmed": {"ru": "Строка подтверждена", "en": "Row confirmed"},
    "plans.event.row_returned": {"ru": "Строка возвращена", "en": "Row returned"},
    # --- строки ------------------------------------------------------------
    "plans.rows.title": {"ru": "Строки плана", "en": "Plan rows"},
    "plans.rows.hint_fill": {
        "ru": "По каждому нарушению — что сделаете и кто отвечает. Свой срок можно поставить "
        "раньше положенного; позже — только переносом с согласием УК.",
        "en": "For each violation, say what you will do and who is responsible. You may set your "
        "own date earlier than the standard one; later only by an extension agreed with HQ.",
    },
    "plans.rows.hint_review_partner": {
        "ru": "План на согласовании. Строки снова правятся, если его вернут.",
        "en": "The plan is under review. Rows become editable again if it is returned.",
    },
    "plans.rows.hint_review_hq": {
        "ru": "Проверьте меры и сроки по строкам: примите план или верните с комментарием.",
        "en": "Check the measures and dates row by row: accept the plan or return it with a comment.",
    },
    "plans.rows.hint_work_partner": {
        "ru": "План принят. По каждой строке: «Взяли в работу», затем «Сделано».",
        "en": "The plan is accepted. For each row: “Taken into work”, then “Done”.",
    },
    "plans.rows.hint_work_hq": {
        "ru": "Когда партнёр отметит строку сделанной, подтвердите её или верните с причиной.",
        "en": "When the partner marks a row done, confirm it or return it with a reason.",
    },
    "plans.rows.hint_closed": {
        "ru": "Все строки подтверждены, план закрыт.",
        "en": "All rows are confirmed; the plan is closed.",
    },
    "plans.rows.due": {"ru": "срок {date}", "en": "due {date}"},
    "plans.rows.due_own": {"ru": "срок {date} (свой)", "en": "due {date} (own)"},
    "plans.rows.overdue": {"ru": "Просрочена", "en": "Overdue"},
    "plans.rows.status.filling": {"ru": "Заполняется", "en": "Being filled in"},
    "plans.rows.status.in_work": {"ru": "В работе", "en": "In progress"},
    "plans.rows.status.done": {"ru": "Сделано, ждёт подтверждения", "en": "Done, awaiting confirmation"},
    "plans.rows.status.confirmed": {"ru": "Подтверждена", "en": "Confirmed"},
    "plans.rows.status.returned": {"ru": "Возвращена", "en": "Returned"},
    "plans.rows.returned_reason": {"ru": "Причина возврата: «{reason}»", "en": "Reason for return: “{reason}”"},
    "plans.rows.measure": {"ru": "Что сделаем", "en": "What we will do"},
    "plans.rows.responsible": {"ru": "Кто отвечает", "en": "Who is responsible"},
    "plans.rows.reason": {"ru": "Почему так вышло (по желанию)", "en": "Why it happened (optional)"},
    "plans.rows.own_due": {"ru": "Свой срок, не позже {due}", "en": "Own date, no later than {due}"},
    "plans.rows.save": {"ru": "Сохранить строку", "en": "Save row"},
    "plans.rows.empty": {"ru": "Строк в плане нет.", "en": "The plan has no rows."},
    "plans.rows.not_filled": {"ru": "не заполнено", "en": "not filled in"},
    "plans.rows.saved": {"ru": "Строка сохранена.", "en": "Row saved."},
    # --- отправка и ход ----------------------------------------------------
    "plans.rows.submit": {"ru": "Отправить на согласование", "en": "Send for approval"},
    "plans.rows.submit_hint": {
        "ru": "Доступно, когда у каждой строки есть мера и ответственный: заполнено {n} из {total}.",
        "en": "Available once every row has a measure and an owner: {n} of {total} filled in.",
    },
    "plans.rows.submitted": {
        "ru": "План отправлен на согласование.",
        "en": "The plan was sent for approval.",
    },
    "plans.rows.start": {"ru": "Взяли в работу", "en": "Taken into work"},
    "plans.rows.finish": {"ru": "Сделано", "en": "Done"},
    "plans.rows.confirm": {"ru": "Подтвердить", "en": "Confirm"},
    "plans.rows.reject": {"ru": "Вернуть", "en": "Return"},
    "plans.rows.reject_reason": {"ru": "Причина возврата", "en": "Reason for return"},
    "plans.rows.started": {"ru": "Строка взята в работу.", "en": "Row taken into work."},
    "plans.rows.finished": {
        "ru": "Строка отмечена сделанной и ушла на подтверждение.",
        "en": "Row marked done and sent for confirmation.",
    },
    "plans.rows.confirmed": {"ru": "Строка подтверждена.", "en": "Row confirmed."},
    "plans.rows.rejected": {"ru": "Строка возвращена партнёру.", "en": "Row returned to the partner."},
    "plans.rows.confirmed_closed": {
        "ru": "Строка подтверждена. Все строки подтверждены — план закрыт.",
        "en": "Row confirmed. All rows are confirmed — the plan is closed.",
    },
    "plans.rows.file_later": {
        "ru": "План электронный: строки заполняются здесь. Файл туда и обратно появится позже.",
        "en": "This plan is electronic: fill in the rows here. File round-trip is coming later.",
    },
    # --- начало отсчёта (D613) ---------------------------------------------
    "plans.count_from.title": {"ru": "Начало отсчёта срока", "en": "Deadline start date"},
    "plans.count_from.hint": {
        "ru": "От этой даты считаются срок ответа планом и сроки строк. Сдвиг пересчитывает "
        "их все, кроме перенесённых с согласием.",
        "en": "The plan deadline and row deadlines count from this date. Moving it recalculates "
        "them all, except rows extended by agreement.",
    },
    "plans.count_from.submit": {"ru": "Сдвинуть отсчёт", "en": "Move the start"},
    "plans.count_from.field": {"ru": "Считать срок от", "en": "Count the deadline from"},
    "plans.count_from.set": {
        "ru": "Начало отсчёта изменено, сроки пересчитаны.",
        "en": "The start date was changed and the deadlines recalculated.",
    },
    "plans.count_from.shown": {"ru": "Отсчёт от", "en": "Counted from"},
}
