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
    "walk.start.drop": {"ru": "Завершить без сдачи", "en": "End without handing over"},
    "walk.start.drop_title": {
        "ru": "Завершить текущую проверку без сдачи?",
        "en": "End the current inspection without handing it over?",
    },
    "walk.start.drop_note": {
        "ru": "Записи и кадры несданной проверки пропадут. Сданные отчёты останутся.",
        "en": "Findings and photos of the unsent inspection are lost. Handed-over reports stay.",
    },
    "walk.start.drop_yes": {"ru": "Да, завершить", "en": "Yes, end it"},
    "walk.start.dropped": {
        "ru": "Проверка завершена без сдачи. Можно начинать новую.",
        "en": "Inspection ended without handing over. You can start a new one.",
    },
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
    "walk.app.finish_mode": {"ru": "Завершение проверки", "en": "Finishing an inspection"},
    "walk.app.finish_mode.summary": {"ru": "Сначала сводка", "en": "Summary first"},
    "walk.app.finish_mode.report": {"ru": "Сразу отчёт", "en": "Report right away"},
    "walk.app.finish_mode.hint": {
        "ru": "«Завершить» пришлёт в чат сводку — отчёт после неё, или сразу отчёт.",
        "en": "“Finish” sends a summary to the chat first, or builds the report right away.",
    },
    "walk.app.translate_mode": {
        "ru": "Перевод комментариев на язык отчёта",
        "en": "Translating comments into the report language",
    },
    "walk.app.translate_mode.button": {"ru": "По кнопке", "en": "On button"},
    "walk.app.translate_mode.auto": {"ru": "Автоматически", "en": "Automatically"},
    "walk.app.translate_mode.hint": {
        "ru": (
            "Автоматически — комментарии переведутся при сборке отчёта, если язык отчёта "
            "не совпал с языком чек-листа. По кнопке — переводите сами под полем "
            "или в вычитке на сайте."
        ),
        "en": (
            "Automatically: comments are translated when the report is built, if the report "
            "language differs from the checklist language. On button: translate them yourself "
            "under the field or during proofreading on the site."
        ),
    },
    "walk.app.help": {"ru": "Справка", "en": "Help"},
    "walk.app.help.text": {
        "ru": (
            "Обход идёт зона за зоной. «+ Нарушение» — кадр и пара слов, пункт найдёт "
            "система; проверьте и сохраните. «Осмотрено →» засчитывает зону.\n\n"
            "«Сведения» в шапке обхода — вопросы для отчёта; заполненное здесь бот в "
            "конце не спросит.\n\n"
            "Начать и завершить проверку можно здесь или в чате (/start, /finish). "
            "«Завершить» в приложении работает в режиме из настроек: сначала сводка в "
            "чат или сразу отчёт; отчёту нужны заполненные «Сведения». Записанное в "
            "одном месте видно в другом."
        ),
        "en": (
            "The walk goes zone by zone. “+ Violation” — a photo and a few words, the "
            "system finds the item; check it and save. “Checked →” counts the zone.\n\n"
            "“Details” in the walk header are the report questions; whatever is filled "
            "in here the bot will not ask at the end.\n\n"
            "Start and finish an inspection here or in the chat (/start, /finish). "
            "“Finish” in the app follows the mode in Settings: a summary in the chat "
            "first, or the report right away; the report needs the “Details” filled in. "
            "What is recorded in one place shows in the other."
        ),
    },
    "walk.app.web_settings": {"ru": "Все настройки на сайте", "en": "All settings on the website"},
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
    "walk.app.claude.expires": {
        "ru": "Токен действует до {date}. Потом получите новую команду здесь же.",
        "en": "The token is valid until {date}. After that, get a new command here.",
    },
    "walk.app.err.unbound_self": {
        "ru": (
            "Токен Claude выпускается на учётку decimus: привяжите бота к своей учётке "
            "в настройках на сайте — или выпустите токен прямо там."
        ),
        "en": (
            "The Claude token is issued to a decimus account: link the bot to your "
            "account in the settings on the website — or issue the token right there."
        ),
    },
    "walk.app.claude.restart": {
        "ru": "После команды полностью перезапустите Claude (Cmd+Q).",
        "en": "After the command, fully restart Claude (Cmd+Q).",
    },
    # ── отказы ───────────────────────────────────────────────────────────
    # Выпуск токена — только по свежему открытию мини-аппа (F-032).
    "walk.app.err.stale": {
        "ru": "Мини-апп открыт давно. Закройте его и откройте снова, затем повторите.",
        "en": "The mini-app was opened a while ago. Close it, open it again and retry.",
    },
    # Учётка жива, но её роли проверки закрыты (контроль, D420, F-024).
    "walk.err.role": {
        "ru": (
            "Ваша роль в decimus не проводит проверок, поэтому мини-апп обхода вам "
            "закрыт. Рейтинги и подключение Claude — в админке на сайте."
        ),
        "en": (
            "Your decimus role does not run inspections, so the walk mini-app is closed "
            "to you. Ratings and connecting Claude are in the web admin."
        ),
    },
    "walk.app.err.lang": {"ru": "Такого языка нет.", "en": "No such language."},
    "walk.app.err.finish_mode": {"ru": "Такого режима нет.", "en": "No such mode."},
    "walk.app.err.translate_mode": {"ru": "Такого режима нет.", "en": "No such mode."},
    "walk.app.err.unavailable": {
        "ru": "Сейчас не получилось — повторите позже.",
        "en": "That did not work right now — try again later.",
    },
}
