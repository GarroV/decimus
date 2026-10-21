"""Тексты открытого демо и лендинга (D524): выбор роли, плашка, посадочная страница."""

from __future__ import annotations

DEMO_TEXTS: dict[str, dict[str, str]] = {
    # ── Лендинг (D525, D545–D547): стопка листов ────────────────────────
    "landing.title": {"ru": "Хаб оценки качества", "en": "Quality assessment hub"},
    # Подпись над заголовком страниц выбора роли и приложения (`demo/pick.html`, `demo/app.html`).
    "landing.kicker": {
        "ru": "Decimus · оценка качества Dodo",
        "en": "Decimus · Dodo quality assessment",
    },
    "landing.login": {"ru": "Войти", "en": "Sign in"},
    "landing.demo": {"ru": "Открыть демо", "en": "Open the demo"},
    "landing.demo.note": {"ru": "Без регистрации и смс", "en": "No sign-up, no SMS"},
    "landing.hero.title": {
        "ru": "Хаб оценки качества сети",
        "en": "A quality assessment hub for the network",
    },
    "landing.hero.sub": {
        "ru": "Проверка, оценка, отчёт и исправления — в одном месте",
        "en": "Inspection, score, report and follow-up in one place",
    },
    "landing.hero.lead": {
        "ru": (
            "Проверяющий снимает находки на телефон и пишет к ним пару слов. Decimus ставит их "
            "на места в чек-листе и считает оценку по методике. Управляющая компания видит всю "
            "сеть, партнёр — свои точки и то, что нужно исправить."
        ),
        "en": (
            "The inspector photographs findings on a phone and adds a few words. Decimus places "
            "them on the checklist and scores them by the methodology. Head office sees the whole "
            "network; the partner sees their own locations and what needs fixing."
        ),
    },
    "landing.plan.tab": {"ru": "План", "en": "Plan"},
    "landing.plan.title": {
        "ru": "Кого, когда и в каком порядке проверять",
        "en": "Who to inspect, when, and in what order",
    },
    "landing.plan.body": {
        "ru": (
            "Календарь показывает проверки месяца с оценкой и поездки проверяющих — порядок и "
            "маршрут видны в одном месте."
        ),
        "en": (
            "The calendar shows the month's inspections with their scores and the inspectors' "
            "trips, so the order and the route are in one place."
        ),
    },
    "landing.walk.tab": {"ru": "Обход", "en": "Walk"},
    "landing.walk.title": {
        "ru": "Обход ведёт человек. Чек-лист ведёт машина.",
        "en": "The person walks. The machine runs the checklist.",
    },
    "landing.walk.body": {
        "ru": (
            "Не нужно бегать по чек-листу и искать пункты: проверяющий снимает находку и пишет "
            "пару слов, а Decimus подбирает пункт. В отчёт ничего не попадает, пока человек не "
            "подтвердил запись."
        ),
        "en": (
            "No hunting through the checklist for items: the inspector photographs a finding and "
            "writes a few words, and Decimus picks the item. Nothing reaches the report until a "
            "person confirms it."
        ),
    },
    "landing.walk.person": {"ru": "Человек", "en": "The person"},
    "landing.walk.person.1": {
        "ru": "Снимает находку и пишет пару слов",
        "en": "Photographs a finding and adds a few words",
    },
    "landing.walk.person.2": {"ru": "Подтверждает каждую запись", "en": "Confirms every record"},
    "landing.walk.person.3": {
        "ru": "Решает, что попадёт в отчёт",
        "en": "Decides what goes into the report",
    },
    "landing.walk.machine": {"ru": "Машина", "en": "The machine"},
    "landing.walk.machine.1": {"ru": "Подбирает пункт чек-листа", "en": "Picks the checklist item"},
    "landing.walk.machine.2": {
        "ru": "Напоминает, что нашли в прошлый раз",
        "en": "Recalls what was found last time",
    },
    "landing.walk.machine.3": {
        "ru": "Считает оценку по методике",
        "en": "Scores by the methodology",
    },
    "landing.report.tab": {"ru": "Отчёт", "en": "Report"},
    "landing.report.title": {
        "ru": "Отчёт готов через секунды после проверки",
        "en": "The report is ready seconds after the inspection",
    },
    "landing.report.body": {
        "ru": (
            "Оценка считается по методике, потери видны по зонам и по записям. Письмо партнёру "
            "готовится черновиком: проверяет и отправляет его человек."
        ),
        "en": (
            "The score follows the methodology, and losses show by zone and by record. The letter "
            "to the partner is a draft that a person checks and sends."
        ),
    },
    "landing.actions.tab": {"ru": "Исправление", "en": "Follow-up"},
    "landing.actions.title": {
        "ru": "План действий и разговор с партнёром — в одном месте",
        "en": "The action plan and the conversation with the partner, in one place",
    },
    "landing.actions.body": {
        "ru": (
            "Партнёр видит свои проверки и план исправлений со сроком, управляющая компания "
            "принимает план. Предписания и ответы не теряются в переписке."
        ),
        "en": (
            "The partner sees their inspections and a fix plan with a due date; head office "
            "accepts the plan. Notices and replies stay out of email threads."
        ),
    },
    "landing.net.tab": {"ru": "Сеть", "en": "Network"},
    "landing.net.title": {
        "ru": "Где качество держится, где проседает и кто должен исправить",
        "en": "Where quality holds, where it slips, and who has to fix it",
    },
    "landing.net.body": {
        "ru": (
            "Главная за любой период показывает, на каких направлениях сеть теряет проценты, "
            "какие нарушения повторяются чаще всего и как идут дела у каждой точки."
        ),
        "en": (
            "The home screen for any period shows which directions cost the network points, "
            "which violations repeat most, and how each location is doing."
        ),
    },
    "landing.net.more.1": {
        "ru": "Рейтинги стандартов и клиентского опыта по странам",
        "en": "Standards and customer-experience ratings by country",
    },
    "landing.net.more.2": {
        "ru": "Вопросы к Claude в рамках своей роли",
        "en": "Questions for Claude within your own role",
    },
    "landing.net.more.3": {"ru": "История каждой точки", "en": "The history of every location"},
    "landing.net.more.4": {
        "ru": "Язык интерфейса, проверки и отчёта — три отдельные настройки",
        "en": "Interface, inspection and report languages as three separate settings",
    },
    "landing.cta.title": {
        "ru": "Посмотрите сами за пять минут",
        "en": "See it for yourself in five minutes",
    },
    "landing.cta.body": {
        "ru": (
            "Пароль не нужен: выберите роль и пройдите проверку, отчёт и план действий. Данные "
            "выдуманные и раз в час возвращаются к исходным."
        ),
        "en": (
            "No password: pick a role and walk through an inspection, the report and the action "
            "plan. The data is made up and resets every hour."
        ),
    },
    "landing.cta.login": {"ru": "Уже есть учётка? Войти", "en": "Already have an account? Sign in"},
    "landing.alt.walk": {
        "ru": (
            "Экран обхода в приложении проверяющего: зона «Кухонная линия» в работе, найденное в "
            "прошлый раз и запись с фото"
        ),
        "en": (
            "The walk screen in the inspector app: the Kitchen line zone in progress, what was "
            "found last time and a record with a photo"
        ),
    },
    "landing.alt.match": {
        "ru": (
            "Запись в приложении проверяющего: к словам «на роликах конвейера снова лёгкий "
            "нагар» подобран пункт чек-листа, остаётся подтвердить"
        ),
        "en": (
            "A record in the inspector app: the checklist item is matched to the inspector's "
            "words, and only the confirmation is left"
        ),
    },
    "landing.alt.plan": {
        "ru": "Календарь июля: проверки по дням с буквой оценки",
        "en": "July calendar: inspections by day with their score letters",
    },
    "landing.alt.report": {
        "ru": (
            "Карточка проверки: оценка 79 процентов, буква D, расшифровка вычетов, потери по "
            "зонам и записи"
        ),
        "en": (
            "Inspection card: a 79 percent score, letter D, the deductions breakdown, loss by "
            "zone and records"
        ),
    },
    "landing.alt.actions": {
        "ru": "Планы действий партнёра: список пиццерий с оценкой, сроком и состоянием плана",
        "en": "A partner's action plans: a list of pizzerias with grade, due date and plan status",
    },
    "landing.alt.network": {
        "ru": (
            "Главная управляющей компании: топ нарушений, потери сети по направлениям и таблица "
            "пиццерий"
        ),
        "en": (
            "Head office home: top violations, network losses by direction and the pizzerias table"
        ),
    },
    "landing.alt.pizzerias": {
        "ru": (
            "Экран «Страны»: страны слева, справа выбранная пиццерия с последней проверкой и "
            "историей"
        ),
        "en": (
            "The Countries screen: countries on the left, the selected pizzeria with its latest "
            "inspection and history"
        ),
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
        "ru": "В демо это выключено: учётки здесь общие на всех посетителей, а Google, "
        "Telegram и Claude к демо не подключены. В настоящем продукте действие работает.",
        "en": "This is switched off in the demo: the accounts here are shared by every visitor, "
        "and Google, Telegram and Claude are not connected to it. In the real product it works.",
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
