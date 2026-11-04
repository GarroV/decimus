"""Тексты оповещений о дырах в данных рейтингов (D704, D706): ru — для владельца, en — запасной.

Как и `alert_texts.py`, лежат здесь, а не в `src/web/texts_*.py`: их читает бот. Только слова:
ни кодов источников, ни кодов причин, ни кодов стран в сообщении нет.
"""

from __future__ import annotations

from typing import Final

DEFAULT_LANG: Final = "ru"

COVERAGE_TEXTS: dict[str, dict[str, str]] = {
    # ── Рамка: {lines} — строки «источник: причина — страны» ──
    "cov.red": {
        "ru": "🔴 Decimus · Данные рейтингов: в источниках есть пустоты.\n{lines}",
        "en": "🔴 Decimus · Ratings data: some sources have gaps.\n{lines}",
    },
    "cov.yellow": {
        "ru": "🟡 Decimus · Данные рейтингов: источники заполнены не полностью.\n{lines}",
        "en": "🟡 Decimus · Ratings data: some sources are incomplete.\n{lines}",
    },
    "cov.done": {
        "ru": "🟢 Decimus · Данные рейтингов: пустоты закрылись.\n{lines}",
        "en": "🟢 Decimus · Ratings data: gaps closed.\n{lines}",
    },
    "cov.tail": {
        "ru": "Администрирование → Подключения: {url}",
        "en": "Administration → Connections: {url}",
    },
    "cov.line": {
        "ru": "• {source}: {reason} — {countries}.",
        "en": "• {source}: {reason} — {countries}.",
    },
    "cov.line_done": {"ru": "• {source}: {countries}.", "en": "• {source}: {countries}."},
    # ── Причины ──
    "cov.reason.empty": {"ru": "данных нет совсем", "en": "no data at all"},
    "cov.reason.not_connected": {
        "ru": "не подключён вход Dodo IS",
        "en": "Dodo IS login is not connected",
    },
    "cov.reason.stale": {"ru": "данные устарели", "en": "data is out of date"},
    "cov.reason.missing_current": {
        "ru": "нет данных за текущий месяц",
        "en": "no data for the current month",
    },
    "cov.reason.missing_previous": {
        "ru": "нет данных за прошлый месяц",
        "en": "no data for the previous month",
    },
    "cov.reason.low": {
        "ru": "заполнено меньше {percent}% пиццерий",
        "en": "fewer than {percent}% of pizzerias filled",
    },
    # ── Подробность у страны ──
    "cov.detail.share": {"ru": "{name} {percent}%", "en": "{name} {percent}%"},
    "cov.detail.age": {"ru": "{name} ({age})", "en": "{name} ({age})"},
    # ── Источники ──
    "cov.src.rs": {"ru": "Рейтинг стандартов", "en": "Standards rating"},
    "cov.src.rko": {"ru": "Рейтинг контроля", "en": "Control rating"},
    "cov.src.kr": {"ru": "Клиентские оценки", "en": "Customer ratings"},
    "cov.src.maps_google": {"ru": "Google Карты", "en": "Google Maps"},
    "cov.src.maps_yandex": {"ru": "Яндекс Карты", "en": "Yandex Maps"},
}

#: Названия площадок: латиницей — как их пишет сама площадка; по-русски — где есть устоявшееся.
AGGREGATOR_NAMES: Final[dict[str, dict[str, str]]] = {
    "wolt": {"ru": "Wolt", "en": "Wolt"},
    "bolt_food": {"ru": "Bolt Food", "en": "Bolt Food"},
    "glovo": {"ru": "Glovo", "en": "Glovo"},
    "chowdeck": {"ru": "Chowdeck", "en": "Chowdeck"},
    "trendyol_go": {"ru": "Trendyol Go", "en": "Trendyol Go"},
    "yemeksepeti": {"ru": "Yemeksepeti", "en": "Yemeksepeti"},
    "pyszne_pl": {"ru": "Pyszne.pl", "en": "Pyszne.pl"},
    "yandex_eda": {"ru": "Яндекс Еда", "en": "Yandex Eda"},
    "migros_yemek": {"ru": "Migros Yemek", "en": "Migros Yemek"},
}


def aggregator_name(key: str, lang: str = DEFAULT_LANG) -> str:
    """Название площадки; незнакомая — её код как есть."""
    names = AGGREGATOR_NAMES.get(key)
    return key if names is None else names.get(lang, names[DEFAULT_LANG])


def days(n: int, lang: str = DEFAULT_LANG) -> str:
    """«1 день», «2 дня», «5 дней», «21 день»; по-английски «1 day», «7 days»."""
    if lang != "ru":
        return f"{n} day" if n == 1 else f"{n} days"
    if n % 100 in range(11, 15):
        word = "дней"
    elif n % 10 == 1:
        word = "день"
    elif n % 10 in (2, 3, 4):
        word = "дня"
    else:
        word = "дней"
    return f"{n} {word}"


def text(key: str, lang: str = DEFAULT_LANG, **params: object) -> str:
    """Текст по ключу и языку; чужой язык — русский; чужой ключ — `KeyError`."""
    entry = COVERAGE_TEXTS[key]
    return entry.get(lang, entry[DEFAULT_LANG]).format(**params)


def source_name(source: str, lang: str = DEFAULT_LANG) -> str:
    """Название источника словами; незнакомая площадка — её код как есть."""
    key = f"cov.src.{source}"
    if key in COVERAGE_TEXTS:
        return text(key, lang)
    return aggregator_name(source.removeprefix("agg_"), lang)
