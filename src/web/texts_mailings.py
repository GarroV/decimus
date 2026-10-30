"""Тексты вкладки «Письма и уведомления» раздела «Администрирование» (D608, #1130).

Сливаются в общий каталог (`texts.TEXTS`). Подстановок с почтами нет: адреса показываются
как есть, а не через текст.
"""

from __future__ import annotations

MAILINGS_TEXTS: dict[str, dict[str, str]] = {
    "mailings.sub": {
        "ru": (
            "Кому из сотрудников УК уходит копия письма и каким текстом письмо пишется. "
            "Выберите вид рассылки. Адреса из списка подставляются в «Копию» черновика, "
            "который вы сами кладёте в свою почту и сами отправляете; здесь ничего не "
            "отправляется."
        ),
        "en": (
            "Which HQ staff are copied on a letter and what the letter says. Pick a kind of "
            "letter. The addresses in the list are filled into the Cc of the draft that you "
            "put into your own mailbox and send yourself; nothing is sent from here."
        ),
    },
    "mailings.count": {"ru": "Видов рассылки: {count}", "en": "Kinds of letters: {count}"},
    "mailings.partial_failed": {
        "ru": "Часть списков не прочиталась: числа адресов показаны прочерком.",
        "en": "Some lists could not be read: address counts are shown as a dash.",
    },
    "mailings.kind.inspection": {"ru": "Письма по проверкам", "en": "Inspection letters"},
    "mailings.kind.prescription": {"ru": "Предписания", "en": "Prescriptions"},
    "mailings.kind.plan": {"ru": "Экшн-планы", "en": "Action plans"},
    "mailings.kind.inspection.sub": {
        "ru": "Письмо партнёру по итогам проверки УК.",
        "en": "The letter to the partner after an HQ inspection.",
    },
    "mailings.kind.prescription.sub": {
        "ru": "Письмо партнёру с предписанием.",
        "en": "The letter to the partner with a prescription.",
    },
    "mailings.kind.plan.sub": {
        "ru": "Письмо партнёру с запросом плана действий.",
        "en": "The letter to the partner requesting an action plan.",
    },
    "mailings.cc.count": {"ru": "В копии: {count}", "en": "In Cc: {count}"},
    "mailings.cc.none": {"ru": "В копии никого", "en": "Nobody in Cc"},
    "mailings.cc.title": {"ru": "Копия", "en": "Cc"},
    "mailings.cc.hint.inspection": {
        "ru": (
            "Почты сотрудников УК. Подставляются в «Копию» черновика письма по проверке УК, "
            "когда вы кладёте его в почту; письмо отправляете вы сами. Письма по проверкам "
            "партнёров их же пространства копию УК не получают."
        ),
        "en": (
            "HQ staff emails. They are filled into the Cc of an HQ inspection letter draft "
            "when you put it into your mailbox; you send the letter yourself. Letters on "
            "partners' own-space inspections do not get the HQ copy."
        ),
    },
    "mailings.cc.hint.prescription": {
        "ru": (
            "Почты сотрудников УК. Подставляются в «Копию» черновика письма предписания, "
            "когда ОСБ кладёт его в почту; письмо отправляет она сама. Шаблон документа "
            "предписания и сопроводительное письмо появятся здесь после сборки предписания "
            "(#1128)."
        ),
        "en": (
            "HQ staff emails. They are filled into the Cc of the prescription letter draft "
            "when the OSB puts it into the mailbox; the OSB sends the letter. The prescription "
            "document template and the cover letter will appear here once prescription "
            "assembly is built (#1128)."
        ),
    },
    "mailings.cc.hint.plan": {
        "ru": (
            "Почты сотрудников УК для «Копии» письма о запросе плана действий. Сейчас запрос "
            "плана идёт уведомлением внутри сервиса, письма партнёру о нём нет, поэтому "
            "список пока только хранится: он подставится в черновик, когда такое письмо "
            "появится. Ничего не отправляется."
        ),
        "en": (
            "HQ staff emails for the Cc of an action plan request letter. Today a plan request "
            "goes as an in-app notification and there is no letter to the partner, so the list "
            "is only stored for now: it will be filled into the draft once such a letter "
            "exists. Nothing is sent."
        ),
    },
    "mailings.cc.empty": {
        "ru": "Список пуст: в «Копию» черновика ничего не подставляется.",
        "en": "The list is empty: nothing is filled into the draft's Cc.",
    },
    "mailings.cc.unreadable": {
        "ru": "Список не прочитался. Попробуйте обновить страницу.",
        "en": "The list could not be read. Try reloading the page.",
    },
    "mailings.cc.remove": {"ru": "Убрать", "en": "Remove"},
    "mailings.cc.add.label": {"ru": "Почта сотрудника", "en": "Staff email"},
    "mailings.cc.add": {"ru": "Добавить в копию", "en": "Add to Cc"},
    "mailings.saved.ok": {"ru": "Сохранено.", "en": "Saved."},
    "mailings.saved.exists": {
        "ru": "Этот адрес уже в списке.",
        "en": "This address is already in the list.",
    },
    "mailings.saved.invalid": {
        "ru": "Адрес не принят: впишите одну почту целиком, например name@dodobrands.io.",
        "en": "Address not accepted: enter one complete email, for example name@dodobrands.io.",
    },
    "mailings.saved.failed": {
        "ru": "Не вышло: база не ответила. Ничего не изменено.",
        "en": "Failed: the database did not answer. Nothing was changed.",
    },
    # ── Шаблон письма по проверкам (D550, D608, #977, #1130, этап 1б) ──
    "mailings.tpl.title": {"ru": "Шаблон письма партнёру", "en": "Partner letter template"},
    "mailings.tpl.hint": {
        "ru": (
            "Текст письма по итогам проверки: свободный текст и блоки в фигурных скобках, "
            "например {{grade}}. Блоки заполняет движок, оценку шаблон не считает. Пока шаблон "
            "не сохранён, письмо собирается по встроенному тексту. Два шаблона на выбор "
            "(сильные стороны до нарушений или обе части в конце) остаются: блоки {{good_block}} "
            "и {{end_block}} кладут обратную связь аудитора по выбранному. Шаблон один на УК; "
            "письма партнёров их же пространства идут по встроенному тексту."
        ),
        "en": (
            "The text of the inspection letter: free text and blocks in curly braces, for "
            "example {{grade}}. The engine fills the blocks; the template does not calculate the "
            "grade. Until a template is saved the letter is built from the built-in text. The "
            "two templates to choose from (strengths before the violations, or both parts at "
            "the end) stay: the {{good_block}} and {{end_block}} blocks put the auditor's feedback "
            "in the place of the chosen one. One template for HQ; letters on partners' own "
            "inspections use the built-in text."
        ),
    },
    "mailings.tpl.unreadable": {
        "ru": "Шаблоны не прочитались. Попробуйте обновить страницу.",
        "en": "The templates could not be read. Try reloading the page.",
    },
    "mailings.tpl.slot.plan": {
        "ru": "Письмо с планом действий",
        "en": "Letter with an action plan",
    },
    "mailings.tpl.slot.clean": {
        "ru": "Письмо с информацией и рекомендациями",
        "en": "Letter with information and recommendations",
    },
    "mailings.tpl.slot.empty": {"ru": "Письмо без нарушений", "en": "Letter without violations"},
    "mailings.tpl.slot.plan.sub": {
        "ru": "Есть D1, D2 или D3: письмо просит план действий независимо от оценки.",
        "en": (
            "There are D1, D2 or D3 violations: the letter asks for an action plan "
            "regardless of grade."
        ),
    },
    "mailings.tpl.slot.clean.sub": {
        "ru": "Только информация и рекомендации (D0/R): письмо не просит план действий.",
        "en": (
            "Information and recommendations only (D0/R): "
            "the letter does not ask for an action plan."
        ),
    },
    "mailings.tpl.slot.empty.sub": {
        "ru": "В проверке нет ни одной записи.",
        "en": "The inspection has no records at all.",
    },
    "mailings.tpl.state.builtin": {"ru": "встроенный", "en": "built-in"},
    "mailings.tpl.state.version": {
        "ru": "версия {n} · {who} · {at}",
        "en": "version {n} · {who} · {at}",
    },
    "mailings.tpl.editing_builtin": {
        "ru": "Сейчас действует встроенный текст. Сохранение создаст версию 1 для этого слота.",
        "en": "The built-in text is in effect now. Saving creates version 1 for this slot.",
    },
    "mailings.tpl.builtin_failed": {
        "ru": "Встроенный текст движка не получен, поле пусто. Письма собираются как обычно.",
        "en": (
            "The built-in engine text could not be fetched, so the "
            "field is empty. Letters are built as usual."
        ),
    },
    "mailings.tpl.body": {"ru": "Текст письма", "en": "Letter text"},
    "mailings.tpl.save": {"ru": "Сохранить новой версией", "en": "Save as a new version"},
    "mailings.tpl.reset": {"ru": "Вернуть встроенный текст", "en": "Return to the built-in text"},
    "mailings.tpl.fields": {"ru": "Блоки", "en": "Blocks"},
    "mailings.tpl.fields.hint": {
        "ru": (
            "Неизвестный блок при сохранении отклоняется. Одиночную "
            "скобку пишут двойной: {{{{ или }}}}."
        ),
        "en": (
            "An unknown block is rejected on save. A single brace is written doubled: {{{{ or }}}}."
        ),
    },
    "mailings.tpl.history": {"ru": "История версий", "en": "Version history"},
    "mailings.tpl.history.none": {"ru": "Версий ещё нет.", "en": "No versions yet."},
    "mailings.tpl.history.unreadable": {
        "ru": "История не прочиталась.",
        "en": "The history could not be read.",
    },
    "mailings.tpl.history.row": {
        "ru": "Версия {n} · {who} · {at}",
        "en": "Version {n} · {who} · {at}",
    },
    "mailings.tpl.err.empty": {
        "ru": "Шаблон не сохранён: текст пуст.",
        "en": "Not saved: the text is empty.",
    },
    "mailings.tpl.err.long": {
        "ru": "Шаблон не сохранён: текст длиннее 6000 знаков.",
        "en": "Not saved: the text is longer than 6000 characters.",
    },
    "mailings.tpl.err.control": {
        "ru": "Шаблон не сохранён: в тексте недопустимые управляющие знаки.",
        "en": "Not saved: the text has invalid control characters.",
    },
    "mailings.tpl.err.markup": {
        "ru": (
            "Не сохранено: разметка блоков нарушена. Одиночную скобку пишут двойной: {{{{ или }}}}."
        ),
        "en": (
            "Not saved: the block markup is broken. A single "
            "brace is written doubled: {{{{ or }}}}."
        ),
    },
    "mailings.tpl.err.unknown": {
        "ru": "Шаблон не сохранён: неизвестный блок {arg}. Допустимые блоки перечислены ниже.",
        "en": "Not saved: unknown block {arg}. The allowed blocks are listed below.",
    },
    "mailings.tpl.err.format": {
        "ru": "Шаблон не сохранён: у блока {arg} не бывает формата.",
        "en": "Not saved: block {arg} takes no format.",
    },
    "mailings.saved.tpl_ok": {
        "ru": "Шаблон сохранён новой версией.",
        "en": "The template is saved as a new version.",
    },
    "mailings.saved.tpl_reset": {
        "ru": "Возвращён встроенный текст (записана новая версия).",
        "en": "The built-in text is back (a new version was recorded).",
    },
    "mailings.field.unit": {"ru": "название пиццерии", "en": "pizzeria name"},
    "mailings.field.date": {"ru": "дата проверки", "en": "inspection date"},
    "mailings.field.city": {
        "ru": "город с запятой впереди (пусто, если города нет)",
        "en": "city with a leading comma (empty if none)",
    },
    "mailings.field.type": {"ru": "вид проверки", "en": "inspection type"},
    "mailings.field.grade": {"ru": "оценка, буква", "en": "grade letter"},
    "mailings.field.pct": {"ru": "итоговый процент", "en": "overall percentage"},
    "mailings.field.grade_note": {"ru": "пояснение к оценке", "en": "note on the grade"},
    "mailings.field.summary_lines": {"ru": "сводка по зонам", "en": "summary by zone"},
    "mailings.field.critical_block": {
        "ru": "критичное (D3) и зоны роста по выбранному шаблону",
        "en": "critical (D3) items and growth areas for the chosen template",
    },
    "mailings.field.good_block": {
        "ru": "сильные стороны аудитора (шаблон 1; в шаблоне 2 пусто)",
        "en": "the auditor's strengths (template 1; empty in template 2)",
    },
    "mailings.field.end_block": {
        "ru": "обратная связь аудитора в конце (шаблон 2; в шаблоне 1 пусто)",
        "en": "the auditor's feedback at the end (template 2; empty in template 1)",
    },
    "mailings.field.plan_due": {"ru": "срок плана действий", "en": "action plan deadline"},
}
