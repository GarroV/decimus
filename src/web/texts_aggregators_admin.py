"""Тексты административного охвата агрегаторов (#1391)."""

AGGREGATORS_ADMIN_TEXTS: dict[str, dict[str, str]] = {
    "aggadmin.settings": {
        "ru": "Настройки площадок и привязки",
        "en": "Platform settings and links",
    },
    "aggadmin.partial": {"ru": "Собрано частично", "en": "Partially collected"},
    "aggadmin.errorDetails": {
        "ru": "Ошибка сбора; подробности в закрытом журнале",
        "en": "Collection error; details in the private log",
    },
    "administration.tab.aggregators": {"ru": "Агрегаторы", "en": "Aggregators"},
    "aggadmin.sub": {
        "ru": (
            "Полнота по работающим пиццериям. Оценки старше 7 дней устарели; журнал "
            "сборщика общий для всех стран площадки."
        ),
        "en": (
            "Coverage of working pizzerias. Scores older than 7 days are stale; "
            "collection logs cover all platform countries."
        ),
    },
    "aggadmin.failed": {
        "ru": "Данные охвата не прочитались. Обновите страницу.",
        "en": "Coverage could not be read. Reload the page.",
    },
    "aggadmin.tone.green": {"ru": "Полно и актуально", "en": "Complete and fresh"},
    "aggadmin.tone.yellow": {"ru": "Неполно или устарело", "en": "Incomplete or stale"},
    "aggadmin.info": {"ru": "К сведению", "en": "For information"},
    "aggadmin.info.note": {
        "ru": (
            "Привязаны к площадке, но оценки пока нет (мало отзывов) — "
            "это норма, делать ничего не надо."
        ),
        "en": (
            "Linked to the platform but not rated yet (too few reviews): normal, nothing to do."
        ),
    },
    "aggadmin.tone.red": {"ru": "Сбой общего сборщика", "en": "Global collection failed"},
    "aggadmin.tone.grey": {"ru": "Нет ожидаемого охвата", "en": "No expected coverage"},
    "aggadmin.working": {"ru": "Работающих пиццерий: {n}", "en": "Working pizzerias: {n}"},
    "aggadmin.noUnits": {
        "ru": "В реестре нет работающих пиццерий этой страны; полноту оценить нельзя.",
        "en": (
            "No working pizzerias in the registry for this country; completeness "
            "cannot be assessed."
        ),
    },
    "aggadmin.noPlatforms": {
        "ru": "В стране нет ожидаемых площадок агрегаторов. Это не сбой сбора.",
        "en": (
            "No aggregator platforms are expected in this country. This is not a "
            "collection failure."
        ),
    },
    "aggadmin.expected": {"ru": "Ожидается пиццерий", "en": "Expected pizzerias"},
    "aggadmin.linked": {"ru": "Привязано", "en": "Linked"},
    "aggadmin.scored": {"ru": "С оценкой", "en": "Scored"},
    "aggadmin.fresh": {"ru": "Со свежей оценкой", "en": "Fresh scores"},
    "aggadmin.stale": {"ru": "С устаревшей оценкой", "en": "Stale scores"},
    "aggadmin.unrated": {"ru": "Привязано без оценки", "en": "Linked without scores"},
    "aggadmin.missing": {"ru": "Нет привязки к площадке", "en": "Missing platform links"},
    "aggadmin.unmatched": {"ru": "Непривязанных точек площадки", "en": "Unmatched platform points"},
    "aggadmin.excluded": {
        "ru": "Исключено вручную (не пиццерия)",
        "en": "Manually excluded (not a pizzeria)",
    },
    "aggadmin.latest": {"ru": "Последняя дата оценки", "en": "Latest score date"},
    "aggadmin.lastSuccess": {
        "ru": "Последний успешный сбор (все страны)",
        "en": "Last successful collection (all countries)",
    },
    "aggadmin.lastAttempt": {
        "ru": "Последняя попытка (все страны)",
        "en": "Last attempt (all countries)",
    },
    "aggadmin.collection": {"ru": "Исход общего сборщика", "en": "Global collection result"},
    "aggadmin.never": {"ru": "Сборов ещё не было", "en": "No collection recorded"},
    "aggadmin.ok": {"ru": "Успешно", "en": "Succeeded"},
    "aggadmin.error": {"ru": "Сбой", "en": "Failed"},
    "aggadmin.global": {
        "ru": (
            "Время и ошибка относятся ко всему сборщику площадки, а не к отдельной "
            "стране. Исключённые точки не входят в непривязанные."
        ),
        "en": (
            "Times and errors refer to the global platform collector, not this "
            "country alone. Excluded points do not count as unmatched."
        ),
    },
    "aggadmin.gaps": {"ru": "Что требует внимания", "en": "Needs attention"},
    "aggadmin.gap.missing": {"ru": "нет привязки", "en": "missing link"},
    "aggadmin.gap.unrated": {"ru": "нет оценки", "en": "no score"},
    "aggadmin.gap.stale": {"ru": "оценка устарела", "en": "stale score"},
    "aggadmin.openRatings": {
        "ru": "Пиццерии и привязки на площадках",
        "en": "Pizzerias and platform links",
    },
    "aggadmin.gap.candidate": {
        "ru": "кандидат рядом не привязан",
        "en": "unlinked candidate nearby",
    },
    "aggadmin.gap.not_listed": {"ru": "нет на площадке", "en": "not on the platform"},
    "aggadmin.candidate.at": {"ru": "{m} м", "en": "{m} m"},
    "aggadmin.candidate.unnamed": {"ru": "без названия", "en": "unnamed"},
    "aggadmin.action.pin": {"ru": "Привязать", "en": "Link"},
    "aggadmin.action.unpin": {"ru": "Отвязать", "en": "Unlink"},
    "aggadmin.action.absent": {"ru": "Нет на площадке", "en": "Not on the platform"},
    "aggadmin.action.present": {"ru": "Снять отметку", "en": "Clear the mark"},
    "aggadmin.action.failed": {
        "ru": "Не получилось: данные не записались. Обновите страницу и повторите.",
        "en": "Could not save. Reload the page and try again.",
    },
    "aggadmin.info.notListed": {
        "ru": (
            "Нет на площадке: у пиццерии искали по её координатам и ничего не нашли, "
            "либо это отмечено вручную. Делать ничего не надо."
        ),
        "en": (
            "Not on the platform: searched at the pizzeria's coordinates and nothing "
            "was found, or marked by hand. Nothing to do."
        ),
    },
    "aggadmin.info.marked": {"ru": "отмечено вручную", "en": "marked by hand"},
    "aggadmin.pinned": {"ru": "Закреплённые привязки", "en": "Pinned links"},
    "aggadmin.pinned.note": {
        "ru": "Ночной сбор их не отменяет, даже если точка далеко от пиццерии.",
        "en": "The nightly run does not undo them, even if the listing is far from the pizzeria.",
    },
}
