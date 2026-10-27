"""Тексты раздела «Рейтинги» и подраздела «Загрузки» (спека 2026-10-08).

Отдельным модулем: `texts.py` длиннее предела файла. Сливаются в общий каталог
(`texts.TEXTS`). Названия нарушений сюда не попадают — они идут как в источнике.

Причины отказа — по коду (P15): `ratings.error.<код RatingsFormatError>`,
`ratings.issue.<reason журнала замечаний>`, `ratings.refused.<код RatingsEditError>`.
Русский текст исключения в веб не выводится: он остаётся журналу и MCP.
"""

from __future__ import annotations

_SCREEN: dict[str, dict[str, str]] = {
    "section.ratings.title": {"ru": "Рейтинги", "en": "Ratings"},
    "ratings.kicker": {"ru": "РС и РКО", "en": "Standards and customer experience"},
    "ratings.title": {"ru": "Рейтинги пиццерий IMF", "en": "IMF pizzeria ratings"},
    "ratings.rs": {"ru": "РС", "en": "Standards"},
    "ratings.rko": {"ru": "РКО", "en": "Customer exp."},
    "ratings.group": {"ru": "Срез", "en": "Group by"},
    "ratings.group.developer": {"ru": "Бизнес-девелопер", "en": "Business developer"},
    "ratings.group.country": {"ru": "Страна", "en": "Country"},
    "ratings.group.imf": {"ru": "Весь IMF", "en": "All IMF"},
    "ratings.period": {"ru": "Период", "en": "Period"},
    "ratings.period.rs": {"ru": "Период РС", "en": "RS period"},
    "ratings.period.rko": {"ru": "Неделя РКО", "en": "RKO week"},
    "ratings.period.none": {"ru": "Выбрать…", "en": "Choose…"},
    "ratings.period.month": {"ru": "Месяц", "en": "Month"},
    "ratings.period.quarter": {"ru": "Квартал", "en": "Quarter"},
    "ratings.month.1": {"ru": "Янв", "en": "Jan"},
    "ratings.month.2": {"ru": "Фев", "en": "Feb"},
    "ratings.month.3": {"ru": "Мар", "en": "Mar"},
    "ratings.month.4": {"ru": "Апр", "en": "Apr"},
    "ratings.month.5": {"ru": "Май", "en": "May"},
    "ratings.month.6": {"ru": "Июн", "en": "Jun"},
    "ratings.month.7": {"ru": "Июл", "en": "Jul"},
    "ratings.month.8": {"ru": "Авг", "en": "Aug"},
    "ratings.month.9": {"ru": "Сен", "en": "Sep"},
    "ratings.month.10": {"ru": "Окт", "en": "Oct"},
    "ratings.month.11": {"ru": "Ноя", "en": "Nov"},
    "ratings.month.12": {"ru": "Дек", "en": "Dec"},
    "ratings.cal.prev": {"ru": "Предыдущий период", "en": "Previous period"},
    "ratings.cal.next": {"ru": "Следующий период", "en": "Next period"},
    "ratings.cal.from": {"ru": "С", "en": "From"},
    "ratings.cal.to": {"ru": "По", "en": "To"},
    "ratings.show": {"ru": "Показать", "en": "Show"},
    "ratings.loaded": {"ru": "{fmt} — {at}", "en": "{fmt} — {at}"},
    "ratings.loaded.hint": {"ru": "Когда обновлены данные", "en": "When the data was updated"},
    "ratings.loaded.title": {"ru": "Последняя загрузка", "en": "Last upload"},
    "ratings.loaded.none": {"ru": "Загрузок ещё не было.", "en": "Nothing has been uploaded yet."},
    "ratings.manage": {"ru": "Настройки рейтингов", "en": "Ratings settings"},
    "ratings.block.scores": {
        "ru": "Средний РС и РКО",
        "en": "Average standards and customer experience",
    },
    "ratings.group.cluster": {"ru": "Кластер", "en": "Cluster"},
    "ratings.cluster.CEE": {"ru": "CEE", "en": "CEE"},
    "ratings.cluster.TR": {"ru": "Турция", "en": "Turkey"},
    "ratings.cluster.CAUCASUS": {"ru": "Кавказ", "en": "Caucasus"},
    "ratings.cluster.OTHER": {"ru": "Остальные страны", "en": "Other countries"},
    "ratings.countries.n": {"ru": "стран: {n}", "en": "countries: {n}"},
    "ratings.line.title": {
        "ru": "{p}: {v} · пиццерий: {n}",
        "en": "{p}: {v} · pizzerias: {n}",
    },
    "ratings.line.aria": {
        "ru": "{name}, {kind}: динамика по периодам рейтинга",
        "en": "{name}, {kind}: trend by rating period",
    },
    "ratings.line.hint": {
        "ru": "Точка — период рейтинга (РС — полмесяца, РКО — неделя), задевший выбранные "
        "даты; подписи снизу — его даты. Красная линия — порог {x}; фон — зоны: "
        "ниже 80, 80–90, от 90. "
        "Подробнее по стране — фильтром «Страна».",
        "en": "Each point is a rating period (RS — half a month, RKO — a week) that touches "
        "the selected dates; the labels below are its dates. Red line — threshold {x}; "
        "the background shows zones: below 80, 80–90, 90 and up. "
        "For a single country, use the Country filter.",
    },
    "ratings.line.empty": {"ru": "За период нет данных.", "en": "No data for the period."},
    "ratings.col.country": {"ru": "Страна", "en": "Country"},
    "ratings.col.delta": {"ru": "Δ к {prev}", "en": "Δ vs {prev}"},
    "ratings.total": {"ru": "Итого", "en": "Total"},
    "ratings.block.rko_violations": {"ru": "Нарушения РКО", "en": "Customer experience violations"},
    "ratings.block.rs_violations": {"ru": "Нарушения РС", "en": "Standards violations"},
    "ratings.cluster": {"ru": "Топ-5", "en": "Top 5"},
    "ratings.violations.total": {"ru": "Всего: {n}", "en": "Total: {n}"},
    "ratings.violations.per": {"ru": "На проверку: {x}", "en": "Per check: {x}"},
    "ratings.top": {"ru": "Выше {x}", "en": "Above {x}"},
    "ratings.bottom": {"ru": "{x} и ниже", "en": "{x} and below"},
    "ratings.block.compare": {
        "ru": "Сравнение девелоперов и стран",
        "en": "Developers and countries compared",
    },
    "ratings.compare.developers": {"ru": "Девелопер", "en": "Developer"},
    "ratings.compare.countries": {"ru": "Страна", "en": "Country"},
    "ratings.compare.units": {"ru": "Пиццерий", "en": "Pizzerias"},
    "ratings.block.top": {"ru": "Top-10 и Bottom-10", "en": "Top 10 and bottom 10"},
    "ratings.block.hard": {"ru": "Хард-нарушения РС и РКО", "en": "Hard violations"},
    "ratings.hard.source": {
        "ru": "Формулировки — дословно из Dodo IS. РКО — фото-проверка заказа.",
        "en": "Wording is verbatim from Dodo IS. RKO is a photo check of an order.",
    },
    "ratings.empty.rs_rko": {
        "ru": "За период нет данных РС и РКО.",
        "en": "No standards or customer experience data for this period.",
    },
    "ratings.empty.hard": {"ru": "Хард-нарушений не найдено.", "en": "No hard violations found."},
    "ratings.col.unit": {"ru": "Пиццерия", "en": "Pizzeria"},
    "ratings.col.violation": {"ru": "Нарушение", "en": "Violation"},
    "ratings.col.amount": {"ru": "Раз", "en": "Times"},
    "ratings.col.scores": {"ru": "Оценки по периодам", "en": "Scores by period"},
    "ratings.col.average": {"ru": "Средняя", "en": "Average"},
    "ratings.filter.country": {"ru": "Страна", "en": "Country"},
    "ratings.filter.all": {"ru": "Все", "en": "All"},
    "ratings.layout.maps": {"ru": "Оценки на картах", "en": "Map ratings"},
    "ratings.layout.aggregators": {"ru": "Оценки в агрегаторах", "en": "Delivery app ratings"},
    "ratings.tile.open": {"ru": "Развернуть", "en": "Expand"},
    "ratings.tile.close": {"ru": "Свернуть", "en": "Collapse"},
    "ratings.more": {"ru": "Показать ещё ({n})", "en": "Show more ({n})"},
    "ratings.tile.none": {"ru": "Данных за период нет", "en": "No data for the period"},
    "ratings.tile.scores": {"ru": "Групп в сводке: {n}", "en": "Groups in the summary: {n}"},
    "ratings.tile.developers": {"ru": "Девелоперов", "en": "Developers"},
    "ratings.tile.countries": {"ru": "Стран", "en": "Countries"},
    "ratings.tile.compare": {"ru": "Лучший РС: {name}, {x}", "en": "Best RS: {name}, {x}"},
    "ratings.tile.violations": {
        "ru": "Нарушений на проверку: РКО {rko}, РС {rs}",
        "en": "Violations per checkup: RKO {rko}, RS {rs}",
    },
    "ratings.tile.best": {"ru": "{kind}, лучшая", "en": "{kind}, best"},
    "ratings.tile.worst": {"ru": "{kind}, худшая", "en": "{kind}, worst"},
    "ratings.tile.top": {"ru": "Лучшая по РС: {name}", "en": "Best by RS: {name}"},
    "ratings.tile.hard": {
        "ru": "Пиццерий с нарушениями: {n}",
        "en": "Pizzerias with violations: {n}",
    },
    "ratings.tile.maps": {"ru": "Средняя по отзывам на картах", "en": "Average of map reviews"},
    "ratings.tile.aggregators": {"ru": "Площадок доставки: {n}", "en": "Delivery apps: {n}"},
    "ratings.maps.hint": {
        "ru": "Средняя по всем отзывам и оценкам пиццерий группы",
        "en": "Average over all reviews and ratings of the group's pizzerias",
    },
    "ratings.maps.reviews": {"ru": "{n} отз.", "en": "{n} reviews"},
    "ratings.agg.points": {"ru": "пиццерий: {n}", "en": "pizzerias: {n}"},
    "ratings.maps.branches_n": {"ru": "филиалов: {n}", "en": "branches: {n}"},
    "ratings.agg.later": {
        "ru": (
            "Агрегаторы собираются с 11.10.2026, раз в сутки: за выбранный период "
            "оценок нет, показаны данные на {date}."
        ),
        "en": (
            "Delivery apps are collected daily since 11.10.2026: no ratings for the "
            "selected period, showing data as of {date}."
        ),
    },
    "ratings.block.risk": {"ru": "Стабильно ниже порога", "en": "Consistently below threshold"},
    "ratings.risk.hint": {
        "ru": "Средняя за {n} последних периода ниже {x}",
        "en": "Average of the last {n} periods below {x}",
    },
    "ratings.empty.rs": {
        "ru": "За период нет данных РС.",
        "en": "No standards data for this period.",
    },
    "ratings.empty.rko": {
        "ru": "За период нет данных РКО.",
        "en": "No customer experience data for this period.",
    },
    "ratings.empty.violations": {"ru": "Нарушений не найдено.", "en": "No violations found."},
    "ratings.empty.top": {
        "ru": "Нет пиццерий выше порога.",
        "en": "No pizzerias above the threshold.",
    },
    "ratings.empty.bottom": {
        "ru": "Нет пиццерий на пороге и ниже.",
        "en": "No pizzerias at or below the threshold.",
    },
    "ratings.empty.risk": {"ru": "В зоне риска никого.", "en": "Nobody is at risk."},
    "ratings.risk.short": {
        "ru": "Недостаточно периодов для оценки: {types}.",
        "en": "Not enough periods to assess: {types}.",
    },
    "ratings.empty.countries": {
        "ru": "В группе нет стран: задайте девелопера стране в «Загрузках».",
        "en": "No countries in this group: assign a developer in Uploads.",
    },
}

_IMPORTS: dict[str, dict[str, str]] = {
    "ratings.imports.hint": {
        "ru": "CSV из Dodo IS, лист «Качество по пиццериям» или снимок рейтинга (JSON), "
        "до {mb} МБ. Формат узнаётся сам.",
        "en": "Dodo IS CSV, the quality-by-pizzeria sheet, or a rating snapshot (JSON), "
        "up to {mb} MB. The format is detected automatically.",
    },
    "ratings.imports.file": {"ru": "Файл", "en": "File"},
    "ratings.imports.submit": {"ru": "Загрузить", "en": "Upload"},
    "ratings.imports.loaded": {
        "ru": "Загружено: {fmt}. Принято {a}, обновлено {u}, пропущено {s}, не сопоставлено {m}.",
        "en": "Uploaded: {fmt}. Added {a}, updated {u}, skipped {s}, unmatched {m}.",
    },
    "ratings.imports.duplicate": {
        "ru": "Этот файл уже загружен {at}. Ничего не изменилось.",
        "en": "This file was already uploaded on {at}. Nothing changed.",
    },
    "ratings.imports.failed": {"ru": "Файл не принят: {reason}", "en": "File rejected: {reason}"},
    "ratings.imports.db_down": {
        "ru": "База не приняла загрузку, ничего не записано. Попробуйте позже.",
        "en": "The database rejected the upload; nothing was saved. Try again later.",
    },
    "ratings.imports.no_file": {"ru": "Выберите файл.", "en": "Choose a file."},
    "ratings.imports.too_big": {
        "ru": "Файл больше {mb} МБ.",
        "en": "The file is larger than {mb} MB.",
    },
    "ratings.chunk": {"ru": "часть {k} из {n}", "en": "part {k} of {n}"},
    "ratings.back": {"ru": "‹ Рейтинги", "en": "‹ Ratings"},
    "ratings.journal": {"ru": "Журнал загрузок", "en": "Upload log"},
    "ratings.journal.empty": {"ru": "Загрузок ещё не было.", "en": "No uploads yet."},
    "ratings.journal.at": {"ru": "Когда", "en": "When"},
    "ratings.journal.actor": {"ru": "Кто", "en": "Who"},
    "ratings.journal.channel": {"ru": "Вход", "en": "Channel"},
    "ratings.journal.format": {"ru": "Формат", "en": "Format"},
    "ratings.journal.outcome": {"ru": "Итог", "en": "Result"},
    "ratings.journal.counts": {
        "ru": "Принято · обновлено · пропущено · не сопоставлено",
        "en": "Added · updated · skipped · unmatched",
    },
    "ratings.journal.note": {"ru": "Примечание", "en": "Note"},
    "ratings.outcome.loaded": {"ru": "загружен", "en": "loaded"},
    "ratings.outcome.duplicate": {"ru": "уже был", "en": "duplicate"},
    "ratings.outcome.failed": {"ru": "не принят", "en": "rejected"},
    "ratings.channel.web": {"ru": "веб", "en": "web"},
    "ratings.channel.mcp": {"ru": "MCP", "en": "MCP"},
    "ratings.channel.seed": {"ru": "сид", "en": "seed"},
    "ratings.channel.sync": {"ru": "таблица", "en": "sheet"},
    "ratings.sheet.title": {"ru": "Таблица контроля", "en": "Control team spreadsheet"},
    "ratings.sheet.hint": {
        "ru": "Рейтинги РС и РКО забираются из общей таблицы сами, раз в {h} ч; загрузка файлом "
        "ниже остаётся запасным путём.",
        "en": "Standards and customer-experience ratings are pulled from the shared spreadsheet "
        "every {h} h; the file upload below stays as a fallback.",
    },
    "ratings.sheet.off": {
        "ru": "Адрес таблицы не задан в настройках сервера: самозабор выключен, данные "
        "загружаются файлами.",
        "en": "The spreadsheet address is not set in the server settings: automatic pull is off, "
        "data is uploaded as files.",
    },
    "ratings.sheet.last": {
        "ru": "Последний заход по таблице: {at}.",
        "en": "Last spreadsheet check: {at}.",
    },
    "ratings.sheet.never": {
        "ru": "Таблицу ещё не забирали: первый заход — в течение минуты после включения.",
        "en": "The spreadsheet has not been pulled yet: the first pull runs within a minute.",
    },
    "ratings.sheet.now": {"ru": "Забрать сейчас", "en": "Pull now"},
    "ratings.sheet.pending": {
        "ru": "Заявка в очереди с {at} ({by}); бот заберёт таблицу в течение минуты.",
        "en": "Request queued since {at} ({by}); the bot pulls the spreadsheet within a minute.",
    },
    "ratings.sheet.queued": {
        "ru": "Заявка принята: бот заберёт таблицу в течение минуты, обновите страницу позже.",
        "en": "Request accepted: the bot pulls the spreadsheet within a minute, reload later.",
    },
    "ratings.sheet.already": {
        "ru": "Заявка уже в очереди — второй раз просить не нужно.",
        "en": "A request is already queued, no need to ask again.",
    },
    "ratings.sheet.db_down": {
        "ru": "База не приняла заявку. Попробуйте позже.",
        "en": "The database did not accept the request. Try again later.",
    },
    "ratings.sheet.failed": {
        "ru": "Не удалось забрать листов: {n} из {m}. Данные остались прежними; причины ниже.",
        "en": "Could not pull {n} of {m} sheets. The data is unchanged; reasons below.",
    },
    "ratings.sheet.unreadable": {
        "ru": "Состояние забора таблицы не прочиталось (база не ответила); попробуйте позже.",
        "en": "The spreadsheet pull status could not be read (database unavailable); try later.",
    },
    "ratings.sheet.col.tab": {"ru": "Лист", "en": "Sheet"},
    "ratings.sheet.col.at": {"ru": "Заход", "en": "Checked"},
    "ratings.sheet.col.result": {"ru": "Итог", "en": "Result"},
    "ratings.sheet.col.reason": {"ru": "Причина", "en": "Reason"},
    "ratings.sheet.outcome.loaded": {"ru": "загружен", "en": "loaded"},
    "ratings.sheet.outcome.unchanged": {"ru": "без изменений", "en": "unchanged"},
    "ratings.sheet.outcome.failed": {"ru": "сбой", "en": "failed"},
    "ratings.sheet.err.closed": {
        "ru": "таблица закрыта: вместо листа пришла страница входа; проверьте доступ по ссылке",
        "en": "the spreadsheet is closed: a sign-in page came back; check link sharing",
    },
    "ratings.sheet.err.http": {
        "ru": "таблица ответила ошибкой; проверьте адрес таблицы и доступ",
        "en": "the spreadsheet answered with an error; check its address and sharing",
    },
    "ratings.sheet.err.network": {
        "ru": "таблица не отвечает; повторим на следующем заходе",
        "en": "the spreadsheet does not answer; retrying on the next pull",
    },
    "ratings.sheet.err.too_big": {
        "ru": "лист больше допустимого размера",
        "en": "the sheet is larger than allowed",
    },
    "ratings.sheet.err.header": {
        "ru": "заголовок листа изменился или лист не тот; подробности — в журнале ниже",
        "en": "the sheet header changed or it is the wrong sheet; details in the journal below",
    },
    "ratings.sheet.err.db": {
        "ru": "база не приняла лист; ничего не записано",
        "en": "the database rejected the sheet; nothing was written",
    },
    "ratings.sheet.err.bad_id": {
        "ru": "адрес таблицы в настройках сервера не похож на адрес",
        "en": "the spreadsheet address in the server settings does not look valid",
    },
    "ratings.sheet.err.unknown": {"ru": "сбой забора", "en": "pull failed"},
    "ratings.issues": {"ru": "Несопоставленные и битые строки", "en": "Unmatched and broken rows"},
    "ratings.issues.empty": {"ru": "Всё сопоставлено.", "en": "Everything is matched."},
    "ratings.issues.row": {"ru": "строка {n}", "en": "row {n}"},
    "ratings.issues.rows": {"ru": "строк: {n}, первая — {first}", "en": "{n} rows, first {first}"},
    "ratings.issue.unit_unmatched": {
        "ru": "пиццерия не сопоставлена",
        "en": "pizzeria not matched",
    },
    "ratings.issue.country_unknown": {"ru": "страна не узнана", "en": "unknown country"},
    "ratings.issue.bad_row": {"ru": "строка не разобрана", "en": "row not parsed"},
    "ratings.issue.unit_id_clash": {
        "ru": "id пиццерии занят другой пиццерией — строки не загружены",
        "en": "the pizzeria id belongs to another pizzeria — rows not loaded",
    },
    "ratings.issue.developer_conflict": {
        "ru": "у страны в файле разные девелоперы",
        "en": "the file gives the country different developers",
    },
    "ratings.developers": {"ru": "Страна → бизнес-девелопер", "en": "Country → business developer"},
    "ratings.developers.save": {"ru": "Сохранить", "en": "Save"},
    "ratings.rules": {"ru": "Хард-нарушения", "en": "Hard violations"},
    "ratings.rules.empty": {"ru": "Правил пока нет.", "en": "No rules yet."},
    "ratings.rules.type": {"ru": "Рейтинг", "en": "Rating"},
    "ratings.rules.match": {"ru": "Совпадение", "en": "Match"},
    "ratings.rules.pattern": {"ru": "Текст нарушения", "en": "Violation text"},
    "ratings.rules.match.text": {"ru": "текст целиком", "en": "exact text"},
    "ratings.rules.match.contains": {"ru": "содержит", "en": "contains"},
    "ratings.rules.add": {"ru": "Добавить правило", "en": "Add rule"},
    "ratings.rules.remove": {"ru": "Убрать", "en": "Remove"},
    "ratings.settings": {"ru": "Пороги", "en": "Thresholds"},
    "ratings.settings.top_threshold": {"ru": "Порог Top/Bottom", "en": "Top/bottom threshold"},
    "ratings.settings.risk_threshold": {"ru": "Порог зоны риска", "en": "Risk threshold"},
    "ratings.settings.risk_periods": {
        "ru": "Периодов в средней для зоны риска",
        "en": "Periods averaged for risk",
    },
    "ratings.settings.save": {"ru": "Сохранить пороги", "en": "Save thresholds"},
    "ratings.saved": {"ru": "Сохранено.", "en": "Saved."},
    "ratings.layout": {"ru": "Компоновка страницы", "en": "Page layout"},
    "ratings.layout.hint": {
        "ru": "Что показывать и в каком порядке — для всех, кто смотрит рейтинги",
        "en": "What to show and in which order — for everyone who views the ratings",
    },
    "ratings.layout.scores": {"ru": "Оценки по странам", "en": "Scores by country"},
    "ratings.layout.violations": {"ru": "Нарушения РКО и РС", "en": "Violations"},
    "ratings.layout.compare": {
        "ru": "Сравнение девелоперов и стран (видит УК)",
        "en": "Developers and countries compared (head office only)",
    },
    "ratings.layout.top": {"ru": "Top и Bottom", "en": "Top and bottom"},
    "ratings.layout.hard": {"ru": "Хард-нарушения", "en": "Hard violations"},
    "ratings.layout.risk": {"ru": "Пиццерии в зоне риска", "en": "Pizzerias at risk"},
    "ratings.maps.provider.2": {"ru": "Google", "en": "Google"},
    "ratings.maps.provider.1": {"ru": "Яндекс", "en": "Yandex"},
    "ratings.maps.unit_title": {
        "ru": "Оценка в Google Картах, отзывов: {n}",
        "en": "Google Maps rating, reviews: {n}",
    },
    "ratings.empty.maps": {
        "ru": "Оценок с карт по этим странам ещё нет.",
        "en": "No map ratings for these countries yet.",
    },
    "ratings.agg.scale.5": {"ru": "из 5", "en": "of 5"},
    "ratings.agg.scale.10": {"ru": "из 10", "en": "of 10"},
    "ratings.agg.scale.100": {"ru": "% довольных", "en": "% positive"},
    "ratings.agg.votes": {"ru": "оценок: {n}", "en": "ratings: {n}"},
    "ratings.agg.as_of": {"ru": "Данные на {date}", "en": "As of {date}"},
    "ratings.agg.failed": {
        "ru": "Не собралось: {names}. Показаны последние удачные данные.",
        "en": "Not collected: {names}. Showing the last successful data.",
    },
    "ratings.agg.failed_one": {
        "ru": "{name}: последний сбор {at} не удался{ok}",
        "en": "{name}: last collection {at} failed{ok}",
    },
    "ratings.agg.last_ok": {"ru": ", последний удачный — {at}", "en": ", last successful — {at}"},
    "ratings.agg.never_ok": {"ru": ", удачных ещё не было", "en": ", never succeeded yet"},
    "ratings.agg.update": {"ru": "Обновить сейчас", "en": "Update now"},
    "ratings.agg.update.hint": {
        "ru": "Не ждать суток: бот соберёт оценки по заявке в течение нескольких минут.",
        "en": "Don't wait a day: the bot collects the ratings on request within a few minutes.",
    },
    "ratings.agg.update.queued": {
        "ru": "Заявка принята: бот соберёт оценки агрегаторов в течение нескольких минут.",
        "en": "Request accepted: the bot will collect the delivery app ratings within minutes.",
    },
    "ratings.agg.update.already": {
        "ru": "Обновление уже в очереди — второй раз просить не нужно.",
        "en": "An update is already queued, no need to ask again.",
    },
    "ratings.agg.update.db_down": {
        "ru": "База не приняла заявку. Попробуйте позже.",
        "en": "The database did not accept the request. Try again later.",
    },
    "ratings.agg.update.pending": {
        "ru": "Обновление в очереди с {at} ({by}); собирает бот, страницу можно открыть позже.",
        "en": "Update queued since {at} ({by}); the bot is collecting it, reload the page later.",
    },
    "ratings.empty.aggregators": {
        "ru": "Оценок из агрегаторов по этим странам ещё нет.",
        "en": "No delivery app ratings for these countries yet.",
    },
    "ratings.agg.name.wolt": {"ru": "Wolt", "en": "Wolt"},
    "ratings.agg.name.glovo": {"ru": "Glovo", "en": "Glovo"},
    "ratings.agg.name.bolt_food": {"ru": "Bolt Food", "en": "Bolt Food"},
    "ratings.agg.name.yandex_eda": {"ru": "Яндекс Еда", "en": "Yandex Eats"},
    "ratings.agg.name.yemeksepeti": {"ru": "Yemeksepeti", "en": "Yemeksepeti"},
    "ratings.agg.name.trendyol_go": {"ru": "Trendyol Go", "en": "Trendyol Go"},
    "ratings.agg.name.pyszne_pl": {"ru": "Pyszne.pl", "en": "Pyszne.pl"},
    "ratings.agg.name.chowdeck": {"ru": "Chowdeck", "en": "Chowdeck"},
    "ratings.agg.name.migros_yemek": {"ru": "Migros Yemek", "en": "Migros Yemek"},
    "ratings.coverage.title": {"ru": "Пиццерии на площадках", "en": "Pizzerias on platforms"},
    "ratings.coverage.open": {"ru": "по пиццериям →", "en": "by pizzeria →"},
    "ratings.coverage.hint": {
        "ru": "На каких картах и агрегаторах есть каждая пиццерия и свежие ли там данные",
        "en": "Which maps and delivery apps list each pizzeria, and whether the data is fresh",
    },
    "ratings.coverage.units": {"ru": "пиццерий: {n}", "en": "pizzerias: {n}"},
    "ratings.coverage.new_count": {
        "ru": "новых за {days} дней: {new}",
        "en": "new in {days} days: {new}",
    },
    "ratings.coverage.gap_count": {
        "ru": "без точки на площадках: {gap}",
        "en": "missing on a platform: {gap}",
    },
    "ratings.coverage.gap_hint": {
        "ru": "Работающие пиццерии, у которых нет точки хотя бы на одном агрегаторе страны",
        "en": "Working pizzerias with no listing on at least one delivery app of their country",
    },
    "ratings.coverage.new": {"ru": "новая", "en": "new"},
    "ratings.coverage.new_title": {
        "ru": "Появилась в публичном API Dodo за последние {days} дней",
        "en": "Appeared in the Dodo public API in the last {days} days",
    },
    "ratings.coverage.stale": {
        "ru": "Данные от {date}, новые не приходят",
        "en": "Data from {date}, no newer data is arriving",
    },
    "ratings.coverage.missing": {"ru": "Нет на площадке", "en": "Not on the platform"},
    "ratings.coverage.unrated": {"ru": "Оценок пока нет", "en": "No ratings yet"},
    "ratings.coverage.empty": {
        "ru": "Реестр пиццерий пока пуст: он наполнится при ближайшем ежедневном сборе.",
        "en": "The pizzeria registry is empty: it fills at the next daily collection.",
    },
    "ratings.coverage.none": {
        "ru": "В этой стране нет работающих пиццерий.",
        "en": "No working pizzerias in this country.",
    },
    "ratings.coverage.db_down": {
        "ru": "База не ответила: охват площадок сейчас не показать.",
        "en": "The database did not respond: platform coverage cannot be shown now.",
    },
    "ratings.coverage.link.summary": {"ru": "привязать", "en": "link"},
    "ratings.coverage.link.label.glovo": {
        "ru": "Страница магазина на glovoapp.com",
        "en": "Store page on glovoapp.com",
    },
    "ratings.coverage.link.label.migros_yemek": {
        "ru": "Страница магазина на migros.com.tr/yemek",
        "en": "Store page on migros.com.tr/yemek",
    },
    "ratings.coverage.link.submit": {"ru": "Привязать", "en": "Link"},
    "ratings.coverage.link.ok": {
        "ru": "Привязано к {platform}: {name}.",
        "en": "Linked to {platform}: {name}.",
    },
    "ratings.coverage.link.failed": {"ru": "Не привязано.", "en": "Not linked."},
    "ratings.coverage.link.bad_url": {
        "ru": (
            "Не привязано: нужна ссылка вида https://glovoapp.com/en/ro/bucharest/stores/"
            "название-магазина."
        ),
        "en": (
            "Not linked: expected a link like https://glovoapp.com/en/ro/bucharest/stores/"
            "store-name."
        ),
    },
    "ratings.coverage.link.bad_url_migros": {
        "ru": "Не привязано: нужна ссылка вида https://www.migros.com.tr/yemek/dodo-pizza-….",
        "en": "Not linked: expected a link like https://www.migros.com.tr/yemek/dodo-pizza-….",
    },
    "ratings.coverage.link.migros_failed": {
        "ru": (
            "Не привязано: Migros не ответил через домашний сервер — проверьте, не спит ли "
            "он, и повторите."
        ),
        "en": (
            "Not linked: Migros did not answer through the home server — check that it is "
            "awake and try again."
        ),
    },
    "ratings.coverage.link.unknown_unit": {
        "ru": "Не привязано: пиццерии нет в реестре.",
        "en": "Not linked: the pizzeria is not in the registry.",
    },
    "ratings.coverage.link.country_mismatch": {
        "ru": "Не привязано: страна в ссылке не совпадает со страной пиццерии.",
        "en": "Not linked: the country in the link differs from the pizzeria's country.",
    },
    "ratings.coverage.link.page_failed": {
        "ru": "Не привязано: страница Glovo не открылась, попробуйте позже.",
        "en": "Not linked: the Glovo page did not open, try again later.",
    },
    "ratings.coverage.link.no_store": {
        "ru": "Не привязано: на странице не нашлись данные магазина Dodo Pizza.",
        "en": "Not linked: no Dodo Pizza store data found on the page.",
    },
    "ratings.coverage.link.glovo_failed": {
        "ru": "Не привязано: Glovo не отдал точку для координат пиццерии.",
        "en": "Not linked: Glovo returned no point for the pizzeria's coordinates.",
    },
    "ratings.coverage.link.taken": {
        "ru": "Не привязано: эта точка площадки уже привязана к другой пиццерии.",
        "en": "Not linked: this platform point is already linked to another pizzeria.",
    },
    "ratings.layout.up": {"ru": "{name} — выше", "en": "Move {name} up"},
    "ratings.layout.down": {"ru": "{name} — ниже", "en": "Move {name} down"},
    "ratings.layout.save": {"ru": "Сохранить компоновку", "en": "Save layout"},
    "ratings.refused": {"ru": "Не сохранено: {reason}", "en": "Not saved: {reason}"},
}

#: Форматы файлов — по коду формата (`src.ratings.model.FORMATS`).
_FORMATS: dict[str, dict[str, str]] = {
    "ratings.format.rko-violations": {"ru": "нарушения РКО", "en": "customer exp. violations"},
    "ratings.format.rko-evaluations": {"ru": "оценки РКО", "en": "customer exp. evaluations"},
    "ratings.format.rs-checkups": {"ru": "проверки РС", "en": "standards checks"},
    "ratings.format.snapshot": {"ru": "снимок рейтинга", "en": "rating snapshot"},
    "ratings.format.sheet-scores": {"ru": "лист оценок", "en": "scores sheet"},
    "ratings.format.base-scores": {"ru": "оценки с флагами", "en": "scores with flags"},
    "ratings.format.base-collection": {"ru": "собираемость РКО", "en": "customer exp. collection"},
    "ratings.format.base-rko-violations": {
        "ru": "нарушения РКО (таблица)",
        "en": "customer exp. violations (sheet)",
    },
    "ratings.format.base-rs-violations": {
        "ru": "нарушения РС (таблица)",
        "en": "standards violations (sheet)",
    },
}

#: Отказы разбора — по `RatingsFormatError.code`; параметры — из `exc.params`.
_ERRORS: dict[str, dict[str, str]] = {
    "ratings.error.not_utf8": {
        "ru": "файл не в UTF-8. Выгрузите CSV заново из Dodo IS или сохраните как «CSV UTF-8».",
        "en": "the file is not UTF-8. Export the CSV from Dodo IS again or save it as CSV UTF-8.",
    },
    "ratings.error.empty": {"ru": "файл пустой.", "en": "the file is empty."},
    "ratings.error.unknown_format": {
        "ru": "формат не узнан: это не выгрузка Dodo IS, не лист оценок и не снимок.",
        "en": "unknown format: not a Dodo IS export, a scores sheet or a snapshot.",
    },
    "ratings.error.missing_columns": {
        "ru": "в файле {format} нет колонок: {columns}.",
        "en": "the {format} file lacks columns: {columns}.",
    },
    "ratings.error.not_sheet": {
        "ru": "это не лист «Качество по пиццериям».",
        "en": "this is not the quality-by-pizzeria sheet.",
    },
    "ratings.error.bad_period": {
        "ru": "дата периода в заголовке листа не существует.",
        "en": "a period date in the sheet header does not exist.",
    },
    "ratings.error.bad_csv": {
        "ru": "CSV повреждён и не читается. Выгрузите его заново из Dodo IS.",
        "en": "the CSV is damaged and unreadable. Export it from Dodo IS again.",
    },
    "ratings.error.too_many_rows": {
        "ru": "в файле больше {limit} строк. Разделите выгрузку на части и загрузите по очереди.",
        "en": "the file has over {limit} rows. Split the export and upload it in parts.",
    },
    "ratings.error.bad_json": {
        "ru": "снимок не читается как JSON.",
        "en": "the snapshot is not valid JSON.",
    },
    "ratings.error.bad_version": {
        "ru": "снимок не той версии: ожидается {expected}.",
        "en": "wrong snapshot version: {expected} expected.",
    },
    "ratings.error.bad_snapshot": {
        "ru": "снимок повреждён (часть: {part}).",
        "en": "the snapshot is damaged (part: {part}).",
    },
}

#: Отказы правки справочников — по `RatingsEditError.code` (`src/db/ratings_read.py`).
_REFUSALS: dict[str, dict[str, str]] = {
    "ratings.refused.developer_invalid": {
        "ru": "имя девелопера — до 120 знаков.",
        "en": "the developer name must be up to 120 characters.",
    },
    "ratings.refused.rule_invalid": {
        "ru": "такое правило уже есть или оно пустое.",
        "en": "this rule already exists or is empty.",
    },
    "ratings.refused.rule_kind_invalid": {
        "ru": "тип рейтинга — РС или РКО; совпадение — целиком или «содержит».",
        "en": "the rating must be standards or customer experience; match exact or contains.",
    },
    "ratings.refused.rule_kept": {"ru": "правило не удалилось.", "en": "the rule was not removed."},
    "ratings.refused.setting_invalid": {
        "ru": "порог — от 0 до 100; число периодов — целое от 2 до 12.",
        "en": "a threshold is 0 to 100; the number of periods is a whole number from 2 to 12.",
    },
    "ratings.refused.setting_unknown": {
        "ru": "настройки «{key}» нет.",
        "en": "there is no setting “{key}”.",
    },
    "ratings.refused.db_failed": {
        "ru": "база отказала, ничего не записано. Попробуйте позже.",
        "en": "the database refused; nothing was saved. Try again later.",
    },
}

RATINGS_TEXTS: dict[str, dict[str, str]] = {
    **_SCREEN,
    **_IMPORTS,
    **_FORMATS,
    **_ERRORS,
    **_REFUSALS,
}
