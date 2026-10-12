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
    "walk.app.audit.new": {"ru": "Начать проверку", "en": "Start inspection"},
    "walk.app.audit.new_other": {"ru": "Начать новую", "en": "Start a new one"},
    "walk.app.audit.records": {"ru": "Записей: {count}", "en": "Records: {count}"},
    "walk.app.audit.continue": {"ru": "Продолжить обход", "en": "Continue the walk"},
    # ── начало проверки (D392) ───────────────────────────────────────────
    "walk.start.title": {"ru": "Новая проверка", "en": "New inspection"},
    "walk.start.checklist": {"ru": "Чек-лист", "en": "Checklist"},
    "walk.start.unit": {"ru": "Пиццерия", "en": "Pizzeria"},
    "walk.start.unit_hint": {
        "ru": "Город и номер, например Belgrade-1",
        "en": "City and number, e.g. Belgrade-1",
    },
    "walk.start.kind": {"ru": "Вид проверки", "en": "Inspection type"},
    # Язык, на котором ведут проверку и пишут записи (код `speech_lang`). Слово
    # «речь» владелец отверг (D414): человек выбирает язык чек-листа.
    "walk.start.speech": {"ru": "Язык чек-листа", "en": "Checklist language"},
    "walk.start.speech_hint_label": {"ru": "Что это значит", "en": "What this means"},
    "walk.start.speech_hint": {
        "ru": "Отчёт и проверку в вебе можно смотреть на любом языке платформы.",
        "en": "The report and the inspection on the web can be viewed in any platform language.",
    },
    "walk.start.go": {"ru": "Начать проверку", "en": "Start inspection"},
    "walk.start.going": {"ru": "Начинаем…", "en": "Starting…"},
    "walk.start.running": {
        "ru": "Сейчас идёт проверка «{unit}». Новая заменит её: то, что не сдано, пропадёт.",
        "en": (
            "Inspection “{unit}” is in progress. A new one replaces it: "
            "anything not handed over is lost."
        ),
    },
    "walk.start.replace_title": {
        "ru": "Заменить текущую проверку?",
        "en": "Replace the current inspection?",
    },
    "walk.start.replace_yes": {"ru": "Да, начать новую", "en": "Yes, start a new one"},
    "walk.start.keep": {"ru": "Оставить текущую", "en": "Keep the current one"},
    "walk.start.cancel": {"ru": "Отмена", "en": "Cancel"},
    "walk.start.new_yes": {"ru": "Да, добавить", "en": "Yes, add it"},
    "walk.start.new_no": {"ru": "Нет, изменить название", "en": "No, edit the name"},
    "walk.start.err.failed": {
        "ru": (
            "Не получилось начать проверку. Повторите через минуту; "
            "если снова не выйдет, скажите администратору."
        ),
        "en": (
            "Could not start the inspection. Try again in a minute; "
            "if it fails again, tell the administrator."
        ),
    },
    "walk.start.err.checklist_gone": {
        "ru": "Этот чек-лист только что закрыли. Выберите другой.",
        "en": "That checklist was just closed. Pick another one.",
    },
    "walk.start.err.running": {
        "ru": "Идёт другая проверка — подтвердите, что её нужно заменить.",
        "en": "Another inspection is in progress — confirm that it should be replaced.",
    },
    # ── настройки ────────────────────────────────────────────────────────
    "walk.app.settings": {"ru": "Настройки", "en": "Settings"},
    "walk.app.lang": {"ru": "Язык", "en": "Language"},
    "walk.app.help": {"ru": "Справка", "en": "Help"},
    "walk.app.help.text": {
        "ru": (
            "Обход идёт зона за зоной. «+ Нарушение» — кадр и пара слов, пункт найдёт "
            "система; проверьте и сохраните. «Осмотрено →» засчитывает зону.\n\n"
            "«Сведения» в шапке обхода — вопросы для отчёта; заполненное здесь бот в "
            "конце не спросит.\n\n"
            "Начать проверку можно здесь или в чате (/start), завершить (/finish) — в "
            "чате. Записанное в одном месте видно в другом."
        ),
        "en": (
            "The walk goes zone by zone. “+ Violation” — a photo and a few words, the "
            "system finds the item; check it and save. “Checked →” counts the zone.\n\n"
            "“Details” in the walk header are the report questions; whatever is filled "
            "in here the bot will not ask at the end.\n\n"
            "Start an inspection here or in the chat (/start); finish it (/finish) in "
            "the chat. What is recorded in one place shows in the other."
        ),
    },
    "walk.app.version": {"ru": "Версия", "en": "Version"},
    # ── подключение Claude ───────────────────────────────────────────────
    "walk.app.claude": {"ru": "Подключить Claude", "en": "Connect Claude"},
    "walk.app.claude.text": {
        "ru": "Команда с вашим токеном: выполните её в терминале на Mac с Claude.",
        "en": "A command with your token: run it in a terminal on the Mac with Claude.",
    },
    "walk.app.claude.safety": {
        "ru": "Токен виден один раз, новая команда гасит прежнюю. Никому не пересылайте.",
        "en": "The token is shown once; a new command cancels the old one. Do not forward it.",
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
