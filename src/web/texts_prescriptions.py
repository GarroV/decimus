"""Тексты предписаний (волна 3): раздел УК, раздел партнёра, блок экрана страны.

Отдельным модулем, как `texts_plans.py`: `texts.py` уже длиннее предела файла.
Сливаются в общий каталог (`texts.TEXTS`) со сверкой пересечений ключей.
"""

from __future__ import annotations

PRESCRIPTION_TEXTS: dict[str, dict[str, str]] = {
    # --- вкладки раздела УК -----------------------------------------------
    "actions.tab.plans": {"ru": "Экшн-планы", "en": "Action plans"},
    "actions.tab.prescriptions": {"ru": "Предписания", "en": "Compliance notices"},
    # --- состояние --------------------------------------------------------
    "rx.state.draft": {"ru": "Черновик", "en": "Draft"},
    "rx.state.active": {"ru": "Действует", "en": "In force"},
    "rx.state.overdue": {"ru": "Просрочено", "en": "Overdue"},
    "rx.state.closed": {"ru": "Закрыто", "en": "Closed"},
    "rx.due": {"ru": "срок {due}", "en": "due {due}"},
    "rx.whole_country": {"ru": "вся страна", "en": "whole country"},
    "rx.issued_meta": {"ru": "отправлено {at}, {by}", "en": "sent {at} by {by}"},
    "rx.closed_meta": {"ru": "закрыто {at}, {by}", "en": "closed {at} by {by}"},
    "rx.base_unknown": {
        "ru": "проверка отклонена или недоступна",
        "en": "inspection retracted or unavailable",
    },
    # --- список УК --------------------------------------------------------
    "rx.list.title": {"ru": "Предписания", "en": "Compliance notices"},
    "rx.list.hint": {"ru": "по сроку", "en": "by due date"},
    "rx.list.empty": {"ru": "Предписаний нет.", "en": "No compliance notices."},
    "rx.closed_empty": {"ru": "Закрытых предписаний нет.", "en": "No closed notices."},
    "rx.show_open": {"ru": "Открытые", "en": "Open"},
    "rx.show_closed": {"ru": "Закрытые", "en": "Closed"},
    "rx.queue.overdue": {"ru": "Просрочены · {n}", "en": "Overdue · {n}"},
    "rx.queue.replied": {"ru": "Ответил партнёр · {n}", "en": "Partner replied · {n}"},
    "rx.queue.drafts": {"ru": "Черновики · {n}", "en": "Drafts · {n}"},
    "rx.new": {"ru": "Новое предписание", "en": "New notice"},
    "rx.col.subject": {"ru": "Тема", "en": "Subject"},
    "rx.col.country": {"ru": "Страна", "en": "Country"},
    "rx.col.units": {"ru": "Пиццерии", "en": "Pizzerias"},
    "rx.col.due": {"ru": "Срок", "en": "Due"},
    "rx.col.state": {"ru": "Состояние", "en": "Status"},
    "rx.truncated": {
        "ru": "Показаны первые {n} — остальные в список не уместились.",
        "en": "Showing the first {n}; the rest did not fit into the list.",
    },
    # --- форма ------------------------------------------------------------
    "rx.form.kicker": {"ru": "Предписание партнёру", "en": "Compliance notice to the partner"},
    "rx.form.title_new": {"ru": "Новое предписание", "en": "New compliance notice"},
    "rx.form.title_edit": {"ru": "Черновик предписания", "en": "Notice draft"},
    "rx.form.pick_country": {
        "ru": "Выберите страну — предписание адресовано её партнёру.",
        "en": "Choose the country: the notice goes to its partner.",
    },
    "rx.form.country": {"ru": "Страна", "en": "Country"},
    "rx.form.units": {"ru": "Пиццерии", "en": "Pizzerias"},
    "rx.form.units_hint": {
        "ru": "Ничего не отмечено — предписание на всю страну.",
        "en": "Nothing ticked means the whole country.",
    },
    "rx.form.bases": {"ru": "Проверки-основания", "en": "Inspections it is based on"},
    "rx.form.bases_hint": {
        "ru": "Последние принятые проверки УК в стране. Можно не отмечать.",
        "en": "Latest accepted inspections in the country. Optional.",
    },
    "rx.form.no_bases": {
        "ru": "Принятых проверок УК в стране нет.",
        "en": "There are no accepted inspections in this country.",
    },
    "rx.form.due": {"ru": "Срок устранения", "en": "Deadline"},
    "rx.form.recipients": {"ru": "Кому", "en": "To"},
    "rx.form.recipients_hint": {
        "ru": "Адреса через запятую. Система запомнит их для страны и подставит в следующий раз.",
        "en": "Addresses separated by commas. They are remembered for the country next time.",
    },
    "rx.form.subject": {"ru": "Тема письма", "en": "Email subject"},
    "rx.form.subject_default": {
        "ru": "Предписание · {country}",
        "en": "Compliance notice · {country}",
    },
    "rx.form.body": {"ru": "Текст письма", "en": "Email text"},
    "rx.form.body_hint": {
        "ru": "Вставьте текст целиком. После отправки он не правится.",
        "en": "Paste the full text. It cannot be edited after sending.",
    },
    "rx.form.save": {"ru": "Сохранить черновик", "en": "Save draft"},
    "rx.form.save_send": {"ru": "Сохранить и положить в Gmail", "en": "Save and put in Gmail"},
    "rx.form.cancel": {"ru": "Отмена", "en": "Cancel"},
    # --- карточка УК ------------------------------------------------------
    "rx.card.kicker": {"ru": "Предписание", "en": "Compliance notice"},
    "rx.card.letter": {"ru": "Письмо", "en": "Letter"},
    "rx.card.to": {"ru": "Кому: {to}", "en": "To: {to}"},
    "rx.card.no_recipients": {"ru": "адресаты не вписаны", "en": "no recipients yet"},
    "rx.card.units": {"ru": "Пиццерии", "en": "Pizzerias"},
    "rx.card.bases": {"ru": "Основания", "en": "Based on"},
    "rx.card.no_bases": {"ru": "Без проверок-оснований.", "en": "No inspections attached."},
    "rx.card.replies": {"ru": "Ответы партнёра", "en": "Partner replies"},
    "rx.card.no_replies": {"ru": "Ответов пока нет.", "en": "No replies yet."},
    "rx.card.history": {"ru": "История", "en": "History"},
    "rx.card.send_title": {"ru": "Отправка", "en": "Sending"},
    "rx.card.send_hint": {
        "ru": "Письмо ляжет черновиком в вашу почту Gmail — отправите его вы сами. С этого "
        "момента предписание действует, партнёр видит его у себя, текст больше не правится.",
        "en": "The letter goes to your Gmail drafts and you send it yourself. From then on the "
        "notice is in force, the partner sees it, and the text can no longer be edited.",
    },
    "rx.card.send": {"ru": "Положить в Gmail", "en": "Put in Gmail"},
    "rx.card.edit": {"ru": "Изменить черновик", "en": "Edit draft"},
    "rx.card.close_title": {"ru": "Закрыть предписание", "en": "Close the notice"},
    "rx.card.close_hint": {
        "ru": "Требование выполнено или снято. Исправить отправленное нельзя — закройте его "
        "и составьте новое.",
        "en": "The requirement is met or withdrawn. A sent notice cannot be edited: close it "
        "and write a new one.",
    },
    "rx.card.close_comment": {"ru": "Комментарий (обязательно)", "en": "Comment (required)"},
    "rx.card.close": {"ru": "Закрыть", "en": "Close"},
    "rx.card.closed_note": {"ru": "Закрыто: «{comment}»", "en": "Closed: “{comment}”"},
    # --- исходы ------------------------------------------------------------
    "rx.failed": {"ru": "Не получилось: {reason}", "en": "Not done: {reason}"},
    "rx.saved": {"ru": "Черновик сохранён.", "en": "Draft saved."},
    "rx.closed": {"ru": "Предписание закрыто.", "en": "The notice is closed."},
    "rx.bad_date": {"ru": "Срок не разобран.", "en": "The deadline could not be read."},
    "rx.gmail.ok": {
        "ru": "Письмо лежит в черновиках вашей почты — проверьте и отправьте. "
        "Предписание действует.",
        "en": "The letter is in your Gmail drafts: check and send it. The notice is now in force.",
    },
    "rx.gmail.failed": {
        "ru": "Черновик в почту не лёг — предписание осталось черновиком. Попробуйте ещё раз.",
        "en": "The draft did not reach your mailbox, so the notice is still a draft. Try again.",
    },
    "rx.gmail.denied": {
        "ru": "Доступ к почте не выдан — предписание осталось черновиком.",
        "en": "Mail access was not granted, so the notice is still a draft.",
    },
    "rx.gmail.unavailable": {
        "ru": "На этом стенде почта Google не настроена — положить письмо в черновики нельзя.",
        "en": "Google mail is not configured on this stand, so the letter cannot be drafted.",
    },
    "rx.gmail.lost": {
        "ru": "Черновик лёг в вашу почту, но предписание не отмечено отправленным. Удалите "
        "этот черновик из почты, не отправляя, и попробуйте ещё раз.",
        "en": "The draft reached your mailbox but the notice was not marked as sent. Delete "
        "that draft without sending it and try again.",
    },
    # --- раздел партнёра ----------------------------------------------------
    "rx.partner.kicker": {"ru": "От управляющей компании", "en": "From the management company"},
    "rx.partner.title": {"ru": "Предписания", "en": "Compliance notices"},
    "rx.partner.hint": {
        "ru": "Что требуют устранить и до какого числа. Ответьте комментарием и, "
        "если нужно, файлом.",
        "en": "What must be fixed and by when. Reply with a comment and, if needed, a file.",
    },
    "rx.partner.empty": {"ru": "Предписаний нет.", "en": "There are no compliance notices."},
    "rx.reply.title": {"ru": "Ответить", "en": "Reply"},
    "rx.reply.comment": {"ru": "Что сделано", "en": "What has been done"},
    "rx.reply.file": {
        "ru": "Файл (по желанию, до {mb} МБ)",
        "en": "File (optional, up to {mb} MB)",
    },
    "rx.reply.submit": {"ru": "Отправить ответ", "en": "Send reply"},
    "rx.reply.done": {
        "ru": "Ответ сохранён — УК его видит.",
        "en": "Reply saved: the management company can see it.",
    },
    "rx.reply.closed": {
        "ru": "Предписание закрыто — ответить на него уже нельзя.",
        "en": "The notice is closed and can no longer be replied to.",
    },
    "rx.reply.too_big": {
        "ru": "Файл больше {mb} МБ — такой не принимается.",
        "en": "The file is larger than {mb} MB and cannot be accepted.",
    },
    "rx.reply.storage_down": {
        "ru": "Хранилище файлов сейчас не принимает файл. Попробуйте позже.",
        "en": "File storage is not accepting files right now. Please try again later.",
    },
    "rx.reply.meta": {"ru": "{by}, {at}", "en": "{by}, {at}"},
    # --- история ----------------------------------------------------------
    "rx.event.created": {"ru": "Составлен черновик", "en": "Draft created"},
    "rx.event.edited": {"ru": "Черновик изменён", "en": "Draft edited"},
    "rx.event.issued": {"ru": "Положено в Gmail, действует", "en": "Put in Gmail, in force"},
    "rx.event.replied": {"ru": "Ответ партнёра", "en": "Partner reply"},
    "rx.event.closed": {"ru": "Закрыто", "en": "Closed"},
    # --- экран страны -----------------------------------------------------
    "country.rx.title": {"ru": "Предписания", "en": "Compliance notices"},
    "country.rx.hint": {
        "ru": "отправленные партнёру страны",
        "en": "sent to the country's partner",
    },
    "country.rx.empty": {"ru": "Предписаний не было.", "en": "No notices have been sent."},
    "country.rx.unknown": {
        "ru": "Предписания сейчас не прочитать.",
        "en": "Compliance notices cannot be read right now.",
    },
    "country.rx.act": {"ru": "Действовать", "en": "Act"},
    "country.rx.mine": {"ru": "Мои предписания", "en": "My notices"},
}
