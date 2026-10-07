"""Тексты мини-аппа обхода (#418) — сливаются в общий каталог `texts.TEXTS`.

Экран рисует скрипт, но строки живут здесь, а не в `walk.js`: сервер отдаёт
их вместе с данными на языке проверки. Так язык остаётся параметром, а третий
язык добавляется строками каталога, а не правкой скрипта.

Числа — после двоеточия («Замечаний: 3»), а не перед существительным: так
русская форма не зависит от числа, и склонение не нужно ни на одном языке.
"""

from __future__ import annotations

WALK_TEXTS: dict[str, dict[str, str]] = {
    "walk.title": {"ru": "Обход точки", "en": "Walk-through"},
    "walk.left": {"ru": "Осталось осмотреть", "en": "Still to check"},
    "walk.progress": {
        "ru": "Осмотрено зон: {done} из {total}",
        "en": "Zones checked: {done} of {total}",
    },
    "walk.all_done": {"ru": "Все зоны осмотрены", "en": "All zones checked"},
    "walk.how": {
        "ru": "Осмотрели зону — отметьте её. Нарушения записывайте как обычно: фото с "
        "комментарием в чат.",
        "en": "Checked a zone — mark it. Record issues as usual: a photo with a comment "
        "in the chat.",
    },
    "walk.prev.title": {"ru": "В прошлый раз, {date}", "en": "Last time, {date}"},
    "walk.prev.summary": {
        "ru": "Замечаний: {count}. Повтор считается вдвое — посмотрите каждое.",
        "en": "Issues: {count}. A repeat counts double — look at each one.",
    },
    "walk.prev.left": {"ru": "Ещё не перепроверено: {count}", "en": "Not rechecked yet: {count}"},
    "walk.prev.clean": {
        "ru": "Прошлая проверка прошла без замечаний.",
        "en": "The previous inspection had no issues.",
    },
    "walk.prev.none": {
        "ru": "Это первая проверка пиццерии — сравнивать не с чем.",
        "en": "This is the pizzeria's first inspection — nothing to compare with.",
    },
    "walk.prev.unavailable": {
        "ru": "История сейчас недоступна, подсказок о прошлой проверке не будет.",
        "en": "History is unavailable right now, so there are no hints from last time.",
    },
    "walk.zone.mark": {"ru": "Зона осмотрена", "en": "Zone checked"},
    "walk.zone.unmark": {"ru": "Вернуть в неосмотренные", "en": "Mark as not checked"},
    "walk.zone.auto": {
        "ru": "Здесь уже есть записи — зона засчитана.",
        "en": "There are records here already — the zone counts as checked.",
    },
    "walk.zone.now": {"ru": "Записано сейчас", "en": "Recorded now"},
    "walk.zone.before": {"ru": "Было в прошлый раз", "en": "Found last time"},
    "walk.zone.nothing": {"ru": "Пока ничего не записано.", "en": "Nothing recorded yet."},
    "walk.count.now": {"ru": "сейчас: {count}", "en": "now: {count}"},
    "walk.count.before": {"ru": "было: {count}", "en": "last time: {count}"},
    "walk.item.again": {"ru": "Записано снова", "en": "Recorded again"},
    "walk.item.fixed": {"ru": "Исправлено", "en": "Fixed"},
    "walk.item.hint": {
        "ru": "Не исправлено — сфотографируйте и отправьте в чат.",
        "en": "Not fixed — take a photo and send it to the chat.",
    },
    "walk.none.title": {"ru": "Проверка не начата", "en": "No inspection in progress"},
    "walk.none.text": {
        "ru": "Начните проверку в чате с ботом — кнопка «Новая проверка». Обход появится "
        "здесь сам.",
        "en": "Start an inspection in the chat with the bot — the “New inspection” button. "
        "The walk-through will appear here by itself.",
    },
    "walk.back": {"ru": "Вернуться в чат", "en": "Back to the chat"},
    "walk.error": {
        "ru": "Обход не загрузился. Закройте окно и откройте снова.",
        "en": "The walk-through did not load. Close the window and open it again.",
    },
    "walk.loading": {"ru": "Загружаю обход…", "en": "Loading the walk-through…"},
}
