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
    "cov.detail.share": {"ru": "{name}, {percent}%", "en": "{name}, {percent}%"},
    "cov.detail.age": {"ru": "{name}, {days} дн", "en": "{name}, {days} d"},
    # ── Источники ──
    "cov.src.rs": {"ru": "Рейтинг стандартов", "en": "Standards rating"},
    "cov.src.rko": {"ru": "Рейтинг контроля", "en": "Control rating"},
    "cov.src.kr": {"ru": "Клиентские оценки", "en": "Customer ratings"},
    "cov.src.maps_google": {"ru": "Google Карты", "en": "Google Maps"},
    "cov.src.maps_yandex": {"ru": "Яндекс Карты", "en": "Yandex Maps"},
}

#: Названия площадок — бренды, одинаковы на обоих языках.
AGGREGATOR_NAMES: Final = {
    "wolt": "Wolt", "bolt_food": "Bolt Food", "glovo": "Glovo", "chowdeck": "Chowdeck",
    "trendyol_go": "Trendyol Go", "yemeksepeti": "Yemeksepeti", "pyszne_pl": "Pyszne.pl",
    "yandex_eda": "Yandex Eda", "migros_yemek": "Migros Yemek",
}  # fmt: skip


def text(key: str, lang: str = DEFAULT_LANG, **params: object) -> str:
    """Текст по ключу и языку; чужой язык — русский; чужой ключ — `KeyError`."""
    entry = COVERAGE_TEXTS[key]
    return entry.get(lang, entry[DEFAULT_LANG]).format(**params)


def source_name(source: str, lang: str = DEFAULT_LANG) -> str:
    """Название источника словами; незнакомая площадка — её код как есть."""
    key = f"cov.src.{source}"
    if key in COVERAGE_TEXTS:
        return text(key, lang)
    bare = source.removeprefix("agg_")
    return AGGREGATOR_NAMES.get(bare, bare)
