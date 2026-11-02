"""Country contact directory and read-only references (D690)."""

CONTACT_TEXTS = {
    "contacts.partner": {"ru": "Партнёр", "en": "Partner"},
    "contacts.mailing": {"ru": "Почты для рассылки", "en": "Mailing recipients"},
    "contacts.name": {"ru": "Имя или название", "en": "Name"},
    "contacts.email": {"ru": "Почта", "en": "Email"},
    "contacts.add": {"ru": "Добавить контакт", "en": "Add contact"},
    "contacts.save": {"ru": "Сохранить", "en": "Save"},
    "contacts.edit": {"ru": "Изменить", "en": "Edit"},
    "contacts.delete": {"ru": "Удалить", "en": "Delete"},
    "contacts.empty": {"ru": "Контакты не заполнены.", "en": "No contacts have been entered."},
    "contacts.partner_note": {
        "ru": "Имя и почта контакта партнёра. Это не пространство доступа.",
        "en": "The partner contact's name and email. This is separate from access spaces.",
    },
    "contacts.mailing_note": {
        "ru": (
            "Адресаты писем по проверкам: подставляются в «Кому», если в проверке адрес не указан."
        ),
        "en": "Inspection letter recipients, used in To when the inspection has no address.",
    },
    "contacts.reference_note": {
        "ru": "Только справка. Контакты изменяются в администрировании.",
        "en": "Read-only reference. Contacts are maintained in Administration.",
    },
    "contacts.imported": {
        "ru": "Партнёры из справочника пиццерий; контактные почты пока не заполнены.",
        "en": "Partners from the pizzeria directory; contact emails have not been entered yet.",
    },
    "contacts.unavailable": {
        "ru": "Не удалось загрузить контакты. Обновите страницу.",
        "en": "Could not load contacts. Refresh the page.",
    },
    "contacts.error.invalid": {
        "ru": "Проверьте имя и почту контакта.",
        "en": "Check the contact name and email.",
    },
    "contacts.error.invalid_email": {
        "ru": "Укажите один корректный адрес почты.",
        "en": "Enter one valid email address.",
    },
    "contacts.error.empty": {"ru": "Заполните имя или почту.", "en": "Enter a name or email."},
    "contacts.error.email_required": {
        "ru": "Для рассылки нужен адрес почты.",
        "en": "A mailing contact needs an email address.",
    },
    "contacts.error.duplicate": {
        "ru": "Такой контакт уже добавлен в этот список.",
        "en": "This contact is already in this list.",
    },
    "contacts.error.unavailable": {
        "ru": "Не удалось сохранить контакты. Повторите попытку.",
        "en": "Could not save contacts. Try again.",
    },
    "contacts.error.missing": {
        "ru": "Контакт уже удалён или не найден.",
        "en": "The contact was removed or could not be found.",
    },
    "contacts.error.forbidden": {
        "ru": "Нет доступа к изменению контактов.",
        "en": "You cannot change these contacts.",
    },
    "contacts.choose_country": {
        "ru": "Выберите страну, чтобы открыть её карточку.",
        "en": "Select a country to open its card.",
    },
}
