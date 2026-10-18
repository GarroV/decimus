"""Тексты открытого демо и лендинга (D524): выбор роли, плашка, посадочная страница."""

from __future__ import annotations

DEMO_TEXTS: dict[str, dict[str, str]] = {
    # ── Лендинг ─────────────────────────────────────────────────────────
    "landing.title": {"ru": "Выездные проверки пиццерий", "en": "Field inspections for pizzerias"},
    "landing.kicker": {"ru": "Decimus · Dodo", "en": "Decimus · Dodo"},
    "landing.lead": {
        "ru": "Аудитор проходит пиццерию с телефоном: говорит и фотографирует, а Decimus "
        "раскладывает замечания по чек-листу, считает оценку и собирает отчёт партнёру. "
        "Управляющая компания и партнёры видят сеть целиком: проверки, рейтинги, планы "
        "действий и предписания.",
        "en": "An auditor walks the pizzeria with a phone: speaks and takes photos, and "
        "Decimus files the findings against the checklist, calculates the score and builds "
        "the partner's report. Head office and partners see the whole network: inspections, "
        "ratings, action plans and prescriptions.",
    },
    "landing.login": {"ru": "Войти", "en": "Sign in"},
    "landing.demo": {"ru": "Открыть демо", "en": "Open the demo"},
    "landing.demo.note": {
        "ru": "Без регистрации, на выдуманных данных",
        "en": "No sign-up, made-up data",
    },
    "landing.f1.title": {"ru": "Проверка голосом и фото", "en": "Voice and photo inspection"},
    "landing.f1.body": {
        "ru": "Аудитор говорит, что видит, — бот находит пункт чек-листа, зону и класс "
        "нарушения. Ничего не попадает в отчёт без подтверждения человека.",
        "en": "The auditor says what they see, and the bot finds the checklist item, zone and "
        "level. Nothing reaches the report until a person confirms it.",
    },
    "landing.f2.title": {"ru": "Оценка считается сама", "en": "The score calculates itself"},
    "landing.f2.body": {
        "ru": "Проценты, буква и разбивка по зонам — по методике, без ручных таблиц. "
        "Повтор прошлого замечания стоит дороже.",
        "en": "Percentage, grade and zone breakdown follow the methodology, no manual "
        "spreadsheets. A repeated finding costs more.",
    },
    "landing.f3.title": {"ru": "Сеть на одном экране", "en": "The network on one screen"},
    "landing.f3.body": {
        "ru": "Страны, пиццерии, динамика оценок и рейтинги — для управляющей компании "
        "и для каждого партнёра в своих границах.",
        "en": "Countries, pizzerias, score trends and ratings — for head office and for "
        "each partner within their own scope.",
    },
    "landing.f4.title": {"ru": "От замечания до исправления", "en": "From finding to fix"},
    "landing.f4.body": {
        "ru": "Серьёзные нарушения сами становятся планом действий, партнёр отвечает "
        "фото и комментарием, УК принимает.",
        "en": "Serious findings become an action plan on their own, the partner answers "
        "with a photo and a comment, head office signs off.",
    },
    # ── Выбор роли ──────────────────────────────────────────────────────
    "demo.title": {"ru": "Демо Decimus", "en": "Decimus demo"},
    "demo.lead": {
        "ru": "Выберите, кем войти. Данные выдуманные и раз в час возвращаются к исходному "
        "виду — можно нажимать что угодно.",
        "en": "Choose who to sign in as. The data is made up and resets every hour — feel "
        "free to click anything.",
    },
    "demo.enter": {"ru": "Войти", "en": "Enter"},
    "demo.role.admin": {"ru": "Администратор УК", "en": "Head office admin"},
    "demo.role.admin.what": {
        "ru": "Вся сеть, приёмка проверок, методика, люди и пространства партнёров.",
        "en": "The whole network, inspection sign-off, methodology, people and partner spaces.",
    },
    "demo.role.developer": {"ru": "Бизнес-девелопер", "en": "Business developer"},
    "demo.role.developer.what": {
        "ru": "Проводит и принимает проверки, пишет письма, ведёт планы и предписания.",
        "en": "Runs and signs off inspections, writes letters, handles plans and prescriptions.",
    },
    "demo.role.partner": {"ru": "Администратор партнёра", "en": "Partner admin"},
    "demo.role.partner.what": {
        "ru": "Свои страны и пиццерии, ответы на планы действий и предписания.",
        "en": "Own countries and pizzerias, answers to action plans and prescriptions.",
    },
    "demo.role.viewer": {"ru": "Наблюдатель", "en": "Viewer"},
    "demo.role.viewer.what": {
        "ru": "Вся сеть только на чтение: главная, проверки, календарь, рейтинги.",
        "en": "The whole network, read-only: home, inspections, calendar, ratings.",
    },
    "demo.app": {"ru": "Приложение аудитора", "en": "Auditor app"},
    "demo.app.what": {
        "ru": "Как выглядит проверка на телефоне — без Telegram.",
        "en": "What an inspection looks like on the phone — no Telegram needed.",
    },
    "demo.app.open": {"ru": "Открыть приложение", "en": "Open the app"},
    "demo.app.lead": {
        "ru": "Это экран аудитора на точке: зоны пиццерии, замечания с фото, что было в прошлый "
        "раз. Добавьте замечание, снимите кадр, пройдите по зонам — так проверку ведут в Telegram.",
        "en": "This is the auditor's screen on site: the pizzeria's zones, findings with photos, "
        "what was found last time. Add a finding, attach a photo, walk the zones — this is how "
        "an inspection runs in Telegram.",
    },
    "demo.app.back": {"ru": "← К выбору роли", "en": "← Back to roles"},
    "demo.not_ready": {
        "ru": "Демо как раз обновляется. Попробуйте через минуту.",
        "en": "The demo is being refreshed right now. Try again in a minute.",
    },
    # ── Плашка на каждой странице ──────────────────────────────────────
    "demo.banner": {
        "ru": "Демо: выдуманные данные, раз в час возвращаются к исходному виду",
        "en": "Demo: made-up data, resets every hour",
    },
    "demo.banner.switch": {"ru": "Сменить роль", "en": "Switch role"},
}
