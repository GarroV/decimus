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
    "administration.tab.journal": {"ru": "Журнал", "en": "Log"},
    "administration.tab.usage": {"ru": "Расход модели", "en": "Model usage"},
    "administration.tab.connections": {"ru": "Подключения", "en": "Connections"},
    "administration.group.access": {"ru": "Люди и доступ", "en": "People & access"},
    "administration.group.journal": {"ru": "Журнал", "en": "Journal"},
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
    "health.check_now": {"ru": "Проверить сейчас", "en": "Check now"},
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
    # ── Подключения ──
    "health.conn.openai": {"ru": "OpenAI — распознавание", "en": "OpenAI — recognition"},
    "health.conn.telegram": {"ru": "Бот в Telegram", "en": "Telegram bot"},
    "health.conn.storage": {"ru": "Хранилище кадров", "en": "Photo storage"},
    "health.conn.google": {"ru": "Вход через Google", "en": "Google sign-in"},
    "health.conn.pointer": {"ru": "Pointer — оценки на картах", "en": "Pointer — map ratings"},
    "health.conn.ispring": {"ru": "iSpring — обучение", "en": "iSpring — training"},
    "health.conn.aggregators": {
        "ru": "Сбор оценок агрегаторов",
        "en": "Aggregator ratings collection",
    },
    "health.conn.maps": {"ru": "Сбор оценок на картах", "en": "Map ratings collection"},
    "health.conn.sheet": {"ru": "Таблица контроля", "en": "Control spreadsheet"},
    "health.conn.learning": {"ru": "Загрузка обучения", "en": "Training load"},
    "health.conn.backup": {"ru": "Ночной бэкап", "en": "Nightly backup"},
    "health.conn.dodo_is": {"ru": "Dodo IS по странам", "en": "Dodo IS by country"},
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
    "health.reason.dodo_is_pending": {
        "ru": "Подключение готовится",
        "en": "Connection in preparation",
    },
}
