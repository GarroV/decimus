"""Тексты экрана «Качество»: колонка стран, блоки, пояснение формулы, пустые состояния.

Отдельным модулем, как у «Обучения» (`texts_training.py`): `texts.py` уже длиннее предела
файла. Сливаются в общий каталог (`texts.TEXTS`) — `t()` знает один словарь.
"""

from __future__ import annotations

QUALITY_TEXTS: dict[str, dict[str, str]] = {
    "section.quality.title": {"ru": "Качество", "en": "Quality"},
    "quality.title": {"ru": "Качество", "en": "Quality"},
    "quality.kicker.network": {"ru": "Качество · сеть", "en": "Quality · network"},
    "quality.kicker.country": {"ru": "Качество · страна", "en": "Quality · country"},
    "quality.network": {"ru": "Все страны", "en": "All countries"},
    "quality.filter.title": {"ru": "Страны", "en": "Countries"},
    "quality.rail.line": {"ru": "ЛКО {lko} · ЭС {es}", "en": "LKO {lko} · ES {es}"},
    "quality.rail.lko": {"ru": "ЛКО {lko}", "en": "LKO {lko}"},
    "quality.rail.none": {"ru": "нет данных", "en": "no data"},
    "quality.place": {"ru": "{n}-е место", "en": "place {n}"},
    "quality.place.of": {"ru": "место {n} из {total}", "en": "place {n} of {total}"},
    "quality.units": {"ru": "пиццерий: {n}", "en": "pizzerias: {n}"},
    "quality.month.label": {"ru": "Месяц", "en": "Month"},
    "quality.month.prev": {"ru": "Предыдущий месяц", "en": "Previous month"},
    "quality.month.next": {"ru": "Следующий месяц", "en": "Next month"},
    "quality.month.title": {"ru": "{month} {year}", "en": "{month} {year}"},
    "quality.failed": {
        "ru": "Данные качества сейчас не прочитались: база не ответила. Попробуйте позже.",
        "en": (
            "Quality data could not be read right now: the "
            "database did not answer. Try again later."
        ),
    },
    "quality.empty.country": {
        "ru": "За этот месяц по стране нет данных качества.",
        "en": "No quality data for this country in this month.",
    },
    "quality.empty.scope": {
        "ru": "Для вашего доступа нет стран с данными качества.",
        "en": "There are no countries with quality data in your access.",
    },
    # --- пояснение под «?»
    "quality.tip.title": {"ru": "Как считается", "en": "How it is calculated"},
    "quality.tip.unit": {
        "ru": "Единица расчёта — пиццерия за месяц; страна — простое среднее своих пиццерий.",
        "en": (
            "The unit is one pizzeria for one month; a country is the plain mean of its pizzerias."
        ),
    },
    "quality.tip.lko": {
        "ru": (
            "ЛКО, пять баллов: РКО (оценка / 20, вес по числу проверок в неделю: "
            "0 — 0%, до 2 — 10%, от 2 до 5 — 30%, от 5 — 50%), карты (среднее Google и "
            "Яндекса по числу оценок, вес 20%), КР и агрегаторы делят остаток веса по долям "
            "заказов "
            "приложения и сайта и агрегаторов. Итог — сумма «вес × оценка», без пересчёта."
        ),
        "en": (
            "LKO, five points: RKO (score / 20, weight by checks per week: 0 — 0%, under 2 — "
            "10%, 2 to 5 — 30%, 5 and up — 50%), maps (mean of Google and Yandex "
            "weighted by rating counts, weight 20%), "
            "CR and aggregators split the remaining weight by the order shares of the app and "
            "website versus aggregators. The total is the sum of weight x score, not rescaled."
        ),
    },
    "quality.tip.es": {
        "ru": (
            "ЭС: половина — оценка последней проверки decimus в месяце, половина — РС. "
            "Нет проверки в месяце — ЭС нет, вес на РС не переносится."
        ),
        "en": (
            "ES: half is the score of the last decimus inspection in the month, half is RS. "
            "No inspection in the month — no ES; the weight is not moved to RS."
        ),
    },
    "quality.tip.kr": {
        "ru": (
            "КР из Dodo IS приходит отдельно для зала и доставки; здесь они сведены в одну "
            "оценку средним, взвешенным числом оценок (допущение, согласовать с аналитиком)."
        ),
        "en": (
            "CR from Dodo IS comes separately for dine-in and delivery; here they are combined "
            "as a mean weighted by the number of ratings (an assumption to confirm with the "
            "analyst)."
        ),
    },
    "quality.tip.fresh": {
        "ru": "РКО и РС — по дате начала периода; карты и агрегаторы — последняя оценка в месяце.",
        "en": (
            "RKO and RS go by the period start date; maps and "
            "aggregators use the last rating in the month."
        ),
    },
    "quality.tip.dodois": {"ru": "Dodo IS: собрано {at}", "en": "Dodo IS: collected {at}"},
    "quality.tip.dodois_error": {
        "ru": "Dodo IS: последний сбор упал — {countries}",
        "en": "Dodo IS: the last collection failed — {countries}",
    },
    "quality.tip.source.dodois": {"ru": "РКО и РС: Dodo IS", "en": "RKO and RS: Dodo IS"},
    "quality.tip.source.sheet": {
        "ru": "РКО и РС: таблица контроля",
        "en": "RKO and RS: the control table",
    },
    "quality.tip.source.mixed": {
        "ru": "РКО и РС: Dodo IS, где есть, иначе таблица контроля",
        "en": "RKO and RS: Dodo IS where available, otherwise the control table",
    },
    "quality.tip.dodois_none": {
        "ru": "Dodo IS: сбор ещё не запускался",
        "en": "Dodo IS: collection has not run yet",
    },
    # --- плитки и сводка
    "quality.tile.lko": {"ru": "Лучший клиентский опыт", "en": "Best customer experience"},
    "quality.tile.es": {"ru": "Эталон стандартов", "en": "Standards benchmark"},
    "quality.tile.lko_sub": {
        "ru": "{place} · пиццерий с ЛКО: {n}",
        "en": "{place} · pizzerias with LKO: {n}",
    },
    "quality.tile.es_sub": {
        "ru": "пиццерий с ЭС: {n} из {total}",
        "en": "pizzerias with ES: {n} of {total}",
    },
    "quality.tile.delta": {"ru": "к прошлому месяцу {d}", "en": "vs previous month {d}"},
    "quality.block.network": {"ru": "Страны по качеству", "en": "Countries by quality"},
    "quality.col.place": {"ru": "Место", "en": "Place"},
    "quality.col.country": {"ru": "Страна", "en": "Country"},
    "quality.col.lko": {"ru": "ЛКО", "en": "LKO"},
    "quality.col.es": {"ru": "ЭС", "en": "ES"},
    "quality.col.delta": {"ru": "Δ", "en": "Δ"},
    "quality.col.units": {"ru": "Пиццерий", "en": "Pizzerias"},
    # --- страна
    "quality.block.lko": {"ru": "Из чего складывается ЛКО", "en": "What LKO is made of"},
    "quality.block.lko_hint": {
        "ru": "среднее по пиццериям страны",
        "en": "mean over the country's pizzerias",
    },
    "quality.col.component": {"ru": "Компонент", "en": "Component"},
    "quality.col.score": {"ru": "Оценка", "en": "Score"},
    "quality.col.weight": {"ru": "Вес", "en": "Weight"},
    "quality.comp.rko": {"ru": "РКО (в пяти баллах)", "en": "RKO (five points)"},
    "quality.comp.kr": {"ru": "КР: приложение и сайт", "en": "CR: app and website"},
    "quality.comp.maps": {"ru": "Карты", "en": "Maps"},
    "quality.comp.aggregators": {"ru": "Агрегаторы", "en": "Aggregators"},
    "quality.comp.sum": {"ru": "Сумма весов", "en": "Sum of weights"},
    "quality.warn.sum": {
        "ru": "Сумма весов {sum} — часть веса выпала (нет данных по компоненту), итог занижен.",
        "en": (
            "Sum of weights {sum} — part of the weight dropped (a "
            "component has no data), the total is understated."
        ),
    },
    "quality.block.es": {"ru": "Из чего складывается ЭС", "en": "What ES is made of"},
    "quality.es.audit": {"ru": "Проверка decimus", "en": "decimus inspection"},
    "quality.es.rs": {"ru": "Рейтинг стандартов (РС)", "en": "Standards rating (RS)"},
    "quality.es.share": {"ru": "{pct} веса", "en": "{pct} of the weight"},
    "quality.es.no_audit": {"ru": "— нет проверки", "en": "— no inspection"},
    "quality.es.no_rs": {"ru": "— нет РС", "en": "— no RS"},
    "quality.es.missing": {
        "ru": "Без проверки в месяце ЭС не считается: пиццерий без ЭС — {n}.",
        "en": (
            "Without an inspection in the month ES is not calculated: pizzerias without ES — {n}."
        ),
    },
    "quality.block.units": {"ru": "Пиццерии", "en": "Pizzerias"},
    "quality.col.unit": {"ru": "Пиццерия", "en": "Pizzeria"},
    "quality.col.rko": {"ru": "РКО", "en": "RKO"},
    "quality.col.checks": {"ru": "Пров./нед.", "en": "Checks/wk"},
    "quality.col.rs": {"ru": "РС", "en": "RS"},
    "quality.col.audit": {"ru": "Проверка", "en": "Inspection"},
    "quality.col.kr": {"ru": "КР", "en": "CR"},
    "quality.col.maps": {"ru": "Карты", "en": "Maps"},
    "quality.col.aggs": {"ru": "Агрег.", "en": "Aggr."},
    "quality.col.wsum": {"ru": "Σ весов", "en": "Σ weights"},
    "quality.block.orders": {"ru": "Каналы заказов", "en": "Order channels"},
    "quality.col.orders": {"ru": "Заказов", "en": "Orders"},
    "quality.col.n": {"ru": "Агрегаторы", "en": "Aggregators"},
    "quality.col.o": {"ru": "Приложение и сайт", "en": "App and website"},
    "quality.col.p": {"ru": "Прочее", "en": "Other"},
    "quality.total": {"ru": "Вся страна", "en": "Whole country"},
    "quality.block.revenue": {"ru": "Выручка по каналам продаж", "en": "Revenue by sales channel"},
    "quality.col.channel": {"ru": "Канал", "en": "Channel"},
    "quality.col.revenue": {"ru": "Выручка", "en": "Revenue"},
    "quality.col.share": {"ru": "Доля", "en": "Share"},
    "quality.channel.dine_in": {"ru": "Зал", "en": "Dine-in"},
    "quality.channel.takeaway": {"ru": "Самовывоз", "en": "Takeaway"},
    "quality.channel.delivery": {"ru": "Доставка", "en": "Delivery"},
    "quality.channel.other": {"ru": "Другое", "en": "Other"},
    "quality.block.aggs": {"ru": "Агрегаторы", "en": "Aggregators"},
    "quality.col.aggregator": {"ru": "Агрегатор", "en": "Aggregator"},
    "quality.col.agg_score": {"ru": "Оценка", "en": "Rating"},
    "quality.col.agg_score5": {"ru": "В пяти баллах", "en": "Five-point"},
    "quality.agg.no_collector": {"ru": "нет сбора оценок", "en": "no ratings collector"},
    "quality.agg.no_score": {"ru": "оценок за месяц нет", "en": "no ratings this month"},
    "quality.block.kr": {"ru": "Клиентский рейтинг (КР)", "en": "Customer rating (CR)"},
    "quality.col.avg": {"ru": "Средняя", "en": "Average"},
    "quality.col.count": {"ru": "Оценок", "en": "Ratings"},
    "quality.kr.dine_in": {"ru": "Зал", "en": "Dine-in"},
    "quality.kr.delivery": {"ru": "Доставка", "en": "Delivery"},
    "quality.block.maps": {"ru": "Карты", "en": "Maps"},
    "quality.col.provider": {"ru": "Карта", "en": "Map"},
    "quality.col.reviews": {"ru": "Отзывов", "en": "Reviews"},
    "quality.maps.google": {"ru": "Google", "en": "Google"},
    "quality.maps.yandex": {"ru": "Яндекс", "en": "Yandex"},
    "quality.nothing": {"ru": "нет данных", "en": "no data"},
    # --- Dodo IS
    "quality.dodois.not_connected": {
        "ru": "Нет данных Dodo IS — страна не подключена.",
        "en": "No Dodo IS data — the country is not connected.",
    },
    "quality.dodois.not_collected": {
        "ru": "Данные Dodo IS ещё не собраны.",
        "en": "Dodo IS data has not been collected yet.",
    },
}
