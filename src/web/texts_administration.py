"""Тексты раздела «Администрирование» (D639) и вкладки «Подключения» (D638, #1251).

Сливаются в общий каталог (`texts.TEXTS`) — `t()` знает один словарь.
"""

from __future__ import annotations

ADMINISTRATION_TEXTS: dict[str, dict[str, str]] = {
    "section.administration.title": {"ru": "Администрирование", "en": "Administration"},
    "administration.tabs": {"ru": "Разделы администрирования", "en": "Administration tabs"},
    "administration.tab.people": {"ru": "Люди", "en": "People"},
    "administration.tab.spaces": {"ru": "Пространства партнёров", "en": "Partner spaces"},
    "administration.tab.spaces_own": {"ru": "Ваше пространство", "en": "Your space"},
    "administration.tab.countries": {"ru": "Страны", "en": "Countries"},
    "administration.tab.journal": {"ru": "Журнал", "en": "Log"},
    "administration.tab.dodois": {"ru": "Dodo IS", "en": "Dodo IS"},
    "administration.tab.usage": {"ru": "Расход модели", "en": "Model usage"},
    "administration.tab.connections": {"ru": "Подключения", "en": "Connections"},
    "administration.group.access": {"ru": "Люди и доступ", "en": "People & access"},
    "administration.group.connections": {"ru": "Внешние сервисы", "en": "External services"},
    "administration.group.journal": {"ru": "Журнал и расход", "en": "Journal & usage"},
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
        "ru": "Партнёр, девелопер, языки отчёта и договор страны. Выберите страну в списке.",
        "en": "Partner, developer, report languages and agreement of a country. "
        "Pick a country in the list.",
    },
    "countries.count": {"ru": "Стран: {count}", "en": "Countries: {count}"},
    "countries.none": {"ru": "Стран в справочнике нет.", "en": "No countries in the directory."},
    "countries.col.country": {"ru": "Страна", "en": "Country"},
    "countries.col.space": {"ru": "Партнёр", "en": "Partner"},
    "countries.col.developer": {"ru": "Девелопер", "en": "Developer"},
    "countries.partial_failed": {
        "ru": "Партнёры или девелоперы сейчас не прочитались: в столбцах могут быть пропуски.",
        "en": "Partners or developers could not be read: some cells may be empty.",
    },
}
