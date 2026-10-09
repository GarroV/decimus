"""Тексты мини-аппа как приложения аудитора (D373): главная и настройки.

Отдельным файлом от экрана обхода: обход — один раздел приложения, а главная
и настройки общие для всех разделов, включая будущие (проверка конкурентов).
Сливаются в каталог обхода (`texts_walk.WALK_TEXTS`) и уходят экрану вместе.
"""

from __future__ import annotations

APP_TEXTS: dict[str, dict[str, str]] = {
    # ── главная ──────────────────────────────────────────────────────────
    "walk.app.home": {"ru": "Главная", "en": "Home"},
    "walk.app.audit": {"ru": "Проверка пиццерии", "en": "Pizzeria inspection"},
    "walk.app.audit.none": {
        "ru": "Проверки нет. Начните её в чате: /start.",
        "en": "No inspection yet. Start one in the chat: /start.",
    },
    "walk.app.audit.to_chat": {"ru": "Открыть чат", "en": "Open the chat"},
    "walk.app.audit.records": {"ru": "Записей: {count}", "en": "Records: {count}"},
    "walk.app.audit.continue": {"ru": "Продолжить обход", "en": "Continue the walk"},
    "walk.app.audit.sealed": {"ru": "Отчёт сдан", "en": "Report handed over"},
    "walk.app.audit.open": {"ru": "Открыть", "en": "Open"},
    # ── настройки ────────────────────────────────────────────────────────
    "walk.app.settings": {"ru": "Настройки", "en": "Settings"},
    "walk.app.lang": {"ru": "Язык", "en": "Language"},
    "walk.app.help": {"ru": "Справка", "en": "Help"},
    "walk.app.help.text": {
        "ru": (
            "Главная — что сейчас идёт и куда дальше.\n\n"
            "Обход: зона за зоной. «+ Нарушение» — снимите кадр и напишите пару слов, "
            "пункт найдёт система; проверьте и сохраните. «Осмотрено →» засчитывает "
            "зону и ведёт к следующей.\n\n"
            "«Сведения» в шапке обхода — вопросы для отчёта; что заполнено здесь, бот в "
            "конце не спросит.\n\n"
            "Чат с ботом работает как раньше: начать (/start) и завершить (/finish) "
            "проверку — там. Всё записанное в чате видно здесь, и наоборот."
        ),
        "en": (
            "Home shows what is going on and where to go next.\n\n"
            "The walk goes zone by zone. “+ Violation” — take a photo and write a few "
            "words, the system finds the item; check it and save. “Checked →” counts the "
            "zone and moves to the next one.\n\n"
            "“Details” in the walk header are the report questions; whatever is filled in "
            "here the bot will not ask at the end.\n\n"
            "The bot chat works as before: start (/start) and finish (/finish) the "
            "inspection there. Everything recorded in the chat shows here, and back."
        ),
    },
    "walk.app.version": {"ru": "Версия", "en": "Version"},
    # ── подключение Claude ───────────────────────────────────────────────
    "walk.app.claude": {"ru": "Подключить Claude", "en": "Connect Claude"},
    "walk.app.claude.text": {
        "ru": (
            "Одна команда с вашим личным токеном: выполните её в терминале на Mac, "
            "где стоит Claude. Токен показывается один раз; новая команда гасит "
            "прежнюю настройку. Никому её не пересылайте."
        ),
        "en": (
            "One command with your personal token: run it in a terminal on the Mac "
            "where Claude is installed. The token is shown once; a new command "
            "cancels the previous setup. Do not forward it to anyone."
        ),
    },
    "walk.app.claude.issue": {"ru": "Получить команду", "en": "Get the command"},
    "walk.app.claude.again": {"ru": "Получить новую", "en": "Get a new one"},
    "walk.app.claude.copy": {"ru": "Скопировать", "en": "Copy"},
    "walk.app.claude.copied": {"ru": "Скопировано", "en": "Copied"},
    "walk.app.claude.replaced": {
        "ru": "Прежний токен отозван — старая настройка больше не работает.",
        "en": "The previous token is revoked — the old setup no longer works.",
    },
    "walk.app.claude.restart": {
        "ru": "После команды полностью перезапустите Claude (Cmd+Q).",
        "en": "After the command, fully restart Claude (Cmd+Q).",
    },
    # ── круг доступа ─────────────────────────────────────────────────────
    "walk.app.access": {"ru": "Доступ к Claude", "en": "Claude access"},
    "walk.app.access.add": {"ru": "Выдать доступ", "en": "Grant access"},
    "walk.app.access.id": {"ru": "Telegram ID", "en": "Telegram ID"},
    "walk.app.access.revoke": {"ru": "Отозвать", "en": "Revoke"},
    "walk.app.access.founder": {"ru": "основатель", "en": "founder"},
    "walk.app.access.token": {"ru": "токен выпущен", "en": "token issued"},
    "walk.app.access.no_token": {"ru": "без токена", "en": "no token"},
    "walk.app.access.revoked": {"ru": "отозван", "en": "revoked"},
    "walk.app.access.empty": {"ru": "В круге никого нет.", "en": "Nobody is in the circle."},
    "walk.app.stops": {"ru": "Отказы мастера", "en": "Wizard refusals"},
    "walk.app.stops.period": {"ru": "За {days} дн.", "en": "Last {days} days"},
    "walk.app.stops.empty": {"ru": "Отказов не было.", "en": "No refusals."},
    "walk.app.stops.line": {
        "ru": "{times} раз · людей: {people}",
        "en": "{times} times · people: {people}",
    },
    # ── отказы ───────────────────────────────────────────────────────────
    "walk.app.err.id": {"ru": "Нужен Telegram ID — число.", "en": "A Telegram ID is a number."},
    "walk.app.err.not_allowed": {
        "ru": "Этого человека бот не пускает — сначала дайте ему доступ к боту.",
        "en": "The bot does not let this person in — give them bot access first.",
    },
    "walk.app.err.founder": {
        "ru": "Основателя круга отозвать нельзя.",
        "en": "The founder of the circle cannot be revoked.",
    },
    "walk.app.err.days": {"ru": "Период — от 1 до 90 дней.", "en": "The period is 1 to 90 days."},
    "walk.app.err.lang": {"ru": "Такого языка нет.", "en": "No such language."},
    "walk.app.err.not_circle": {
        "ru": "Это доступно только кругу доступа к Claude.",
        "en": "Only the Claude access circle can do this.",
    },
    "walk.app.err.unavailable": {
        "ru": "Сейчас не получилось — повторите позже.",
        "en": "That did not work right now — try again later.",
    },
}
