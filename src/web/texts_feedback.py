"""Тексты кнопки «Обратная связь» (D761 п.6) и вкладки «Обратная связь» в «Администрировании».

Сливаются в общий каталог (`texts.TEXTS`). Сообщение в Telegram (команде) тут не живёт:
оно служебное и всегда на русском, его шаблон — в `feedback_telegram.py`.
"""

from __future__ import annotations

FEEDBACK_TEXTS: dict[str, dict[str, str]] = {
    # ── Кнопка и окно ────────────────────────────────────────────────────
    "feedback.button": {"ru": "Обратная связь", "en": "Feedback"},
    "feedback.title": {"ru": "Обратная связь", "en": "Feedback"},
    "feedback.lead": {
        "ru": "Что не так или что улучшить? Страница, с которой вы пишете, приложится сама.",
        "en": "What is wrong or what could be better? The page you are on is attached "
        "automatically.",
    },
    "feedback.text.label": {"ru": "Сообщение", "en": "Message"},
    "feedback.text.placeholder": {
        "ru": "Опишите проблему или предложение",
        "en": "Describe the problem or suggestion",
    },
    "feedback.photos.label": {
        "ru": "Фото или скриншоты (до {max})",
        "en": "Photos or screenshots (up to {max})",
    },
    "feedback.photos.hint": {
        "ru": "JPEG, PNG или WebP, каждое до {mb} МБ",
        "en": "JPEG, PNG or WebP, up to {mb} MB each",
    },
    "feedback.send": {"ru": "Отправить", "en": "Send"},
    "feedback.cancel": {"ru": "Отмена", "en": "Cancel"},
    "feedback.close": {"ru": "Закрыть", "en": "Close"},
    "feedback.sending": {"ru": "Отправляем…", "en": "Sending…"},
    "feedback.sent": {
        "ru": "Спасибо, сообщение отправлено.",
        "en": "Thank you, your message has been sent.",
    },
    "feedback.demo": {
        "ru": "В демо отправка отключена: сообщение никуда не уйдёт.",
        "en": "Sending is turned off in the demo: your message would go nowhere.",
    },
    "feedback.err.network": {
        "ru": "Не удалось отправить. Проверьте соединение и повторите.",
        "en": "Could not send. Check your connection and try again.",
    },
    # ── Отказы (ключ — код отказа сервера) ───────────────────────────────
    "feedback.err.empty": {"ru": "Напишите сообщение.", "en": "Please write a message."},
    "feedback.err.too_long": {
        "ru": "Сообщение длиннее {max} знаков.",
        "en": "The message is longer than {max} characters.",
    },
    "feedback.err.too_many_photos": {
        "ru": "Не больше {max} фото.",
        "en": "No more than {max} photos.",
    },
    "feedback.err.photo_big": {
        "ru": "Фото больше {mb} МБ.",
        "en": "A photo is larger than {mb} MB.",
    },
    "feedback.err.photo_pixels": {
        "ru": "Фото слишком большое по размеру в пикселях (не больше {px} млн).",
        "en": "The photo is too large in pixels (up to {px} million).",
    },
    "feedback.err.photo_type": {
        "ru": "Принимаются только фото JPEG, PNG и WebP.",
        "en": "Only JPEG, PNG and WebP photos are accepted.",
    },
    "feedback.err.rate": {
        "ru": "Слишком много сообщений за час. Попробуйте позже.",
        "en": "Too many messages this hour. Please try again later.",
    },
    "feedback.err.failed": {
        "ru": "Сообщение не сохранилось. Повторите попытку.",
        "en": "The message was not saved. Please try again.",
    },
    # ── Вкладка администрирования ────────────────────────────────────────
    "administration.tab.feedback": {"ru": "Обратная связь", "en": "Feedback"},
    "feedback.admin.sub": {
        "ru": "Сообщения из кнопки «Обратная связь», новые сверху.",
        "en": "Messages from the Feedback button, newest first.",
    },
    "feedback.admin.none": {"ru": "Сообщений пока нет.", "en": "No messages yet."},
    "feedback.admin.unavailable": {
        "ru": "Сообщения сейчас не прочитать. Повторите позже.",
        "en": "Messages cannot be read right now. Please try again later.",
    },
    "feedback.admin.who": {
        "ru": "{login} · {role} · {space}",
        "en": "{login} · {role} · {space}",
    },
    "feedback.admin.page": {"ru": "Страница", "en": "Page"},
    "feedback.admin.lang": {"ru": "Язык: {lang}", "en": "Language: {lang}"},
    "feedback.admin.photo": {"ru": "Фото {n}", "en": "Photo {n}"},
    "feedback.admin.reviewed": {
        "ru": "Разобрано: {by}, {at}",
        "en": "Reviewed: {by}, {at}",
    },
    "feedback.admin.review": {"ru": "Отметить разобранным", "en": "Mark as reviewed"},
    "feedback.admin.unreview": {"ru": "Вернуть в работу", "en": "Reopen"},
    "feedback.admin.review.failed": {
        "ru": "Отметка не сохранилась. Повторите попытку.",
        "en": "The mark was not saved. Please try again.",
    },
    "feedback.admin.tg.sent": {"ru": "В Telegram отправлено", "en": "Sent to Telegram"},
    "feedback.admin.tg.error": {
        "ru": "В Telegram не ушло ({code})",
        "en": "Not delivered to Telegram ({code})",
    },
    "feedback.admin.chat.title": {
        "ru": "Чат Telegram для команды",
        "en": "Telegram chat for the team",
    },
    "feedback.admin.chat.note": {
        "ru": "Пока чат не задан, сообщения только сохраняются здесь, а в Telegram не уходят. "
        "Бот должен быть добавлен в этот чат.",
        "en": "While no chat is set, messages are only saved here and not sent to Telegram. "
        "The bot must be a member of the chat.",
    },
    "feedback.admin.chat.label": {"ru": "Номер чата", "en": "Chat id"},
    "feedback.admin.chat.current": {"ru": "Сейчас: {chat}", "en": "Current: {chat}"},
    "feedback.admin.chat.off": {"ru": "Сейчас: не задан", "en": "Current: not set"},
    "feedback.admin.chat.save": {"ru": "Сохранить", "en": "Save"},
    "feedback.admin.chat.disable": {"ru": "Выключить отправку", "en": "Turn sending off"},
    "feedback.admin.chat.saved": {"ru": "Чат сохранён.", "en": "Chat saved."},
    "feedback.admin.chat.disabled": {
        "ru": "Отправка в Telegram выключена.",
        "en": "Sending to Telegram is off.",
    },
    "feedback.admin.chat.bad": {
        "ru": "Номер чата — только цифры, для групп с минусом впереди.",
        "en": "The chat id is digits only, with a leading minus for groups.",
    },
    "feedback.admin.chat.failed": {
        "ru": "Чат не сохранился. Повторите попытку.",
        "en": "The chat was not saved. Please try again.",
    },
}
