"""Тексты экрана «Качество»: колонка стран, таблицы, блоки, пояснение, пустые состояния.

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
    "quality.rail.line": {"ru": "РКО {rko} · РС {rs}", "en": "RKO {rko} · RS {rs}"},
    "quality.rail.none": {"ru": "нет данных", "en": "no data"},
    "quality.month.label": {"ru": "Месяц", "en": "Month"},
    "quality.month.prev": {"ru": "Предыдущий месяц", "en": "Previous month"},
    "quality.month.next": {"ru": "Следующий месяц", "en": "Next month"},
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
        "ru": (
            "Единица — пиццерия за месяц. Страна: оценки — простое среднее её пиццерий, "
            "доли заказов и выручка — по суммам. Под числом — движение к прошлому месяцу."
        ),
        "en": (
            "The unit is one pizzeria for one month. A country: ratings are the plain mean of "
            "its pizzerias, order shares and revenue are totals. Under a number — the change "
            "from the previous month."
        ),
    },
    "quality.tip.scores": {
        "ru": (
            "РКО, РС и проверка — сто баллов; КР, карты и агрегаторы — пять. КР: зал и "
            "доставка, среднее по числу оценок. Карты: Google и Яндекс, среднее по числу "
            "оценок. Агрегаторы: оценки площадок в пяти баллах, среднее по заказам среди "
            "площадок с оценкой. Проверок РКО в неделю — среднее по неделям месяца."
        ),
        "en": (
            "RKO, RS and inspection are out of 100; CR, maps and aggregators out of 5. CR: "
            "dine-in and delivery, mean weighted by rating counts. Maps: Google and Yandex, "
            "mean weighted by rating counts. Aggregators: platform ratings in five points, "
            "mean weighted by orders among rated platforms. RKO checks per week — the mean "
            "over the weeks of the month."
        ),
    },
    "quality.tip.tone": {
        "ru": (
            "Цвет ячейки: РКО и РС — как в «Рейтингах» (ниже 80 красный, ниже 90 жёлтый); "
            "остальные показатели — жёлтым, если стали хуже прошлого месяца. Доли заказов "
            "не подсвечиваются."
        ),
        "en": (
            "Cell colour: RKO and RS as in Ratings (below 80 red, below 90 amber); other "
            "figures turn amber when worse than the previous month. Order shares are not "
            "coloured."
        ),
    },
    "quality.tip.audit": {
        "ru": "Проверка — процент последней принятой проверки decimus в месяце.",
        "en": "Inspection — the percentage of the last accepted decimus inspection in the month.",
    },
    "quality.tip.fresh": {
        "ru": (
            "РКО — по дате начала недели; РС — по месяцу, на который падает большинство его "
            "дней; карты и агрегаторы — последняя оценка в месяце."
        ),
        "en": (
            "RKO goes by the week start date; RS by the month holding most of its days; maps "
            "and aggregators use the last rating in the month."
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
    "quality.col.rko": {"ru": "РКО", "en": "RKO"},
    "quality.col.rs": {"ru": "РС", "en": "RS"},
    "quality.col.checks": {"ru": "Пров./нед.", "en": "Checks/wk"},
    "quality.col.kr": {"ru": "КР", "en": "CR"},
    "quality.col.maps": {"ru": "Карты", "en": "Maps"},
    "quality.col.aggs": {"ru": "Агрег.", "en": "Aggr."},
    "quality.col.share_agg": {"ru": "Агрегаторы, %", "en": "Aggregators, %"},
    "quality.col.share_app": {"ru": "Прилож. и сайт, %", "en": "App and site, %"},
    "quality.col.share_other": {"ru": "Прочее, %", "en": "Other, %"},
    "quality.col.rev_dine": {"ru": "Выручка: зал", "en": "Revenue: dine-in"},
    "quality.col.rev_delivery": {"ru": "Выручка: доставка", "en": "Revenue: delivery"},
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
