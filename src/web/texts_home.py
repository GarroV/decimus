"""Тексты «Главной» (D378, D398, D418, D471): внимание, проверки, «Рейтинги», фильтры.

Отдельным модулем: `texts.py` уже длиннее предела файла. Сливаются в общий
каталог (`texts.TEXTS`). Подписи блоков, общих со «Страной» (потери по зонам,
системные нарушения, таблица пиццерий), остаются под ключами `overview.*`.
"""

from __future__ import annotations

HOME_TEXTS: dict[str, dict[str, str]] = {
    "home.country.all": {"ru": "Все страны", "en": "All countries"},
    "home.countries.open": {"ru": "Открыть страну: {country}", "en": "Open the country: {country}"},
    "home.cluster.all": {"ru": "Все кластеры", "en": "All clusters"},
    "home.developer.all": {"ru": "Все девелоперы", "en": "All developers"},
    # ── Панель фильтров справа от списка (D471) ─────────────────────────
    "home.filters.title": {"ru": "Фильтры", "en": "Filters"},
    "home.filters.period": {"ru": "Период", "en": "Period"},
    "home.filters.cluster": {"ru": "Кластер", "en": "Cluster"},
    "home.filters.developer": {"ru": "Бизнес-девелопер", "en": "Business developer"},
    "home.filters.country": {"ru": "Страна", "en": "Country"},
    "home.filters.note": {
        "ru": "Фильтры действуют на весь экран, включая верхние блоки.",
        "en": "Filters apply to the whole screen, including the top blocks.",
    },
    "home.more.registry": {"ru": "Проверки", "en": "Inspections"},
    # ── «Требует внимания»: задания по живым счётчикам (D217) и пиццерии (D398) ─────────────
    "home.board.failed": {
        "ru": "Задания не загрузились: база не ответила. Обновите страницу.",
        "en": "Tasks did not load: the database did not answer. Reload the page.",
    },
    "home.board.overdue": {"ru": "просрочено: {count}", "en": "overdue: {count}"},
    # Объявление D629: на стикере — только заголовок (владелец 23.10.2026: «нужно короткое
    # название, внутри уже должно быть написано, что к чему»); пояснение — в плитке Claude,
    # `settings.claude.relink`. Правка текста — только с его «да».
    "home.board.mcp_relink.kind": {"ru": "Объявление", "en": "Announcement"},
    "home.board.mcp_relink.title": {"ru": "Переподключите Claude", "en": "Reconnect Claude"},
    "home.board.mcp_relink.cta": {"ru": "Подробнее", "en": "Details"},
    "home.board.review.kind": {"ru": "Приёмка", "en": "Review"},
    "home.board.review.title": {
        "ru": "Проверок ждут приёмки: {count}",
        "en": "Inspections waiting for review: {count}",
    },
    "home.board.review.cta": {"ru": "Вычитать", "en": "Review"},
    "home.board.plans_review.kind": {"ru": "Экшн-планы", "en": "Action plans"},
    "home.board.plans_review.title": {
        "ru": "Планов на рассмотрении: {count}",
        "en": "Plans to consider: {count}",
    },
    "home.board.plans_review.cta": {"ru": "Рассмотреть", "en": "Consider"},
    "home.board.plans_due.kind": {"ru": "Экшн-планы", "en": "Action plans"},
    "home.board.plans_due.title": {
        "ru": "Ждут вашего плана: {count}",
        "en": "Waiting for your plan: {count}",
    },
    "home.board.plans_due.cta": {"ru": "Сдать план", "en": "Submit a plan"},
    "home.board.orders_due.kind": {"ru": "Предписания", "en": "Notices"},
    "home.board.orders_due.title": {
        "ru": "Срок предписаний на этой неделе: {count}",
        "en": "Notices due this week: {count}",
    },
    "home.board.orders_due.cta": {"ru": "Открыть", "en": "Open"},
    "home.board.ratings_stale.kind": {"ru": "Рейтинги", "en": "Ratings"},
    "home.board.ratings_stale.title": {
        "ru": "РС и РКО не загружались {count} дн.",
        "en": "RS and CX not loaded for {count} days",
    },
    "home.board.ratings_stale.cta": {"ru": "Загрузить", "en": "Upload"},
    # ── Проверки за период ────────────────────────────
    "home.inspections.title": {"ru": "Проверки за период", "en": "Inspections in the period"},
    "home.inspections.average": {
        "ru": "средняя оценка, к прошлому периоду",
        "en": "average score, against the previous period",
    },
    "home.inspections.average_only": {
        "ru": "средняя оценка за период",
        "en": "average score in the period",
    },
    "home.inspections.checked": {"ru": "Пиццерий проверено", "en": "Pizzerias inspected"},
    "home.attention.title": {"ru": "Требует внимания", "en": "Needs attention"},
    "home.inspections.none": {
        "ru": "За период проверок нет.",
        "en": "No inspections in the period.",
    },
    "home.more.n": {"ru": "ещё {n}", "en": "{n} more"},
    "home.top.none": {
        "ru": "Системных нарушений за период нет.",
        "en": "No systemic violations in the period.",
    },
    "home.processes.none": {
        "ru": "Потерь по блокам методики за период нет.",
        "en": "No losses by methodology block in the period.",
    },
    "home.top.title": {"ru": "Топ нарушений", "en": "Top violations"},
    # ── Колонки рейтинга клиента в таблице пиццерий (D399) ──────────────
    "home.rs.short": {"ru": "РС", "en": "RS"},
    "home.rko.short": {"ru": "РКО", "en": "CX"},
    "home.ratings.open": {
        "ru": "Последняя оценка рейтинга — открыть страницу «Рейтинги»",
        "en": "Latest rating score — open the Ratings page",
    },
    "home.ratings.failed": {
        "ru": "Оценки рейтинга не загрузились: в колонках РС и РКО прочерки.",
        "en": "Rating scores did not load: the RS and CX columns show dashes.",
    },
    # ── Блок «Рейтинги» (D418) ──────────────────────────────────────────
    "home.rb.title": {"ru": "Рейтинги", "en": "Ratings"},
    "home.rb.more": {"ru": "Все рейтинги", "en": "All ratings"},
    "home.rb.rs": {"ru": "РС", "en": "RS"},
    "home.rb.rko": {"ru": "РКО", "en": "CX"},
    "home.rb.maps": {"ru": "Карты", "en": "Maps"},
    "home.rb.total": {"ru": "Итого", "en": "Total"},
    "home.rb.prev": {"ru": "Прокрутить влево", "en": "Scroll left"},
    "home.rb.next": {"ru": "Прокрутить вправо", "en": "Scroll right"},
    "home.rb.aggs_failed": {
        "ru": "Оценки агрегаторов не загрузились.",
        "en": "Delivery app ratings did not load.",
    },
    "home.rb.aggs_later": {
        "ru": "Агрегаторы — последние собранные оценки: за этот период их ещё не собирали.",
        "en": "Delivery apps show the latest collected ratings: "
        "none were collected for this period.",
    },
    "home.rb.none": {
        "ru": "Для выбранной страны рейтингов нет.",
        "en": "No ratings for the selected country.",
    },
    "home.rb.failed": {
        "ru": "Рейтинги не загрузились: база не ответила. Обновите страницу.",
        "en": "Ratings did not load: the database did not answer. Reload the page.",
    },
    "home.rb.maps_failed": {
        "ru": "Оценки карт не загрузились.",
        "en": "Map ratings did not load.",
    },
    # ── Пиццерии ────────────────────────────────────────────────────────
    "home.units.title": {"ru": "Пиццерии", "en": "Pizzerias"},
    "home.units.empty": {
        "ru": "За период проверок нет. Листните период стрелкой ← или выберите «Всё время».",
        "en": "No inspections in the period. Step back with ← or choose «All time».",
    },
}
