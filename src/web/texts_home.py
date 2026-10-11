"""Тексты «Главной» (D378, D395): «Требует внимания», проверки, колонки РС / РКО, «Мои страны».

Отдельным модулем: `texts.py` уже длиннее предела файла. Сливаются в общий
каталог (`texts.TEXTS`). Подписи блоков, общих со «Страной» (потери по зонам,
системные нарушения, таблица пиццерий), остаются под ключами `overview.*`.
"""

from __future__ import annotations

HOME_TEXTS: dict[str, dict[str, str]] = {
    "home.only": {"ru": "Только {country}", "en": "Only {country}"},
    "home.only.clear": {"ru": "Показать все страны", "en": "Show all countries"},
    "home.countries.open": {"ru": "Открыть страну: {country}", "en": "Open the country: {country}"},
    "home.more.registry": {"ru": "Проверки", "en": "Inspections"},
    # ── «Требует внимания»: задания по живым счётчикам (D217) и пиццерии (D395) ─────────────
    "home.board.failed": {
        "ru": "Задания не загрузились: база не ответила. Обновите страницу.",
        "en": "Tasks did not load: the database did not answer. Reload the page.",
    },
    "home.board.overdue": {"ru": "просрочено: {count}", "en": "overdue: {count}"},
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
    # ── Где нужно проверить, последние проверки (D396) ──────────────────
    "home.tocheck.title": {"ru": "Где нужно проверить", "en": "Where to inspect"},
    "home.tocheck.hint": {"ru": "нет проверок за период", "en": "no inspection in the period"},
    "home.tocheck.last": {"ru": "последняя {date}", "en": "last {date}"},
    "home.tocheck.never": {"ru": "ни разу не проверяли", "en": "never inspected"},
    "home.tocheck.more": {"ru": "и ещё {count}", "en": "and {count} more"},
    "home.latest.title": {"ru": "Последние проверки", "en": "Latest inspections"},
    "home.latest.all": {"ru": "Все проверки", "en": "All inspections"},
    "home.top.title": {"ru": "Топ нарушений", "en": "Top violations"},
    # ── Колонки рейтинга клиента в таблице пиццерий (D396) ──────────────
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
    # ── Мои страны ──────────────────────────────────────────────────────
    "home.countries.title": {"ru": "Мои страны", "en": "My countries"},
    "home.countries.hint": {
        "ru": "Щелчок по стране сужает всю главную",
        "en": "Click a country to narrow the whole page",
    },
    "home.countries.country": {"ru": "Страна", "en": "Country"},
    "home.countries.units": {"ru": "Проверено", "en": "Inspected"},
    "home.countries.average": {"ru": "Средняя", "en": "Average"},
    # ── Пиццерии ────────────────────────────────────────────────────────
    "home.units.title": {"ru": "Пиццерии", "en": "Pizzerias"},
    "home.units.empty": {
        "ru": "За период проверок нет. Листните период стрелкой ← или выберите «Всё время».",
        "en": "No inspections in the period. Step back with ← or choose «All time».",
    },
}
