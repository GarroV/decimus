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
    "mailings.cc.hint": {
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
}
