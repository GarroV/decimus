"""Тексты уведомлений в приложении (#1129, D604, D614): колокольчик и фразы событий.

Отдельным модулем: `texts.py` уже длиннее предела файла. Сливаются в общий
каталог (`texts.TEXTS`) со сверкой пересечений ключей. Фраза вида — `notif.<вид>`
(`src/web/notifications.py`, `SECTION_OF_KIND`); в базе лежат вид и параметры,
текст не хранится.
"""

from __future__ import annotations

NOTIFICATION_TEXTS: dict[str, dict[str, str]] = {
    "notif.title": {"ru": "Уведомления", "en": "Notifications"},
    "notif.bell": {"ru": "Уведомления", "en": "Notifications"},
    "notif.bell_unread": {"ru": "Уведомления: есть новые", "en": "Notifications: new items"},
    "notif.new": {"ru": "Новое", "en": "New"},
    "notif.empty": {"ru": "Пока ничего нового.", "en": "Nothing new yet."},
    "notif.failed": {
        "ru": "Не удалось загрузить уведомления. Попробуйте позже.",
        "en": "Could not load notifications. Try again later.",
    },
    "notif.read_all": {"ru": "Отметить все прочитанными", "en": "Mark all as read"},
    "notif.unknown": {"ru": "Новое событие", "en": "New event"},
    # --- предписания ------------------------------------------------------
    "notif.rx_requested": {
        "ru": "{by} просит согласовать предписание «{subject}»",
        "en": "{by} asks you to approve the compliance notice “{subject}”",
    },
    "notif.rx_returned": {
        "ru": "{by} вернул предписание «{subject}» на доработку",
        "en": "{by} returned the compliance notice “{subject}” for rework",
    },
    "notif.rx_approved": {
        "ru": "{by} согласовал предписание «{subject}»",
        "en": "{by} approved the compliance notice “{subject}”",
    },
    "notif.rx_issued": {
        "ru": "Предписание «{subject}» отправлено: черновик письма лёг в почту ({by})",
        "en": "The compliance notice “{subject}” was sent: the draft is in the mailbox ({by})",
    },
}
