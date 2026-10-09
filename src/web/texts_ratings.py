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
    "ratings.period.month": {"ru": "Месяц", "en": "Month"},
    "ratings.period.quarter": {"ru": "Квартал", "en": "Quarter"},
    "ratings.period.rating": {"ru": "Период рейтинга", "en": "Rating period"},
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
    "ratings.sort": {"ru": "Порядок", "en": "Order"},
    "ratings.sort.name": {"ru": "по алфавиту", "en": "by name"},
    "ratings.sort.rs": {"ru": "слабые по РС", "en": "weakest standards"},
    "ratings.sort.rko": {"ru": "слабые по РКО", "en": "weakest customer exp."},
    "ratings.cal.prev": {"ru": "Предыдущий период", "en": "Previous period"},
    "ratings.cal.next": {"ru": "Следующий период", "en": "Next period"},
    "ratings.show": {"ru": "Показать", "en": "Show"},
    "ratings.loaded": {"ru": "{fmt}: {at}", "en": "{fmt}: {at}"},
    "ratings.loaded.title": {"ru": "Последняя загрузка", "en": "Last upload"},
    "ratings.loaded.none": {"ru": "Загрузок ещё не было.", "en": "Nothing has been uploaded yet."},
    "ratings.manage": {"ru": "Загрузки и справочники", "en": "Uploads and settings"},
    "ratings.block.scores": {
        "ru": "Средний РС и РКО по странам",
        "en": "Average standards and customer experience by country",
    },
    "ratings.col.country": {"ru": "Страна", "en": "Country"},
    "ratings.col.delta": {"ru": "Δ к {prev}", "en": "Δ vs {prev}"},
    "ratings.total": {"ru": "Итого", "en": "Total"},
    "ratings.block.rko_violations": {"ru": "Нарушения РКО", "en": "Customer experience violations"},
    "ratings.block.rs_violations": {"ru": "Нарушения РС", "en": "Standards violations"},
    "ratings.cluster": {"ru": "Топ-5 по кластеру", "en": "Top 5 in the cluster"},
    "ratings.by_country": {"ru": "По каждой стране", "en": "By country"},
    "ratings.violations.total": {"ru": "Всего: {n}", "en": "Total: {n}"},
    "ratings.violations.per": {"ru": "На проверку: {x}", "en": "Per check: {x}"},
    "ratings.block.rs_top": {
        "ru": "По проверкам РС: Top-10 и Bottom-10",
        "en": "Standards: top 10 and bottom 10",
    },
    "ratings.block.rko_top": {
        "ru": "По проверкам РКО: Top-10 и Bottom-10",
        "en": "Customer experience: top 10 and bottom 10",
    },
    "ratings.top": {"ru": "Выше {x}", "en": "Above {x}"},
    "ratings.bottom": {"ru": "{x} и ниже", "en": "{x} and below"},
    "ratings.block.rs_hard": {"ru": "Хард-нарушения РС", "en": "Standards: hard violations"},
    "ratings.block.rko_hard": {
        "ru": "Хард-нарушения РКО",
        "en": "Customer experience: hard violations",
    },
    "ratings.block.risk": {"ru": "Пиццерии в зоне риска", "en": "Pizzerias at risk"},
    "ratings.risk.hint": {
        "ru": "{n} последних периода подряд ниже {x}",
        "en": "Last {n} periods in a row below {x}",
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
    "ratings.imports.title": {"ru": "Загрузки рейтингов", "en": "Rating uploads"},
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
    "ratings.issues": {"ru": "Несопоставленные и битые строки", "en": "Unmatched and broken rows"},
    "ratings.issues.empty": {"ru": "Всё сопоставлено.", "en": "Everything is matched."},
    "ratings.issues.row": {"ru": "строка {n}", "en": "row {n}"},
    "ratings.issue.unit_unmatched": {
        "ru": "пиццерия не сопоставлена",
        "en": "pizzeria not matched",
    },
    "ratings.issue.country_unknown": {"ru": "страна не узнана", "en": "unknown country"},
    "ratings.issue.bad_row": {"ru": "строка не разобрана", "en": "row not parsed"},
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
        "ru": "Периодов подряд для зоны риска",
        "en": "Periods in a row for risk",
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
    "ratings.layout.top": {"ru": "Top и Bottom", "en": "Top and bottom"},
    "ratings.layout.hard": {"ru": "Хард-нарушения", "en": "Hard violations"},
    "ratings.layout.risk": {"ru": "Пиццерии в зоне риска", "en": "Pizzerias at risk"},
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
