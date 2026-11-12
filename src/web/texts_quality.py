"""Тексты экрана «Качество»: фильтры, таблицы, блоки, пояснение, пустые состояния.

Отдельным модулем, как у «Обучения» (`texts_training.py`): `texts.py` уже длиннее предела
файла. Сливаются в общий каталог (`texts.TEXTS`) — `t()` знает один словарь.
"""

from __future__ import annotations

QUALITY_TEXTS: dict[str, dict[str, str]] = {
    "quality.latest_data": {
        "ru": "Последний месяц с сохранёнными данными Dodo IS: {month}.",
        "en": "Latest month with saved Dodo IS data: {month}.",
    },
    "quality.latest_open": {"ru": "Открыть этот месяц", "en": "Open this month"},
    "section.quality.title": {"ru": "Качество", "en": "Quality"},
    "quality.title": {"ru": "Качество", "en": "Quality"},
    "quality.kicker.network": {"ru": "Качество · сеть", "en": "Quality · network"},
    "quality.kicker.country": {"ru": "Качество · страна", "en": "Quality · country"},
    "quality.filters.label": {"ru": "Фильтры", "en": "Filters"},
    "quality.filters.country": {"ru": "Страна", "en": "Country"},
    "quality.filters.period": {"ru": "Период", "en": "Period"},
    "quality.period.by_months": {
        "ru": "Считается по месяцам: {span}.",
        "en": "Calculated by month: {span}.",
    },
    "quality.period.running": {
        "ru": "Последний месяц ещё идёт.",
        "en": "The last month is still in progress.",
    },
    "quality.period.capped": {
        "ru": "Период длиннее {n} месяцев — взяты последние.",
        "en": "The period is longer than {n} months — the latest are taken.",
    },
    "quality.network": {"ru": "Все страны", "en": "All countries"},
    "quality.month.in_progress": {
        "ru": "{title} · месяц идёт",
        "en": "{title} · month in progress",
    },
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
    "quality.tip.title": {"ru": "Как читать таблицу", "en": "How to read the table"},
    "quality.tip.unit": {
        "ru": "Строка — страна или пиццерия за месяц. Под числом — изменение к прошлому месяцу.",
        "en": "A row is a country or pizzeria per month. Under a number — change vs last month.",
    },
    "quality.tip.overall": {
        "ru": "Рейтинг из 5 — сумма «оценка × вес». Как считается — на странице страны.",
        "en": "Rating out of 5 = sum of score × weight. How — on the country page.",
    },
    "quality.tip.rko": {
        "ru": "РКО за месяц — все недели, задевшие месяц.",
        "en": "RKO for a month — every week touching the month.",
    },
    "quality.tip.tone": {
        "ru": "Красный — РКО или РС ниже 80. Жёлтый — ниже 90 или хуже прошлого месяца.",
        "en": "Red — RKO or RS below 80. Amber — below 90 or worse than last month.",
    },
    "quality.tip.audit": {
        "ru": "Проверка — последняя проверка decimus в месяце.",
        "en": "Inspection — the last decimus inspection in the month.",
    },
    "quality.tip.maps_head": {
        "ru": (
            "Карта за месяц — среднее оценок, поставленных в этом месяце (удалённые не "
            "считаются). Пиццерия — средневзвешенное карт по числу оценок, страна — по числу "
            "оценок всех пиццерий. Если оценок нет или их меньше 10% от среднего за 3 прошлых "
            "месяца — берётся прошлый месяц."
        ),
        "en": (
            "A map's value for the month is the mean of the ratings given in that month "
            "(deleted ones do not count). A pizzeria is the mean of its maps weighted by "
            "rating counts, a country is weighted by the rating counts of all its pizzerias. "
            "If there are no ratings or fewer than 10% of the average of the previous 3 "
            "months, the previous month is taken."
        ),
    },
    "quality.tip.maps_carried": {
        "ru": "Карты, месяц перенесён из прошлого (мало оценок), пиццерий: {n} — {items}",
        "en": (
            "Maps, month carried over from an earlier one (too few ratings), "
            "pizzerias: {n} — {items}"
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
    # --- таблица
    "quality.block.network": {"ru": "Страны", "en": "Countries"},
    "quality.block.units": {"ru": "Пиццерии", "en": "Pizzerias"},
    "quality.col.country": {"ru": "Страна", "en": "Country"},
    "quality.col.unit": {"ru": "Пиццерия", "en": "Pizzeria"},
    "quality.total": {"ru": "Вся страна", "en": "Whole country"},
    "quality.col.total": {"ru": "Рейтинг, из 5", "en": "Rating, of 5"},
    "quality.col.w_rko": {"ru": "Вес", "en": "Weight"},
    "quality.col.w_kr": {"ru": "Вес", "en": "Weight"},
    "quality.col.w_maps": {"ru": "Вес ({w})", "en": "Weight ({w})"},
    "quality.col.w_aggs": {"ru": "Вес", "en": "Weight"},
    "quality.cell.incomplete": {
        "ru": "неполный · веса {pct}",
        "en": "incomplete · weights {pct}",
    },
    "quality.col.rko": {"ru": "РКО, из 100", "en": "RKO, of 100"},
    "quality.col.rko_adj": {"ru": "РКО adj, из 5", "en": "RKO adj, of 5"},
    "quality.col.rs": {"ru": "РС", "en": "RS"},
    "quality.col.checks": {"ru": "Проверок в нед.", "en": "Checks/wk"},
    "quality.col.kr": {"ru": "Оценка", "en": "Score"},
    "quality.col.maps": {"ru": "Оценка (G/Y)", "en": "Score (G/Y)"},
    "quality.col.aggs": {"ru": "Оценка", "en": "Score"},
    "quality.col.share_agg": {"ru": "Агрегаторы", "en": "Aggregators"},
    "quality.col.share_app": {"ru": "Приложение и сайт", "en": "App and site"},
    "quality.col.share_other": {"ru": "Прочее", "en": "Other"},
    "quality.col.rev_dine": {"ru": "Зал", "en": "Dine-in"},
    "quality.col.rev_delivery": {"ru": "Доставка", "en": "Delivery"},
    "quality.group.rko": {"ru": "РКО", "en": "RKO"},
    "quality.group.kr": {"ru": "КР", "en": "CR"},
    "quality.group.maps": {"ru": "Карты", "en": "Maps"},
    "quality.group.aggs": {"ru": "Агрегаторы", "en": "Aggregators"},
    "quality.group.shares": {"ru": "Доли заказов", "en": "Order shares"},
    "quality.group.revenue": {"ru": "Выручка", "en": "Revenue"},
    "quality.no_data": {
        "ru": "Нет данных за {month} ({n}): ",
        "en": "No data for {month} ({n}): ",
    },
    "quality.col.audit": {"ru": "Проверка", "en": "Inspection"},
    # --- страна
    "quality.col.score": {"ru": "Оценка", "en": "Score"},
    "quality.col.orders": {"ru": "Заказов", "en": "Orders"},
    "quality.col.share": {"ru": "Доля", "en": "Share"},
    "quality.col.units_n": {"ru": "Пиццерий", "en": "Pizzerias"},
    "quality.col.reviews": {"ru": "Отзывов", "en": "Reviews"},
    "quality.col.avg": {"ru": "Средняя", "en": "Average"},
    "quality.col.count": {"ru": "Оценок", "en": "Ratings"},
    "quality.col.channel": {"ru": "Канал продаж", "en": "Sales channel"},
    "quality.col.source": {"ru": "Источник заказа", "en": "Order source"},
    "quality.col.revenue": {"ru": "Выручка", "en": "Revenue"},
    "quality.col.aggregator": {"ru": "Агрегатор", "en": "Aggregator"},
    "quality.col.agg_score": {"ru": "Оценка", "en": "Rating"},
    "quality.col.agg_score5": {"ru": "В пяти баллах", "en": "Five-point"},
    "quality.col.provider": {"ru": "Карта", "en": "Map"},
    "quality.col.period": {"ru": "Период", "en": "Period"},
    "quality.col.span": {"ru": "Даты", "en": "Dates"},
    "quality.col.status": {"ru": "Статус", "en": "Status"},
    "quality.channel.dine_in": {"ru": "Зал", "en": "Dine-in"},
    "quality.channel.takeaway": {"ru": "Самовывоз", "en": "Takeaway"},
    "quality.channel.delivery": {"ru": "Доставка", "en": "Delivery"},
    "quality.channel.other": {"ru": "Другое", "en": "Other"},
    "quality.source.dinein": {"ru": "Зал", "en": "Dine-in"},
    "quality.source.mobileapp": {"ru": "Приложение", "en": "Mobile app"},
    "quality.source.website": {"ru": "Сайт", "en": "Website"},
    "quality.source.kiosk": {"ru": "Киоск", "en": "Kiosk"},
    "quality.source.manager": {"ru": "Менеджер", "en": "Manager"},
    "quality.source.callcenter": {"ru": "Колл-центр", "en": "Call center"},
    "quality.source.aggregator": {"ru": "Агрегаторы", "en": "Aggregators"},
    "quality.block.overall": {"ru": "Как считается итог", "en": "How the total is computed"},
    "quality.overall.rko": {
        "ru": "РКО — из 100 баллов; делится на {divisor}, получается оценка из 5.",
        "en": "RKO is out of 100; divided by {divisor} it becomes a score out of 5.",
    },
    "quality.overall.rko_weight": {
        "ru": "Вес РКО зависит от числа проверок РКО в неделю: {tiers}.",
        "en": "The weight of RKO depends on RKO checks per week: {tiers}.",
    },
    "quality.overall.tier.zero": {"ru": "нет проверок — {w}", "en": "no checks — {w}"},
    "quality.overall.tier.below": {"ru": "меньше {n} — {w}", "en": "fewer than {n} — {w}"},
    "quality.overall.tier.from": {"ru": "{n} и больше — {w}", "en": "{n} or more — {w}"},
    "quality.overall.maps": {"ru": "Вес карт — {w}.", "en": "The weight of maps is {w}."},
    "quality.overall.rest": {
        "ru": (
            "Остаток веса делится между КР и агрегаторами по их долям в заказах «приложение и "
            "сайт + агрегаторы»; прочие каналы не участвуют."
        ),
        "en": (
            "The remaining weight is split between CR and aggregators by their shares of "
            "“app and site + aggregators” orders; other channels do not take part."
        ),
    },
    "quality.overall.sum": {
        "ru": "Итог — сумма «вес × оценка» по компонентам.",
        "en": "The total is the sum of weight × score over the components.",
    },
    "quality.overall.missing": {
        "ru": (
            "Компонент без оценки получает вес 0; если сумма весов стала меньше 100%, итог "
            "делится на неё и помечается «неполный»."
        ),
        "en": (
            "A component without a score gets weight 0; if the weights then add up to less "
            "than 100%, the total is divided by that sum and marked “incomplete”."
        ),
    },
    "quality.overall.country": {
        "ru": (
            "Итог и веса страны (строка «Вся страна») считаются по её строке: сначала средние "
            "и доли страны, потом эти же правила — не среднее итогов пиццерий{inc}."
        ),
        "en": (
            "The country's total and weights (the “Whole country” row) are computed from its "
            "own row: first the country's means and shares, then the same rules — not the "
            "mean of the pizzerias' totals{inc}."
        ),
    },
    "quality.overall.incomplete": {
        "ru": "; веса страны неполные — {w}",
        "en": "; the country's weights are incomplete — {w}",
    },
    "quality.overall.country_none": {
        "ru": "За этот месяц у страны нет итога.",
        "en": "The country has no total this month.",
    },
    "quality.overall.table": {
        "ru": "Веса и итог каждой пиццерии считаются по ней самой — в таблице выше.",
        "en": (
            "Each pizzeria's weights and total are computed from that pizzeria — see the table "
            "above."
        ),
    },
    "quality.block.revenue": {"ru": "Выручка", "en": "Revenue"},
    "quality.block.aggs": {"ru": "Агрегаторы", "en": "Aggregators"},
    "quality.agg.no_collector": {"ru": "нет сбора оценок", "en": "no ratings collector"},
    "quality.agg.no_score": {"ru": "оценок за месяц нет", "en": "no ratings this month"},
    "quality.block.kr": {"ru": "Клиентский рейтинг (КР)", "en": "Customer rating (CR)"},
    "quality.kr.dine_in": {"ru": "Зал", "en": "Dine-in"},
    "quality.kr.delivery": {"ru": "Доставка", "en": "Delivery"},
    "quality.block.maps": {"ru": "Карты", "en": "Maps"},
    "quality.block.periods": {"ru": "Периоды РКО и РС", "en": "RKO and RS periods"},
    "quality.block.periods_hint": {
        "ru": "из Dodo IS; «предварительно» — оценка ещё не опубликована",
        "en": "from Dodo IS; “preliminary” — the rating is not published yet",
    },
    "quality.period.rko": {"ru": "РКО, неделя", "en": "RKO, week"},
    "quality.period.rs": {"ru": "РС", "en": "RS"},
    "quality.period.preliminary": {
        "ru": "предварительно: {n} из {total}",
        "en": "preliminary: {n} of {total}",
    },
    "quality.period.published": {"ru": "опубликовано", "en": "published"},
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
