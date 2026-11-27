"""Тексты раздела «Администрирование» (D639), вкладок «Подключения» (D638) и «Ключи и API» (D650).

Сливаются в общий каталог (`texts.TEXTS`) — `t()` знает один словарь.
"""

from __future__ import annotations

from .texts_aggregators_admin import AGGREGATORS_ADMIN_TEXTS

ADMINISTRATION_TEXTS: dict[str, dict[str, str]] = {
    "plans.setting.title": {"ru": "Настройки экшн-планов", "en": "Action-plan settings"},
    "plans.setting.label": {"ru": "Электронные экшн-планы", "en": "Electronic action plans"},
    "plans.setting.on": {"ru": "Включены", "en": "Enabled"},
    "plans.setting.off": {"ru": "Выключены", "en": "Disabled"},
    "plans.setting.save": {"ru": "Сохранить", "en": "Save"},
    "plans.setting.saved": {"ru": "Настройка сохранена", "en": "Setting saved"},
    "plans.setting.failed": {
        "ru": "Настройка не сохранена. Повторите попытку.",
        "en": "The setting was not saved. Please retry.",
    },
    "plans.setting.archive": {"ru": "Сохранённые планы", "en": "Stored plans"},
    "plans.setting.open": {"ru": "Открыть работу с планами", "en": "Open action-plan workflow"},
    "plans.setting.changed": {"ru": "Изменил: {actor} · {at}", "en": "Changed by: {actor} · {at}"},
    "plans.setting.unavailable": {
        "ru": "Настройку не удалось прочитать. Экшн-планы временно недоступны.",
        "en": "The setting could not be read. Action plans are temporarily unavailable.",
    },
    "plans.setting.note": {
        "ru": (
            "Новые запросы, заполнение, согласование и подтверждение исправлений "
            "доступны по правам пользователя."
        ),
        "en": (
            "New requests, submissions, reviews and confirmation of corrections "
            "are available according to user permissions."
        ),
    },
    "plans.setting.activation_note": {
        "ru": (
            "Включение не создаёт планы по старым проверкам и не отправляет письма "
            "или сообщения в Telegram. Старые непрочитанные уведомления не появляются заново."
        ),
        "en": (
            "Enabling does not create plans for past inspections "
            "or send email or Telegram messages. "
            "Old unread notifications do not reappear."
        ),
    },
    "administration.tab.home": {"ru": "Главная", "en": "Home"},
    "home.setting.sub": {
        "ru": "Настройки сети для страницы «Главная».",
        "en": "Network-wide settings for the Home page.",
    },
    "home.setting.attention.title": {
        "ru": "Пиццерии в «Требует внимания»",
        "en": "Pizzerias in “Needs attention”",
    },
    "home.setting.attention.label": {
        "ru": "Показывать пиццерии в «Требует внимания»",
        "en": "Show pizzerias in “Needs attention”",
    },
    "home.setting.attention.note": {
        "ru": (
            "Строки с пиццериями, где в проверках периода есть критические нарушения "
            "или оценка D. Задания в той же карточке (приёмка, планы, предписания) "
            "настройка не трогает. Пока выключено, строк и подсказки к ним нет; "
            "карточки нет совсем, если нет и заданий."
        ),
        "en": (
            "Rows for pizzerias with critical findings or a D grade in the period's "
            "inspections. Tasks in the same card (review, plans, orders) are not affected. "
            "While off, there are no rows or hint for them; the card is not shown at all "
            "if there are no tasks either."
        ),
    },
    "home.setting.on": {"ru": "Включено", "en": "On"},
    "home.setting.off": {"ru": "Выключено", "en": "Off"},
    "home.setting.unavailable": {
        "ru": "Настройку не удалось прочитать. Пока считается выключенной.",
        "en": "The setting could not be read. Treated as off for now.",
    },
    "administration.tab.plans": {"ru": "Экшн-планы", "en": "Action plans"},
    "plans.paused.title": {"ru": "Экшн-планы отключены", "en": "Action plans are paused"},
    "plans.paused.note": {
        "ru": (
            "Новые запросы и уведомления не создаются. "
            "Сохранённые планы доступны здесь только для чтения."
        ),
        "en": (
            "New requests and notifications are disabled. "
            "Stored plans remain here for read-only review."
        ),
    },
    "section.administration.title": {"ru": "Администрирование", "en": "Administration"},
    "administration.tabs": {"ru": "Разделы администрирования", "en": "Administration tabs"},
    "administration.tab.people": {"ru": "Люди и доступ", "en": "People & access"},
    "administration.tab.spaces": {"ru": "Пространства партнёров", "en": "Partner spaces"},
    "administration.tab.spaces_own": {"ru": "Ваше пространство", "en": "Your space"},
    "administration.tab.countries": {"ru": "Страны", "en": "Countries"},
    "administration.tab.journal": {"ru": "Журнал", "en": "Log"},
    "administration.tab.dodois": {"ru": "Dodo IS", "en": "Dodo IS"},
    "administration.tab.usage": {"ru": "Расход модели", "en": "Model usage"},
    "administration.tab.connections": {"ru": "Подключения", "en": "Connections"},
    "administration.tab.keys": {"ru": "Ключи и API", "en": "Keys & API"},
    "administration.tab.ratings": {"ru": "Рейтинги", "en": "Ratings"},
    "administration.tab.mailings": {"ru": "Письма и уведомления", "en": "Letters & notifications"},
    "administration.sub": {
        "ru": "Все настройки сервиса в одном месте. Вкладки видны по роли.",
        "en": "All service settings in one place. Tabs depend on your role.",
    },
    # ── Состояние подключений ──
    "health.title": {"ru": "Состояние подключений", "en": "Connection status"},
    "health.sub": {
        "ru": "Ключи и службы проверяются раз в 15 минут, "
        "сборы — по их журналу после каждого прогона.",
        "en": "Keys and services are checked every 15 minutes, "
        "data collections by their log after each run.",
    },
    "health.summary.green": {"ru": "Всё работает", "en": "Everything works"},
    "health.summary.yellow": {
        "ru": "Есть предупреждения: {n}",
        "en": "Warnings: {n}",
    },
    "health.summary.red": {"ru": "Не работает: {n}", "en": "Not working: {n}"},
    "health.summary.grey": {"ru": "Проверок ещё не было", "en": "No checks yet"},
    "health.check_now": {"ru": "Проверить", "en": "Check"},
    "health.key_link": {"ru": "Ключ", "en": "Key"},
    # ── «Ключи и API» (D650): два блока ──
    "keys.out.title": {"ru": "Наши ключи к внешним сервисам", "en": "Our keys to outside services"},
    "keys.out.sub": {
        "ru": "Ими Decimus сам ходит наружу: OpenAI, Pointer, iSpring.",
        "en": "What Decimus itself uses to call out: OpenAI, Pointer, iSpring.",
    },
    "keys.api.title": {"ru": "Доступ к API Decimus", "en": "Access to the Decimus API"},
    "keys.api.sub": {
        "ru": (
            "Внешний сервис получает ключ и читает данные Decimus по API; "
            "права и страны задаются при выдаче."
        ),
        "en": (
            "An outside service gets a key and reads Decimus data through the API; "
            "rights and countries are set when the key is issued."
        ),
    },
    "keys.api.add": {"ru": "Выдать ключ API", "en": "Issue API key"},
    "keys.api.count": {"ru": "Ключей API: {count}", "en": "API keys: {count}"},
    "health.checked": {"ru": "проверено {at}", "en": "checked {at}"},
    "health.ran": {"ru": "последний прогон {at}", "en": "last run {at}"},
    "health.ok.checked": {"ru": "Проверено: {name}", "en": "Checked: {name}"},
    "health.err.unavailable": {
        "ru": "Здесь проверить нечем — проверку ведёт бот. Исход появится после его захода.",
        "en": "This can't be checked from here — the bot checks it. "
        "The result appears after its next run.",
    },
    "health.err.db": {
        "ru": "База не ответила — состояние подключений сейчас не прочитать.",
        "en": "The database didn't answer — connection status can't be read right now.",
    },
    "health.light.green": {"ru": "работает", "en": "working"},
    "health.light.yellow": {"ru": "предупреждение", "en": "warning"},
    "health.light.red": {"ru": "не работает", "en": "not working"},
    "health.light.grey": {"ru": "нет данных", "en": "no data"},
    # ── Группы ──
    "health.group.system": {
        "ru": "Системное: хранилище, бот, вход, бэкап",
        "en": "System: storage, bot, sign-in, backup",
    },
    "health.group.ratings": {"ru": "Рейтинги и оценки", "en": "Ratings and reviews"},
    "health.group.learning": {"ru": "Обучение", "en": "Training"},
    "health.group.dodo_is": {"ru": "Dodo IS по странам", "en": "Dodo IS by country"},
    # ── Данные рейтингов по странам и источникам (D704, D706) ──
    "coverage.title": {"ru": "Данные рейтингов по странам", "en": "Ratings data by country"},
    "coverage.sub": {
        "ru": "У скольких пиццерий страны есть данные источника и когда они обновлялись. "
        "Если источник пуст или заполнен меньше {min}% пиццерий, данные старше срока "
        "или нет месяца, владельцу раз в сутки приходит оповещение. Пустая клетка — "
        "источник для страны не ждём.",
        "en": "How many of a country's pizzerias have data from a source and when it was "
        "last updated. If a source is empty or covers under {min}% of pizzerias, the data "
        "is out of date or a month is missing, the owner is notified once a day. "
        "An empty cell means the source is not expected for that country.",
    },
    "coverage.err": {
        "ru": "Не удалось прочитать данные рейтингов: база не ответила.",
        "en": "Could not read the ratings data: the database did not respond.",
    },
    "coverage.none": {"ru": "Нет данных.", "en": "No data."},
    "coverage.country": {"ru": "Страна", "en": "Country"},
    "coverage.src.rs": {"ru": "Рейтинг стандартов", "en": "Standards rating"},
    "coverage.src.rko": {"ru": "Рейтинг контроля", "en": "Control rating"},
    "coverage.src.kr": {"ru": "Клиентские оценки", "en": "Customer ratings"},
    "coverage.src.maps_google": {"ru": "Google Карты", "en": "Google Maps"},
    "coverage.src.maps_yandex": {"ru": "Яндекс Карты", "en": "Yandex Maps"},
    "coverage.reason.empty": {"ru": "данных нет совсем", "en": "no data at all"},
    "coverage.reason.not_connected": {
        "ru": "не подключён вход Dodo IS",
        "en": "Dodo IS login is not connected",
    },
    "coverage.reason.stale": {"ru": "данные устарели", "en": "data is out of date"},
    "coverage.reason.missing_current": {
        "ru": "нет данных за текущий месяц",
        "en": "no data for the current month",
    },
    "coverage.reason.missing_previous": {
        "ru": "нет данных за прошлый месяц",
        "en": "no data for the previous month",
    },
    "coverage.reason.low": {
        "ru": "заполнено меньше {min}% пиццерий",
        "en": "fewer than {min}% of pizzerias filled",
    },
    # ── Подключения ──
    "health.conn.openai": {"ru": "OpenAI — распознавание", "en": "OpenAI — recognition"},
    "health.conn.telegram": {"ru": "Бот в Telegram", "en": "Telegram bot"},
    "health.conn.storage": {"ru": "Хранилище кадров", "en": "Photo storage"},
    "health.conn.google": {"ru": "Вход через Google", "en": "Google sign-in"},
    "health.conn.pointer": {"ru": "Pointer — ключ", "en": "Pointer — key"},
    "health.conn.ispring": {"ru": "iSpring — ключ", "en": "iSpring — key"},
    "health.conn.aggregators": {
        "ru": "Агрегаторы — ночной сбор оценок",
        "en": "Aggregators — nightly ratings collection",
    },
    "health.conn.maps": {
        "ru": "Pointer — ночной сбор оценок с карт",
        "en": "Pointer — nightly map ratings collection",
    },
    "health.conn.sheet": {"ru": "Таблица контроля — загрузка", "en": "Control spreadsheet — load"},
    "health.conn.learning": {"ru": "iSpring — ночная загрузка", "en": "iSpring — nightly load"},
    "health.conn.backup": {"ru": "Ночной бэкап", "en": "Nightly backup"},
    "health.conn.dodo_is": {"ru": "Dodo IS по странам", "en": "Dodo IS by country"},
    "health.conn.dodo_is_country": {"ru": "Dodo IS — {name}", "en": "Dodo IS — {name}"},
    # ── Причины ──
    "health.reason.ok": {"ru": "Ответил", "en": "Responded"},
    "health.reason.rejected": {"ru": "Ключ не принят", "en": "Key rejected"},
    "health.reason.unverified": {
        "ru": "Не удалось проверить: сеть или сбой у провайдера",
        "en": "Couldn't check: network or provider failure",
    },
    "health.reason.unreachable": {"ru": "Не отвечает", "en": "Not responding"},
    "health.reason.no_key": {"ru": "Ключ не задан", "en": "No key set"},
    "health.reason.not_configured": {"ru": "Не настроено", "en": "Not configured"},
    "health.reason.configured": {"ru": "Настроено", "en": "Configured"},
    "health.reason.never_checked": {"ru": "Ещё не проверялось", "en": "Not checked yet"},
    "health.reason.stale": {
        "ru": "Проверка давно не шла — проверьте, жив ли бот",
        "en": "No check for a while — make sure the bot is running",
    },
    "health.reason.never_ran": {"ru": "Ещё не запускался", "en": "Hasn't run yet"},
    "health.reason.failed": {"ru": "Сбой: {error}", "en": "Failed: {error}"},
    "health.reason.late": {"ru": "Опаздывает", "en": "Running late"},
    "health.reason.stopped": {"ru": "Давно не запускался", "en": "Hasn't run for a long time"},
    "health.reason.ran": {"ru": "Прошёл", "en": "Completed"},
    "health.reason.backup_host": {
        "ru": "Бэкап делает сервер, сюда его исход пока не приходит",
        "en": "The server makes the backup; its result doesn't reach this page yet",
    },
    "health.reason.dodois_none": {
        "ru": "Входов нет: выдайте ссылку коллеге страны",
        "en": "No logins yet: issue a link to a colleague in the country",
    },
    "health.reason.dodois_ok": {
        "ru": "Работает: открыто {open} из {total}",
        "en": "Working: {open} of {total} open",
    },
    "health.reason.dodois_partial": {
        "ru": "Открыто не всё: {open} из {total}",
        "en": "Not everything open: {open} of {total}",
    },
    "health.reason.dodois_expired": {
        "ru": "Вход истёк: продление отказано, нужна новая ссылка",
        "en": "Login expired: renewal was refused, a new link is needed",
    },
    "health.reason.dodois_failed": {
        "ru": "Сбой связи с Dodo IS при последней проверке",
        "en": "Connection to Dodo IS failed on the last check",
    },
    # Состояние канала оповещений владельцу (D641); исход пишет бот под кодом `alerts_channel`.
    "health.conn.alerts_channel": {"ru": "Оповещения владельцу", "en": "Owner alerts"},
    "health.reason.alerts_on": {
        "ru": "Включены: о сбое придёт сообщение в Telegram",
        "en": "On: a failure sends a Telegram message",
    },
    "health.reason.alerts_off": {
        "ru": "Оповещения выключены: не заданы адрес и ключ канала FURCA",
        "en": "Alerts are off: the FURCA channel address and key are not set",
    },
    "health.reason.alerts_demo": {
        "ru": "Оповещения выключены: это демо",
        "en": "Alerts are off: this is the demo",
    },
    # ── Вкладка «Страны» (D640) ──
    "countries.sub": {
        "ru": "Партнёр, девелопер и языки отчёта страны. Выберите страну в списке.",
        "en": "Partner, developer and report languages of a country. Pick a country in the list.",
    },
    "countries.count": {"ru": "Стран: {count}", "en": "Countries: {count}"},
    "countries.none": {"ru": "Стран в справочнике нет.", "en": "No countries in the directory."},
    "countries.open": {
        "ru": "Настроить страну: {country}",
        "en": "Configure the country: {country}",
    },
    # ── Вкладка «Рейтинги» (D654): блоки настроек и их строка состояния ──
    "ratings.admin.sub": {
        "ru": (
            "Загрузка данных, справочники и пороги рейтингов. "
            "Привязка площадок и запрос обновления — в блоке «Агрегаторы»."
        ),
        "en": (
            "Rating data uploads, reference lists and thresholds. "
            "Platform links and refresh requests are in the Aggregators block."
        ),
    },
    "ratings.admin.count": {"ru": "Блоков: {n}", "en": "Blocks: {n}"},
    "ratings.admin.coverage": {
        "ru": "Охват площадок и привязка Glovo →",
        "en": "Platform coverage and the Glovo link →",
    },
    "ratings.admin.panel": {"ru": "Блок настроек", "en": "Settings block"},
    "ratings.admin.block.sheet": {"ru": "Таблица контроля", "en": "Control spreadsheet"},
    "ratings.admin.block.upload": {"ru": "Загрузка файла", "en": "File upload"},
    "ratings.admin.block.layout": {"ru": "Компоновка страницы", "en": "Page layout"},
    "ratings.admin.block.journal": {"ru": "Журнал загрузок", "en": "Upload log"},
    "ratings.admin.block.issues": {"ru": "Несопоставленное", "en": "Unmatched rows"},
    "ratings.admin.block.developers": {"ru": "Девелоперы стран", "en": "Country developers"},
    "ratings.admin.block.rules": {"ru": "Хард-правила", "en": "Hard rules"},
    "ratings.admin.block.aggregators": {"ru": "Агрегаторы", "en": "Aggregators"},
    "ratings.admin.aggregators.state": {
        "ru": "Привязка площадок и обновление данных",
        "en": "Platform links and data refresh",
    },
    "ratings.admin.block.settings": {"ru": "Пороги", "en": "Thresholds"},
    "ratings.admin.sheet.off": {"ru": "Самозабор выключен", "en": "Auto-pull is off"},
    "ratings.admin.sheet.failed": {
        "ru": "Не удалось забрать листов: {n}",
        "en": "Could not pull {n} sheets",
    },
    "ratings.admin.upload.last": {
        "ru": "Последняя загрузка {at}",
        "en": "Last upload {at}",
    },
    "ratings.admin.journal.state": {"ru": "Записей: {n}", "en": "Entries: {n}"},
    "ratings.admin.issues.none": {"ru": "Нестыковок нет", "en": "No mismatches"},
    "ratings.admin.issues.some": {"ru": "Нестыковок: {n}", "en": "Mismatches: {n}"},
    "ratings.admin.developers.state": {
        "ru": "Задан у {set} из {total} стран",
        "en": "Set for {set} of {total} countries",
    },
    "ratings.admin.rules.state": {"ru": "Правил: {n}", "en": "Rules: {n}"},
}

ADMINISTRATION_TEXTS.update(AGGREGATORS_ADMIN_TEXTS)
