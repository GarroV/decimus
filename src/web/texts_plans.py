"""Тексты экшн-планов (волна 2): раздел УК, раздел партнёра, блоки страны и карточки.

Отдельным модулем, а не строками в `texts.py`: тот уже длиннее предела файла.
Сливаются в общий каталог (`texts.TEXTS`) — `t()` знает один словарь.
Имена разделов рабочие (#462).
"""

from __future__ import annotations

PLAN_TEXTS: dict[str, dict[str, str]] = {
    "section.actions.title": {"ru": "Действия", "en": "Actions"},
    # --- состояние и версии ------------------------------------------------
    "plans.state.requested": {"ru": "Ждём план", "en": "Awaiting plan"},
    "plans.state.returned": {"ru": "Вернули", "en": "Returned"},
    "plans.state.on_review": {"ru": "На приёмке", "en": "Under review"},
    "plans.state.accepted": {"ru": "Принят", "en": "Accepted"},
    "plans.overdue": {"ru": "Просрочен", "en": "Overdue"},
    "plans.origin.auto": {
        "ru": "запрошен сам: в проверке D2 или D3",
        "en": "requested automatically: the inspection has D2 or D3",
    },
    "plans.origin.manual": {"ru": "запрошен вручную", "en": "requested manually"},
    "plans.version": {"ru": "Версия {n}", "en": "Version {n}"},
    "plans.uploaded_meta": {
        "ru": "{by}, {at}, {kb} КБ",
        "en": "{by}, {at}, {kb} KB",
    },
    "plans.verdict.accepted": {"ru": "Принят", "en": "Accepted"},
    "plans.verdict.returned": {"ru": "Вернули", "en": "Returned"},
    "plans.no_versions": {"ru": "Файла плана ещё нет.", "en": "No plan file yet."},
    "plans.versions.title": {"ru": "Версии плана", "en": "Plan versions"},
    "plans.history.title": {"ru": "История", "en": "History"},
    "plans.event.requested": {"ru": "Запрошен план", "en": "Plan requested"},
    "plans.event.due_changed": {"ru": "Изменён срок", "en": "Due date changed"},
    "plans.event.uploaded": {"ru": "Загружена версия", "en": "Version uploaded"},
    "plans.event.accepted": {"ru": "План принят", "en": "Plan accepted"},
    "plans.event.returned": {"ru": "План возвращён", "en": "Plan returned"},
    # --- исходы действий --------------------------------------------------
    "plans.failed": {"ru": "Не получилось: {reason}", "en": "Not done: {reason}"},
    "plans.accepted": {"ru": "План принят.", "en": "Plan accepted."},
    "plans.returned": {
        "ru": "План возвращён партнёру с комментарием.",
        "en": "Plan returned to the partner with a comment.",
    },
    "plans.due_set": {"ru": "Срок изменён.", "en": "Due date changed."},
    "plans.bad_date": {"ru": "Дата не разобрана.", "en": "The date could not be read."},
    "plans.too_big": {
        "ru": "Файл больше {mb} МБ — такой не принимается.",
        "en": "The file is larger than {mb} MB and cannot be accepted.",
    },
    "plans.no_file": {"ru": "Файл не выбран.", "en": "No file chosen."},
    "plans.storage_down": {
        "ru": "Хранилище файлов сейчас не принимает файл. Попробуйте позже.",
        "en": "File storage is not accepting files right now. Please try again later.",
    },
    "plans.uploaded": {
        "ru": "Версия {version} загружена и ушла на приёмку.",
        "en": "Version {version} uploaded and sent for review.",
    },
    # --- раздел партнёра ---------------------------------------------------
    "plans.kicker": {"ru": "Ответы на проверки", "en": "Responses to inspections"},
    "plans.title": {"ru": "Запросы экшн-плана", "en": "Action plan requests"},
    "plans.hint": {
        "ru": "Загрузите план файлом любого формата, до {mb} МБ. После возврата — новую версию.",
        "en": "Upload the plan as a file of any format, up to {mb} MB. After a return, upload a new version.",  # noqa: E501
    },
    "plans.returned_note": {
        "ru": "План вернули. Комментарий УК:",
        "en": "The plan was returned. Comment from the management company:",
    },
    "plans.upload": {"ru": "Загрузить план", "en": "Upload plan"},
    "plans.empty": {
        "ru": "Запросов экшн-плана нет.",
        "en": "There are no action plan requests.",
    },
    # --- раздел УК ---------------------------------------------------------
    "actions.kicker": {"ru": "Экшн-планы", "en": "Action plans"},
    "actions.all_countries": {"ru": "Все страны", "en": "All countries"},
    "actions.queue.review": {"ru": "Ждут приёмки · {n}", "en": "Awaiting review · {n}"},
    "actions.queue.overdue": {"ru": "Просрочены · {n}", "en": "Overdue · {n}"},
    "actions.country": {"ru": "Страна", "en": "Country"},
    "actions.list.title": {"ru": "Запросы экшн-плана", "en": "Action plan requests"},
    "actions.list.hint": {"ru": "по сроку ответа", "en": "by due date"},
    "actions.list.empty": {"ru": "Запросов нет.", "en": "No requests."},
    "actions.col.country": {"ru": "Страна", "en": "Country"},
    "actions.col.inspection": {"ru": "Проверка", "en": "Inspection"},
    "actions.col.due": {"ru": "Срок", "en": "Due"},
    "actions.col.state": {"ru": "Состояние", "en": "Status"},
    "actions.request.kicker": {"ru": "Запрос экшн-плана", "en": "Action plan request"},
    "actions.request.inspection": {"ru": "Проверка от {date}", "en": "Inspection of {date}"},
    "actions.request.due": {"ru": "срок {due}", "en": "due {due}"},
    "actions.review.title": {"ru": "Приёмка плана", "en": "Plan review"},
    "actions.review.hint": {
        "ru": "Решение — по последней версии.",
        "en": "The decision applies to the latest version.",
    },
    "actions.review.accept": {"ru": "Принять план", "en": "Accept plan"},
    "actions.review.comment": {
        "ru": "Что исправить (обязательно при возврате)",
        "en": "What to fix (required to return)",
    },
    "actions.review.return": {"ru": "Вернуть с комментарием", "en": "Return with comment"},
    "actions.due.title": {"ru": "Срок ответа", "en": "Due date"},
    "actions.due.submit": {"ru": "Изменить срок", "en": "Change due date"},
    "actions.back_to_inspection": {"ru": "К проверке", "en": "Back to the inspection"},
    # --- карточка проверки и экран страны --------------------------------
    "card.plan.title": {"ru": "Экшн-план", "en": "Action plan"},
    "card.plan.request_hint": {
        "ru": "В проверке нет D2 и D3 — план можно запросить вручную.",
        "en": "The inspection has no D2 or D3 — a plan can be requested manually.",
    },
    "card.plan.due": {"ru": "Срок ответа", "en": "Due date"},
    "card.plan.request_submit": {"ru": "Запросить экшн-план", "en": "Request action plan"},
    "card.plan.open": {"ru": "Открыть запрос", "en": "Open request"},
    "card.plan.unknown": {
        "ru": "Экшн-план сейчас не прочитать.",
        "en": "The action plan cannot be read right now.",
    },
    "country.plans.title": {"ru": "Экшн-планы", "en": "Action plans"},
    "country.plans.hint": {"ru": "по проверкам страны", "en": "for the country's inspections"},
    "country.plans.empty": {"ru": "Запросов экшн-плана нет.", "en": "No action plan requests."},
    "country.plans.unknown": {
        "ru": "Экшн-планы сейчас не прочитать.",
        "en": "Action plans cannot be read right now.",
    },
    "card.plan.request_hint_needed": {
        "ru": "В проверке есть D2 или D3, а запроса нет — запросите план.",
        "en": "The inspection has D2 or D3 but no request — request a plan.",
    },
    "card.plan.no_country": {
        "ru": "Нужен экшн-план, у точки не задана страна",
        "en": "Action plan needed, the unit has no country set",
    },
    "card.plan.no_country_hint": {
        "ru": "В проверке есть D2 или D3, но запрос некому показать. Задайте точке "
        "страну в справочнике — после этого запросите план здесь.",
        "en": "The inspection has D2 or D3, but there is no one to show the request to. "
        "Set the unit's country in the directory, then request the plan here.",
    },
    "country.plans.act": {"ru": "Действовать", "en": "Act"},
    "country.plans.mine": {"ru": "Мои запросы", "en": "My requests"},
}
