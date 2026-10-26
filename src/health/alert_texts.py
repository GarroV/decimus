"""Тексты оповещений о подключениях (D641): ru — для владельца, en — запасной.

Лежат здесь, а не в `src/web/texts_*.py`, потому что их читает бот, а бот и веб друг друга
не импортируют. Только слова: кодов причин (`health.reason.*`, `rejected`, `no_units`) в
сообщении нет. Ключи причин здесь — те же, что у плиток, чтобы экран и сообщение говорили
об одном одинаково.
"""

from __future__ import annotations

from typing import Final

DEFAULT_LANG: Final = "ru"

ALERT_TEXTS: dict[str, dict[str, str]] = {
    # ── Рамка сообщения: {subject} — «Dodo IS, Сербия» или «Агрегаторы» ──
    "alert.red": {"ru": "🔴 Decimus · {subject}: {body}", "en": "🔴 Decimus · {subject}: {body}"},
    "alert.yellow": {
        "ru": "🟡 Decimus · {subject}: {body}",
        "en": "🟡 Decimus · {subject}: {body}",
    },
    "alert.done": {
        "ru": "🟢 Decimus · {subject}: снова работает.",
        "en": "🟢 Decimus · {subject}: working again.",
    },
    "alert.dodois_tail": {
        "ru": " Администрирование → Dodo IS: {url}",
        "en": " Administration → Dodo IS: {url}",
    },
    "alert.dodois_tail_nourl": {
        "ru": " Администрирование → Dodo IS.",
        "en": " Administration → Dodo IS.",
    },
    "alert.subject.dodois": {"ru": "Dodo IS, {country}", "en": "Dodo IS, {country}"},
    # ── Что сказать по причине (ключ — причина плитки без префикса `health.reason.`) ──
    "alert.dodois.dodois_expired": {
        "ru": "вход не работает — вход истёк, продление отказано, нужна новая ссылка.",
        "en": "login is not working — it expired, renewal was refused, a new link is needed.",
    },
    "alert.dodois.dodois_failed": {
        "ru": "вход не работает — сбой связи с Dodo IS при последней проверке.",
        "en": "login is not working — the connection to Dodo IS failed on the last check.",
    },
    "alert.dodois.dodois_partial": {
        "ru": "вход работает не полностью — открыто {open} из {total} пиццерий.",
        "en": "login only partly works — {open} of {total} pizzerias open.",
    },
    "alert.dodois.stale": {
        "ru": "вход давно не проверялся — проверьте, жив ли бот.",
        "en": "login has not been checked for a while — make sure the bot is running.",
    },
    "alert.load.late": {
        "ru": "сбор не пришёл в срок, последний удачный {at}.",
        "en": "the collection did not arrive on time, last successful {at}.",
    },
    "alert.load.stopped": {
        "ru": "сбор не пришёл в срок и давно не запускался, последний удачный {at}.",
        "en": "the collection did not arrive on time and has not run for a long time, "
        "last successful {at}.",
    },
    "alert.load.failed": {
        "ru": "сбор завершился ошибкой, последний заход {at}.",
        "en": "the collection ended with an error, last run {at}.",
    },
    "alert.probe.rejected": {"ru": "ключ не принят.", "en": "the key was rejected."},
    "alert.probe.unreachable": {"ru": "не отвечает.", "en": "not responding."},
    "alert.probe.default": {"ru": "не работает.", "en": "not working."},
    # ── Названия подключений ──
    "alert.conn.openai": {"ru": "OpenAI (распознавание)", "en": "OpenAI (recognition)"},
    "alert.conn.telegram": {"ru": "Бот в Telegram", "en": "Telegram bot"},
    "alert.conn.storage": {"ru": "Хранилище кадров", "en": "Photo storage"},
    "alert.conn.ispring": {"ru": "iSpring (ключ)", "en": "iSpring (key)"},
    "alert.conn.aggregators": {"ru": "Агрегаторы", "en": "Aggregators"},
    "alert.conn.maps": {"ru": "Карты (Pointer)", "en": "Maps (Pointer)"},
    "alert.conn.sheet": {"ru": "Таблица контроля", "en": "Control spreadsheet"},
    "alert.conn.learning": {"ru": "Обучение (iSpring)", "en": "Training (iSpring)"},
}


def text(key: str, lang: str = DEFAULT_LANG, **params: object) -> str:
    """Текст по ключу и языку; чужой язык — русский; чужой ключ — `KeyError`."""
    entry = ALERT_TEXTS[key]
    return entry.get(lang, entry[DEFAULT_LANG]).format(**params)
