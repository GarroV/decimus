"""Тексты открытого демо и лендинга (D524): выбор роли, плашка, посадочная страница."""

from __future__ import annotations

DEMO_TEXTS: dict[str, dict[str, str]] = {
    # ── Лендинг (D525) ──────────────────────────────────────────────────
    "landing.title": {"ru": "Выездные проверки пиццерий", "en": "Field inspections for pizzerias"},
    "landing.kicker": {
        "ru": "Decimus · выездные проверки Dodo",
        "en": "Decimus · Dodo field audits",
    },
    "landing.hero.a": {"ru": "Обход пиццерии — голосом.", "en": "Walk the pizzeria — by voice."},
    "landing.hero.em": {
        "ru": "Оценка, отчёт и письмо партнёру — сами.",
        "en": "Score, report and partner letter — done for you.",
    },
    "landing.lead": {
        "ru": "Аудитор идёт по зонам с телефоном, говорит и фотографирует. Decimus "
        "раскладывает замечания по чек-листу, считает оценку по методике и собирает отчёт. "
        "Управляющая компания видит всю сеть, партнёр — свои пиццерии и что исправить.",
        "en": "The auditor walks the zones with a phone, speaking and taking photos. Decimus "
        "files the findings against the checklist, scores them by the methodology and builds "
        "the report. Head office sees the whole network, the partner sees their pizzerias "
        "and what to fix.",
    },
    "landing.login": {"ru": "Войти", "en": "Sign in"},
    "landing.demo": {"ru": "Открыть демо", "en": "Open the demo"},
    "landing.demo.note": {
        "ru": "Без входа и регистрации, на выдуманных данных",
        "en": "No sign-in, no sign-up, made-up data",
    },
    "landing.how.link": {"ru": "Как это работает", "en": "How it works"},
    "landing.proof.1": {
        "ru": "в Telegram — ставить нечего",
        "en": "in Telegram — nothing to install",
    },
    "landing.proof.2": {
        "ru": "оценка по методике, не руками",
        "en": "scored by the method, not by hand",
    },
    "landing.proof.3": {"ru": "русский и английский", "en": "Russian and English"},
    # Макет на главном экране — выдуманная проверка, как в демо.
    "landing.mock.zone": {"ru": "Кухня · линия", "en": "Kitchen line"},
    "landing.mock.progress": {"ru": "4 из 6 зон", "en": "4 of 6 zones"},
    "landing.mock.said": {
        "ru": "«На роликах конвейера печи остатки теста»",
        "en": "“Dough residue on the oven conveyor rollers”",
    },
    "landing.mock.item": {"ru": "Печь, конвейер, вытяжка", "en": "Oven, conveyor, hood"},
    "landing.mock.confirm": {"ru": "Подтвердить", "en": "Confirm"},
    "landing.mock.report": {"ru": "Отчёт готов", "en": "Report ready"},
    "landing.mock.zones": {"ru": "Зал · Кухня · Склад", "en": "Dining · Kitchen · Storage"},
    "landing.mock.plan": {"ru": "План действий: 7 дней", "en": "Action plan: 7 days"},
    "landing.steps.kicker": {"ru": "Путь проверки", "en": "The inspection path"},
    "landing.steps.title": {
        "ru": "От маршрута до исправления — в одной системе",
        "en": "From route to fix — in one system",
    },
    "landing.steps.lead": {
        "ru": "Без таблиц, пересылки фото и ручного подсчёта процентов.",
        "en": "No spreadsheets, no forwarding photos, no counting percentages by hand.",
    },
    "landing.s1.title": {"ru": "План", "en": "Plan"},
    "landing.s1.body": {
        "ru": "Маршрут и календарь поездок: кого, когда и в каком порядке проверять.",
        "en": "Route and trip calendar: who to inspect, when and in what order.",
    },
    "landing.s2.title": {"ru": "Обход", "en": "Walk"},
    "landing.s2.body": {
        "ru": "Зона за зоной в Telegram: голосом, фото и списком «что было в прошлый раз».",
        "en": "Zone by zone in Telegram: voice, photos and a list of what was found last time.",
    },
    "landing.s3.title": {"ru": "Подтверждение", "en": "Confirm"},
    "landing.s3.body": {
        "ru": "Модель предлагает пункт и класс нарушения, аудитор фиксирует. Без него в отчёт "
        "не попадает ничего.",
        "en": "The model suggests the item and level, the auditor confirms. Nothing reaches "
        "the report without them.",
    },
    "landing.s4.title": {"ru": "Отчёт", "en": "Report"},
    "landing.s4.body": {
        "ru": "Проценты, буква и разбивка по зонам, PDF и письмо партнёру. Повтор прошлого "
        "замечания стоит дороже.",
        "en": "Percentage, grade and zone breakdown, a PDF and a letter to the partner. "
        "A repeated finding costs more.",
    },
    "landing.s5.title": {"ru": "Исправление", "en": "Fix"},
    "landing.s5.body": {
        "ru": "Серьёзные нарушения сами становятся планом действий со сроком; партнёр "
        "отвечает фото, УК принимает.",
        "en": "Serious findings become an action plan with a deadline; the partner answers "
        "with a photo, head office signs off.",
    },
    "landing.who.kicker": {"ru": "Кому что даёт", "en": "Who gets what"},
    "landing.who.title": {
        "ru": "Одна проверка — три точки зрения",
        "en": "One inspection, three views",
    },
    "landing.who.auditor": {"ru": "Аудитору", "en": "Auditors"},
    "landing.who.auditor.1": {
        "ru": "Проверка в телефоне, без бумаги и ноутбука",
        "en": "The inspection on a phone, no paper or laptop",
    },
    "landing.who.auditor.2": {
        "ru": "Голос превращается в замечание с пунктом и зоной",
        "en": "Voice turns into a finding with item and zone",
    },
    "landing.who.auditor.3": {
        "ru": "Отчёт и письмо собираются сами",
        "en": "The report and letter build themselves",
    },
    "landing.who.hq": {"ru": "Управляющей компании", "en": "Head office"},
    "landing.who.hq.1": {
        "ru": "Вся сеть на одном экране: страны, пиццерии, динамика",
        "en": "The whole network on one screen: countries, pizzerias, trends",
    },
    "landing.who.hq.2": {
        "ru": "Рейтинги стандартов и клиентского опыта вместо таблиц",
        "en": "Standards and customer-experience ratings instead of spreadsheets",
    },
    "landing.who.hq.3": {
        "ru": "Методика и чек-лист правятся без программиста",
        "en": "Methodology and checklist edited without a developer",
    },
    "landing.who.partner": {"ru": "Партнёру", "en": "Partners"},
    "landing.who.partner.1": {
        "ru": "Свои пиццерии и их история проверок",
        "en": "Their pizzerias and inspection history",
    },
    "landing.who.partner.2": {
        "ru": "Что исправить и к какому сроку",
        "en": "What to fix and by when",
    },
    "landing.who.partner.3": {
        "ru": "Ответ фотографией прямо в системе",
        "en": "Answer with a photo right in the system",
    },
    "landing.who.try": {"ru": "Посмотреть в демо", "en": "See it in the demo"},
    "landing.more.kicker": {"ru": "Ещё внутри", "en": "Also inside"},
    "landing.more.ratings": {"ru": "Рейтинги по странам", "en": "Ratings by country"},
    "landing.more.ratings.body": {
        "ru": "Стандарты и клиентский опыт по каждой стране — вместо Google-таблиц.",
        "en": "Standards and customer experience for every country — instead of Google Sheets.",
    },
    "landing.more.claude": {"ru": "Спросить Claude", "en": "Ask Claude"},
    "landing.more.claude.body": {
        "ru": "Подключите Claude и спрашивайте про сеть словами: в рамках своей роли.",
        "en": "Connect Claude and ask about the network in plain words, within your role.",
    },
    "landing.more.history": {"ru": "История пиццерии", "en": "Pizzeria history"},
    "landing.more.history.body": {
        "ru": "Все прошлые проверки и повторы — перед глазами аудитора на месте.",
        "en": "Every past inspection and repeat — in front of the auditor on site.",
    },
    "landing.more.lang": {"ru": "Язык — параметр", "en": "Language is a setting"},
    "landing.more.lang.body": {
        "ru": "Интерфейс, речь аудитора и отчёт — каждый на своём языке.",
        "en": "Interface, the auditor's speech and the report — each in its own language.",
    },
    "landing.mock.repeat": {"ru": "Повтор", "en": "Repeat"},
    "landing.mock.item2": {
        "ru": "Мытьё рук: мыло и полотенца",
        "en": "Handwashing: soap and towels",
    },
    "landing.mock.photos": {"ru": "Фото: 3", "en": "Photos: 3"},
    "landing.net.kicker": {"ru": "Сеть на одном экране", "en": "The network on one screen"},
    "landing.net.title": {
        "ru": "Где всё хорошо, где проседает и кто должен исправить",
        "en": "Where it's fine, where it slips and who has to fix it",
    },
    "landing.net.lead": {
        "ru": "Страны, пиццерии и динамика оценок — для управляющей компании целиком, для "
        "партнёра в границах его пиццерий. Серьёзные нарушения сами превращаются в план "
        "действий со сроком, и видно, кто его задерживает.",
        "en": "Countries, pizzerias and score trends — the whole network for head office, "
        "their own pizzerias for each partner. Serious findings turn into an action plan "
        "with a deadline on their own, and you can see who is holding it up.",
    },
    "landing.net.p1": {
        "ru": "Тренд по каждой пиццерии, а не одна цифра",
        "en": "A trend for every pizzeria, not one number",
    },
    "landing.net.p2": {
        "ru": "Повторы прошлых замечаний видны сразу",
        "en": "Repeats of past findings stand out at once",
    },
    "landing.net.p3": {
        "ru": "Планы действий со сроками и ответами партнёра",
        "en": "Action plans with deadlines and the partner's answers",
    },
    "landing.net.head.unit": {"ru": "Пиццерия", "en": "Pizzeria"},
    "landing.net.head.score": {"ru": "Оценка", "en": "Score"},
    "landing.net.head.trend": {"ru": "Динамика", "en": "Trend"},
    "landing.net.plan": {"ru": "Ждут плана партнёра", "en": "Awaiting the partner's plan"},
    "landing.cta.chip1": {"ru": "Без регистрации", "en": "No sign-up"},
    "landing.cta.chip2": {"ru": "Пять минут", "en": "Five minutes"},
    "landing.cta.chip3": {"ru": "Сброс раз в час", "en": "Resets hourly"},
    "landing.cta.login": {"ru": "Уже есть учётка? Войти", "en": "Already have an account? Sign in"},
    "landing.cta.title": {
        "ru": "Посмотрите сами за пять минут",
        "en": "See it for yourself in five minutes",
    },
    "landing.cta.body": {
        "ru": "Демо открывается без пароля: выберите роль и пройдите проверку, отчёт и план "
        "действий. Данные выдуманные и раз в час возвращаются к исходному виду.",
        "en": "The demo opens without a password: pick a role and walk through an inspection, "
        "the report and the action plan. The data is made up and resets every hour.",
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
    "demo.locked": {
        "ru": "В демо это выключено: учётки здесь общие на всех посетителей. "
        "В настоящем продукте действие работает.",
        "en": "This is switched off in the demo: the accounts here are shared by every visitor. "
        "In the real product it works.",
    },
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
