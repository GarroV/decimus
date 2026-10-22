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
    "rx.state.review": {"ru": "На согласовании", "en": "In review"},
    "rx.state.approved": {"ru": "Согласовано", "en": "Approved"},
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
    "rx.form.title_by_inspection": {
        "ru": "Предписание по проверке",
        "en": "Notice based on an inspection",
    },
    "rx.form.pick_base": {
        "ru": "Отметьте проверку-основание.",
        "en": "Tick the inspection it is based on.",
    },
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
        "ru": "Последние {n} принятых проверок УК в стране — более ранних здесь нет. "
        "Можно не отмечать.",
        "en": "The latest {n} accepted inspections in the country; older ones are not listed. "
        "Optional.",
    },
    "rx.form.no_bases": {
        "ru": "Принятых проверок УК в стране нет.",
        "en": "There are no accepted inspections in this country.",
    },
    "rx.form.due": {"ru": "Срок устранения", "en": "Deadline"},
    "rx.form.recipients": {"ru": "Кому", "en": "To"},
    "rx.form.recipients_hint": {
        "ru": "Адреса через запятую. Подставлены контакты по ДКК из карточки страны; если их "
        "там нет, — адреса прошлой отправки. Система запомнит эти для страны.",
        "en": "Addresses separated by commas. Filled in from the agreement contacts in the "
        "country card; if there are none, from the last notice sent. They are remembered "
        "for the country.",
    },
    "rx.form.subject": {"ru": "Тема письма", "en": "Email subject"},
    "rx.form.subject_default": {
        "ru": "Предписание · {country}",
        "en": "Compliance notice · {country}",
    },
    "rx.form.body": {"ru": "Текст письма", "en": "Email text"},
    "rx.form.body_hint": {
        "ru": "Вставьте текст целиком. После отправки партнёру он не правится; "
        "правка согласованного снимает согласование.",
        "en": "Paste the full text. It cannot be edited once sent to the partner; "
        "editing an approved notice withdraws the approval.",
    },
    "rx.form.save": {"ru": "Сохранить черновик", "en": "Save draft"},
    "rx.form.save_request": {
        "ru": "Отправить на согласование",
        "en": "Send for approval",
    },
    "rx.form.save_approve": {"ru": "Сохранить и согласовать", "en": "Save and approve"},
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
    "rx.card.in_review": {
        "ru": "Предписание на согласовании у ОСБ. Пока оно не согласовано, партнёр его не видит.",
        "en": "The notice is waiting for OSB approval. The partner cannot see it until then.",
    },
    "rx.card.request_title": {"ru": "Согласование", "en": "Approval"},
    "rx.card.request_hint": {
        "ru": "Отправьте черновик ОСБ: она согласует его или вернёт с комментарием. "
        "Партнёру он не уйдёт, пока ОСБ не согласует.",
        "en": "Send the draft to OSB: it will approve it or return it with a comment. "
        "Nothing reaches the partner before OSB approves.",
    },
    "rx.card.request": {"ru": "Отправить на согласование", "en": "Send for approval"},
    "rx.card.approve_title": {"ru": "Согласование", "en": "Approval"},
    "rx.card.approve_hint": {
        "ru": "Согласуйте предписание или верните автору с комментарием. Партнёру оно уйдёт "
        "отдельным шагом — после согласования.",
        "en": "Approve the notice or return it to the author with a comment. It reaches the "
        "partner as a separate step, after approval.",
    },
    "rx.card.approved_hint": {
        "ru": "Согласованное предписание можно положить в почту. Текст, нарушения и адресаты "
        "после согласования заморожены: правка снимет согласование.",
        "en": "An approved notice can be put into the mailbox. Text, violations and recipients "
        "are frozen after approval: editing withdraws the approval.",
    },
    "rx.card.approve": {"ru": "Согласовать", "en": "Approve"},
    "rx.card.return": {"ru": "Вернуть автору", "en": "Return to the author"},
    "rx.card.return_comment": {
        "ru": "Комментарий автору (обязательно)",
        "en": "Comment for the author (required)",
    },
    "rx.card.returned_note": {
        "ru": "Вернули с комментарием: «{comment}»",
        "en": "Returned with a comment: “{comment}”",
    },
    "rx.card.approved": {"ru": "Согласовано", "en": "Approved"},
    "rx.approved_meta": {"ru": "{at}, {by}", "en": "{at}, {by}"},
    "rx.card.edit_drops_approval": {
        "ru": "Правка снимет согласование: после неё предписание снова на согласовании.",
        "en": "Editing withdraws the approval: the notice goes back to review afterwards.",
    },
    "rx.card.send_title": {"ru": "Отправка", "en": "Sending"},
    "rx.card.send_hint": {
        "ru": "Письмо ляжет черновиком в вашу почту — отправите его вы сами. С этого момента "
        "предписание действует, партнёр видит его, текст больше не правится.",
        "en": "The letter goes to your mailbox drafts and you send it yourself. From then on the "
        "notice is in force, the partner sees it, and the text can no longer be edited.",
    },
    "rx.card.send": {"ru": "Черновик в почту", "en": "Draft to mailbox"},
    "rx.card.edit": {"ru": "Изменить черновик", "en": "Edit draft"},
    "rx.card.edit_approved": {
        "ru": "Изменить (снимет согласование)",
        "en": "Edit (withdraws approval)",
    },
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
    "rx.requested": {
        "ru": "Отправлено на согласование ОСБ.",
        "en": "Sent to OSB for approval.",
    },
    "rx.approved": {"ru": "Предписание согласовано.", "en": "The notice is approved."},
    "rx.returned": {
        "ru": "Предписание возвращено автору.",
        "en": "The notice is returned to its author.",
    },
    "rx.need_base": {
        "ru": "Предписание без проверки заводит ОСБ: отметьте проверку-основание.",
        "en": "A notice without an inspection is created by OSB: tick an inspection to base it on.",
    },
    "rx.not_approved": {
        "ru": "в почту кладут только согласованное ОСБ предписание",
        "en": "only a notice approved by OSB can be put into the mailbox",
    },
    "rx.closed": {"ru": "Предписание закрыто.", "en": "The notice is closed."},
    "rx.bad_date": {"ru": "Срок не разобран.", "en": "The deadline could not be read."},
    "rx.gmail.ok": {
        "ru": "Письмо лежит в черновиках вашей почты — проверьте и отправьте. "
        "Предписание действует.",
        "en": "The letter is in your mailbox drafts: check and send it. "
        "The notice is now in force.",
    },
    "rx.gmail.failed": {
        "ru": "Черновик в почту не лёг — предписание осталось согласованным, но не отправленным. "
        "Попробуйте ещё раз.",
        "en": "The draft did not reach your mailbox, so the notice is still approved but unsent. "
        "Try again.",
    },
    "rx.gmail.denied": {
        "ru": "Доступ к почте не выдан — предписание осталось согласованным, но не отправленным.",
        "en": "Mail access was not granted, so the notice is still approved but unsent.",
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
    "rx.gmail.wrong_account": {
        "ru": "Доступ к почте выдал не тот аккаунт Google — предписание осталось черновиком. "
        "Черновик кладётся только в почту, которой вы входите через Google: выберите её в окне "
        "Google.",
        "en": "Mail access came from a different Google account, so the notice is still a draft. "
        "Drafts go only to the mailbox you sign in with through Google: pick it in the Google "
        "window.",
    },
    "rx.not_found.title": {"ru": "Предписание не найдено", "en": "Notice not found"},
    "rx.not_found.text": {
        "ru": "Такого предписания нет или оно вам недоступно.",
        "en": "There is no such notice, or it is not available to you.",
    },
    "rx.not_found.back": {"ru": "К предписаниям", "en": "To notices"},
    # --- ответ партнёра -----------------------------------------------------
    "rx.partner.empty": {"ru": "Предписаний нет.", "en": "There are no compliance notices."},
    "rx.reply.comment": {"ru": "Что сделано", "en": "What has been done"},
    "rx.reply.file": {
        "ru": "Файл (по желанию, до {mb} МБ)",
        "en": "File (optional, up to {mb} MB)",
    },
    "rx.reply.file_label": {"ru": "Файл ответа", "en": "Reply file"},
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
    "rx.event.edited": {"ru": "Предписание изменено", "en": "Notice edited"},
    "rx.event.edited_approval_dropped": {
        "ru": "Изменено, согласование снято",
        "en": "Edited, approval withdrawn",
    },
    "rx.event.requested": {"ru": "Отправлено на согласование", "en": "Sent for approval"},
    "rx.event.returned": {"ru": "Возвращено автору", "en": "Returned to the author"},
    "rx.event.approved": {"ru": "Согласовано ОСБ", "en": "Approved by OSB"},
    "rx.event.issued": {"ru": "Черновик в почте, действует", "en": "Draft in mailbox, in force"},
    "rx.event.replied": {"ru": "Ответ партнёра", "en": "Partner reply"},
    "rx.event.closed": {"ru": "Закрыто", "en": "Closed"},
    # --- страница «ОСБ» (D599) ---------------------------------------------
    "section.osb.title": {"ru": "ОСБ", "en": "OSB"},
    "osb.queues": {"ru": "Очереди предписаний", "en": "Notice queues"},
    "osb.queue.review": {"ru": "На согласовании · {n}", "en": "In review · {n}"},
    "osb.queue.approved": {
        "ru": "Согласовано, не отправлено · {n}",
        "en": "Approved, not sent · {n}",
    },
    "osb.queue.active": {"ru": "Действуют · {n}", "en": "In force · {n}"},
    "osb.queue.drafts": {"ru": "Черновики · {n}", "en": "Drafts · {n}"},
    "osb.queue.closed": {"ru": "Закрытые · {n}", "en": "Closed · {n}"},
    "osb.empty.review": {
        "ru": "Ничего не ждёт согласования.",
        "en": "Nothing is waiting for approval.",
    },
    "osb.empty.approved": {
        "ru": "Согласованных, но не отправленных предписаний нет.",
        "en": "No approved notices are waiting to be sent.",
    },
    "osb.empty.active": {"ru": "Действующих предписаний нет.", "en": "No notices are in force."},
    "osb.empty.drafts": {"ru": "Черновиков нет.", "en": "There are no drafts."},
    "osb.empty.closed": {"ru": "Закрытых предписаний нет.", "en": "No closed notices."},
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
