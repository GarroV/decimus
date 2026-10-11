"""Тексты «Главной» (D378): доска «Ждёт действия», блоки РС / РКО, «Страны».

Отдельным модулем: `texts.py` уже длиннее предела файла. Сливаются в общий
каталог (`texts.TEXTS`). Подписи блоков, общих со «Страной» (потери по зонам,
системные нарушения, таблица пиццерий), остаются под ключами `overview.*`.
"""

from __future__ import annotations

_MONTHS_SHORT_RU = (
    "янв",
    "фев",
    "мар",
    "апр",
    "май",
    "июн",
    "июл",
    "авг",
    "сен",
    "окт",
    "ноя",
    "дек",
)
_MONTHS_SHORT_EN = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)

HOME_TEXTS: dict[str, dict[str, str]] = {
    "home.only": {"ru": "Только {country}", "en": "Only {country}"},
    "home.only.clear": {"ru": "Показать все страны", "en": "Show all countries"},
    "home.more.ratings": {"ru": "Рейтинги", "en": "Ratings"},
    "home.more.registry": {"ru": "Проверки", "en": "Inspections"},
    # ── Доска «Ждёт действия»: только живые счётчики (D217) ─────────────
    "home.board.title": {"ru": "Ждёт действия", "en": "Waiting for you"},
    "home.board.done": {
        "ru": "Всё сделано: на приёмке, в экшн-планах и предписаниях ничего не ждёт.",
        "en": "All done: nothing is waiting in review, action plans or notices.",
    },
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
    # ── Проверки за период и «Куда смотреть» ────────────────────────────
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
    "home.attention.title": {"ru": "Куда смотреть", "en": "Where to look"},
    "home.attention.empty": {
        "ru": "Всё в пределах норм: критических нарушений и оценок D за период нет.",
        "en": "All within norms: no critical findings and no D grades in the period.",
    },
    # ── РС и РКО (D378, D379) ───────────────────────────────────────────
    "home.rs.title": {"ru": "Стандарты · РС", "en": "Standards · RS"},
    "home.rko.title": {"ru": "Клиентский опыт · РКО", "en": "Customer experience · CX"},
    "home.rs.short": {"ru": "РС", "en": "RS"},
    "home.rko.short": {"ru": "РКО", "en": "CX"},
    "home.ratings.horizon": {"ru": "8 месяцев", "en": "8 months"},
    "home.ratings.month": {
        "ru": "за {month}, к прошлому месяцу",
        "en": "for {month}, vs previous month",
    },
    "home.ratings.mine": {"ru": "Все страны", "en": "All countries"},
    "home.ratings.rated": {"ru": "Пиццерий с оценкой", "en": "Pizzerias rated"},
    "home.ratings.below": {
        "ru": "Ниже порога Top / Bottom ({threshold})",
        "en": "Below the Top / Bottom line ({threshold})",
    },
    "home.ratings.none": {
        "ru": "Рейтинги ещё не загружены: стран IMF в базе нет.",
        "en": "Ratings are not loaded yet: no IMF countries in the database.",
    },
    "home.ratings.no_scores": {
        "ru": "У этих стран нет оценок за последние 8 месяцев.",
        "en": "These countries have no scores in the last 8 months.",
    },
    "home.ratings.failed": {
        "ru": "Рейтинги не загрузились: база не ответила. Обновите страницу.",
        "en": "Ratings did not load: the database did not answer. Reload the page.",
    },
    # ── Страны ──────────────────────────────────────────────────────
    "home.countries.title": {"ru": "Страны", "en": "Countries"},
    "home.countries.hint": {
        "ru": "Щелчок по стране сужает всю главную",
        "en": "Click a country to narrow the whole page",
    },
    "home.countries.country": {"ru": "Страна", "en": "Country"},
    "home.countries.units": {"ru": "Проверено", "en": "Inspected"},
    "home.countries.average": {"ru": "Средняя", "en": "Average"},
    "home.countries.open": {"ru": "Открыть страну: {country}", "en": "Open the country: {country}"},
    "home.countries.empty": {
        "ru": "В охвате нет стран: в справочнике нет пиццерий.",
        "en": "No countries in reach: the directory has no pizzerias.",
    },
    # ── Пиццерии ────────────────────────────────────────────────────────
    "home.units.title": {"ru": "Пиццерии", "en": "Pizzerias"},
    "home.units.empty": {
        "ru": "За период проверок нет. Листните период стрелкой ← или выберите «Всё время».",
        "en": "No inspections in the period. Step back with ← or choose «All time».",
    },
    **{
        f"home.month_short.{n}": {"ru": ru, "en": en}
        for n, (ru, en) in enumerate(zip(_MONTHS_SHORT_RU, _MONTHS_SHORT_EN, strict=True), 1)
    },
}
