"""Тексты экшн-планов (волна 2) и раздела «Действия» (D526): вкладка, панель, блоки, карточки.

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
        "ru": "запрошен автоматически: в проверке D2 или D3",
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
    # Общий для всех экранов, принимающих файл (#1137): чинит не человек, а администратор.
    "files.storage_unset": {
        "ru": "Хранилище файлов на этом сервере не настроено — файл не принят. "
        "Сообщите администратору.",
        "en": "File storage is not set up on this server — the file was not accepted. "
        "Please tell the administrator.",
    },
    "plans.storage_down": {
        "ru": "Хранилище файлов сейчас не принимает файл. Попробуйте позже.",
        "en": "File storage is not accepting files right now. Please try again later.",
    },
    "plans.uploaded": {
        "ru": "Версия {version} загружена и ушла на приёмку.",
        "en": "Version {version} uploaded and sent for review.",
    },
    # --- загрузка файла партнёром ----------------------------------------
    "plans.hint": {
        "ru": "Загрузите план файлом любого формата, до {mb} МБ. После возврата — новую версию.",
        "en": "Upload the plan as a file of any format, up to {mb} MB. After a return, upload a new version.",  # noqa: E501
    },
    "plans.returned_note": {
        "ru": "План вернули. Комментарий УК:",
        "en": "The plan was returned. Comment from the management company:",
    },
    "plans.upload_title": {"ru": "Файл плана", "en": "Plan file"},
    # Шаблон плана и объяснение запроса (#976, ступень 1).
    "plans.ask.title": {"ru": "Что ждём", "en": "What we expect"},
    "plans.ask.text": {
        "ru": (
            "План исправления по нарушениям проверки — до {due}: что делаете, "
            "кто отвечает и к какому сроку по каждому пункту. Скачайте шаблон, "
            "заполните и загрузите ниже. Дальше УК примет план или вернёт с комментарием."
        ),
        "en": (
            "A corrective plan for the inspection's violations by {due}: what you "
            "will do, who is responsible and by when, for each item. Download the "
            "template, fill it in and upload it below. Head office then accepts the "
            "plan or returns it with a comment."
        ),
    },
    "plans.ask.text_hq": {
        "ru": (
            "Партнёр присылает план исправления по нарушениям проверки до {due}. "
            "Шаблон ему доступен в этой же панели; формат загрузки — любой."
        ),
        "en": (
            "The partner sends a corrective plan for the inspection's violations "
            "by {due}. The template is available to them in this panel; any file "
            "format is accepted."
        ),
    },
    "plans.tpl.download": {"ru": "Скачать шаблон плана", "en": "Download plan template"},
    "plans.tpl.failed": {
        "ru": "Шаблон не собрался: проверка не прочиталась. Обновите страницу позже.",
        "en": "The template could not be built: the inspection did not load. Try again later.",
    },
    "plans.tpl.sheet": {"ru": "План исправления", "en": "Corrective plan"},
    "plans.tpl.title": {"ru": "План исправления нарушений", "en": "Corrective action plan"},
    "plans.tpl.unit": {"ru": "Пиццерия", "en": "Pizzeria"},
    "plans.tpl.date": {"ru": "Дата проверки", "en": "Inspection date"},
    "plans.tpl.grade": {"ru": "Итог проверки", "en": "Inspection result"},
    "plans.tpl.plan_due": {"ru": "Прислать план до", "en": "Send the plan by"},
    "plans.tpl.hint": {
        "ru": (
            "Заполните жёлтые колонки по каждому нарушению. Сроки устранения по пунктам "
            "указаны в отчёте проверки (PDF)."
        ),
        "en": (
            "Fill in the yellow columns for every violation. Fix-by dates for each item "
            "are in the inspection report (PDF)."
        ),
    },
    "plans.tpl.col.n": {"ru": "№", "en": "#"},
    "plans.tpl.col.level": {"ru": "Класс", "en": "Class"},
    "plans.tpl.col.zone": {"ru": "Зона", "en": "Zone"},
    "plans.tpl.col.code": {"ru": "Пункт", "en": "Item"},
    "plans.tpl.col.finding": {"ru": "Нарушение", "en": "Violation"},
    "plans.tpl.col.action": {"ru": "Что делаем", "en": "Action"},
    "plans.tpl.col.owner": {"ru": "Ответственный", "en": "Responsible"},
    "plans.tpl.col.due": {"ru": "Срок", "en": "Due"},
    "plans.tpl.col.done": {"ru": "Отметка об исправлении", "en": "Done (date, evidence)"},
    "plans.upload_button": {"ru": "Загрузить файл плана", "en": "Upload plan file"},
    "plans.file_label": {"ru": "Файл плана", "en": "Plan file"},
    "actions.drop.title": {
        "ru": "Перетащите файл сюда или нажмите, чтобы выбрать",
        "en": "Drop a file here or click to choose",
    },
    "actions.drop.none": {"ru": "Файл не выбран", "en": "No file chosen"},
    # --- экран «Действия» --------------------------------------------------
    "actions.count": {"ru": "в списке: {n}", "en": "in the list: {n}"},
    "actions.drawer.plan": {"ru": "Экшн-план", "en": "Action plan"},
    "actions.drawer.rx": {"ru": "Предписание", "en": "Compliance notice"},
    "actions.panel.facts": {"ru": "Сведения", "en": "Details"},
    "actions.panel.origin": {"ru": "Запрос", "en": "Request"},
    "actions.panel.sent": {"ru": "Отправка", "en": "Sending"},
    "actions.panel.missing.title": {"ru": "Запись не найдена", "en": "Not found"},
    "actions.panel.missing.text": {
        "ru": "Её нет или она вне вашего охвата.",
        "en": "It does not exist or is outside your scope.",
    },
    "actions.panel.failed.title": {"ru": "Не удалось открыть", "en": "Could not open"},
    "actions.panel.failed.text": {
        "ru": "База не ответила. Список остался на месте — попробуйте ещё раз.",
        "en": "The database did not respond. The list is still there; please try again.",
    },
    "actions.all_countries": {"ru": "Все страны", "en": "All countries"},
    "actions.country.apply": {"ru": "Показать", "en": "Show"},
    "actions.rail.overdue": {"ru": "просрочено {n}", "en": "overdue {n}"},
    "actions.block.empty": {"ru": "Пусто.", "en": "Nothing here."},
    "actions.block.collapse": {"ru": "Свернуть", "en": "Collapse"},
    "plans.block.on_review": {"ru": "Ждут приёмки", "en": "Awaiting review"},
    "plans.block.returned": {"ru": "Возвращены на доработку", "en": "Returned for rework"},
    "plans.block.requested": {"ru": "Запрошены", "en": "Requested"},
    "plans.block.accepted": {"ru": "Принятые", "en": "Accepted"},
    "plans.rail.on_review": {"ru": "ждут приёмки {n}", "en": "awaiting review {n}"},
    "plans.rail.waiting": {"ru": "ждут партнёра {n}", "en": "awaiting partner {n}"},
    "actions.country": {"ru": "Страна", "en": "Country"},
    "actions.list.empty": {"ru": "Запросов нет.", "en": "No requests."},
    "actions.col.unit": {"ru": "Пиццерия", "en": "Pizzeria"},
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
    "card.plan.request_submit": {"ru": "Запросить экшн-план", "en": "Request action plan"},
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
        "ru": "В проверке есть D2 или D3, но партнёр не увидит запрос: у точки не задана "
        "страна. Задайте точке страну в справочнике — после этого запросите план здесь.",
        "en": "The inspection has D2 or D3, but no partner will see the request: the unit "
        "has no country. Set the unit's country in the directory, then request the plan here.",
    },
    # --- открытые и принятые -----------------------------------------------
    "plans.truncated": {
        "ru": "Показаны первые {n} — остальные в список не уместились.",
        "en": "Showing the first {n}; the rest did not fit into the list.",
    },
    "country.plans.act": {"ru": "Действовать", "en": "Act"},
    "country.plans.mine": {"ru": "Мои запросы", "en": "My requests"},
}
