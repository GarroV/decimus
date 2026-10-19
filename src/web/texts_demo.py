"""Тексты открытого демо и лендинга (D524): выбор роли, плашка, посадочная страница."""

from __future__ import annotations

DEMO_TEXTS: dict[str, dict[str, str]] = {
    # ── Лендинг (D525) ──────────────────────────────────────────────────
    "landing.title": {"ru": "Хаб оценки качества", "en": "Quality assessment hub"},
    "landing.kicker": {
        "ru": "Decimus · оценка качества Dodo",
        "en": "Decimus · Dodo quality assessment",
    },
    "landing.hero.a": {
        "ru": "Хаб оценки качества сети.",
        "en": "A quality assessment hub for the network.",
    },
    "landing.hero.em": {
        "ru": "Проверка, оценка, отчёт и исправления — в одном месте.",
        "en": "Inspection, score, report and follow-up — in one place.",
    },
    "landing.lead": {
        "ru": "Проверяющий ведёт проверку с телефона: фиксирует замечания фото и коротким комментарием. Decimus привязывает их к пунктам чек-листа, считает оценку по методике и готовит отчёт. Управляющая компания видит всю сеть, партнёр — свои точки и что нужно исправить.",
        "en": "The inspector runs the inspection from a phone, recording findings with a photo and a short comment. Decimus links them to checklist items, scores them by the methodology and prepares the report. Head office sees the whole network, the partner sees their own locations and what needs fixing.",
    },
    "landing.login": {"ru": "Войти", "en": "Sign in"},
    "landing.demo": {"ru": "Открыть демо", "en": "Open the demo"},
    "landing.demo.note": {"ru": "Без регистрации и смс", "en": "No sign-up, no SMS"},
    "landing.how.link": {"ru": "Как это работает", "en": "How it works"},
    # Макет на главном экране — выдуманная проверка, как в демо.
    "landing.mock.zone": {"ru": "Кухня", "en": "Kitchen"},
    "landing.mock.progress": {"ru": "4 из 6 зон", "en": "4 of 6 zones"},
    "landing.mock.said": {
        "ru": "На роликах конвейера печи остатки теста",
        "en": "Dough residue on the oven conveyor rollers",
    },
    "landing.mock.item": {"ru": "Печь, конвейер, вытяжка", "en": "Oven, conveyor, hood"},
    "landing.mock.report": {"ru": "Отчёт готов", "en": "Report ready"},
    "landing.mock.z1": {"ru": "Зал", "en": "Dining"},
    "landing.mock.z2": {"ru": "Кухня", "en": "Kitchen"},
    "landing.mock.z3": {"ru": "Склад", "en": "Storage"},
    "landing.mock.add": {"ru": "Нарушение", "en": "Violation"},
    "landing.mock.done": {"ru": "Осмотрено", "en": "Checked"},
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
        "ru": "Зона за зоной в Telegram: фото, короткий комментарий и что было в прошлый раз.",
        "en": "Zone by zone in Telegram: a photo, a short comment and what was found last time.",
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
        "ru": "После проверки отчёт готов за секунды — с оценкой по методике и черновиком письма партнёру.",
        "en": "The report is ready seconds after the inspection — scored by the methodology, with a draft letter to the partner.",
    },
    "landing.s5.title": {"ru": "Исправление", "en": "Fix"},
    "landing.s5.body": {
        "ru": "По серьёзным нарушениям запрашивается план действий со сроком: партнёр присылает план, УК принимает или возвращает.",
        "en": "Serious findings trigger a request for an action plan with a deadline: the partner sends the plan, head office accepts or returns it.",
    },
    "landing.who.kicker": {"ru": "Кому что даёт", "en": "Who gets what"},
    "landing.who.title": {
        "ru": "Одна проверка — три точки зрения",
        "en": "One inspection, three views",
    },
    "landing.who.auditor": {"ru": "Проверяющему", "en": "Inspectors"},
    "landing.who.auditor.1": {
        "ru": "Проверка в телефоне, без бумаги и ноутбука",
        "en": "The inspection on a phone, no paper or laptop",
    },
    "landing.who.auditor.2": {
        "ru": "Комментарий становится замечанием с пунктом и зоной",
        "en": "A comment becomes a finding with item and zone",
    },
    "landing.who.auditor.3": {
        "ru": "Отчёт и черновик письма готовы — остаётся проверить и отправить",
        "en": "The report and draft letter are ready — just review and send",
    },
    "landing.who.hq": {"ru": "Управляющей компании", "en": "Head office"},
    "landing.who.hq.1": {
        "ru": "Вся сеть на одном экране: страны, точки, динамика",
        "en": "The whole network on one screen: countries, locations, trends",
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
        "ru": "Свои точки и их история проверок",
        "en": "Their locations and inspection history",
    },
    "landing.who.partner.2": {
        "ru": "Что исправить и к какому сроку",
        "en": "What to fix and by when",
    },
    "landing.who.partner.3": {
        "ru": "План действий и ответ на предписание — прямо в системе",
        "en": "Action plan and response to a notice — right in the system",
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
    "landing.more.history": {"ru": "История точки", "en": "Location history"},
    "landing.more.history.body": {
        "ru": "Все прошлые проверки и повторы — перед глазами проверяющего на месте.",
        "en": "Every past inspection and repeat — in front of the inspector on site.",
    },
    "landing.more.lang": {"ru": "Язык — параметр", "en": "Language is a setting"},
    "landing.more.lang.body": {
        "ru": "Интерфейс, язык проверки и отчёт — каждый на своём языке.",
        "en": "Interface, inspection language and report — each in its own language.",
    },
    "landing.mock.repeat": {"ru": "Повтор", "en": "Repeat"},
    "landing.mock.item2": {
        "ru": "Мытьё рук: мыло и полотенца",
        "en": "Handwashing: soap and towels",
    },
    "landing.mock.photos": {"ru": "Фото: 3", "en": "Photos: 3"},
    "landing.net.kicker": {"ru": "Сеть на одном экране", "en": "The network on one screen"},
    "landing.net.title": {
        "ru": "Где качество держится, где проседает и кто должен исправить",
        "en": "Where quality holds, where it slips and who has to fix it",
    },
    "landing.net.lead": {
        "ru": "Страны, точки и динамика оценок — для управляющей компании целиком, для партнёра в границах его точек. По серьёзным нарушениям автоматически запрашивается план действий со сроком, и видно, кто его задерживает.",
        "en": "Countries, locations and score trends — the whole network for head office, their own locations for each partner. Serious findings automatically trigger an action plan request with a deadline, and you can see who is holding it up.",
    },
    "landing.net.p1": {
        "ru": "Тренд по каждой точке, а не одна цифра",
        "en": "A trend for every location, not one number",
    },
    "landing.net.p2": {
        "ru": "Повторы прошлых замечаний видны сразу",
        "en": "Repeats of past findings stand out at once",
    },
    "landing.net.p3": {
        "ru": "Планы действий со сроками и ответами партнёра",
        "en": "Action plans with deadlines and the partner's answers",
    },
    "landing.net.head.unit": {"ru": "Точка", "en": "Location"},
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
