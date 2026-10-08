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
        "ru": "Откройте зону и запишите, что нашли: фото, пункт, класс. Зона без нарушений — "
        "отметьте её осмотренной. В чат тоже можно писать: всё попадёт в одну проверку.",
        "en": "Open a zone and record what you find: photo, item, class. A zone with no "
        "issues — mark it as checked. The chat still works: everything goes into one "
        "inspection.",
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
        "ru": "Не исправлено — запишите повтор: вычет за него вдвое.",
        "en": "Not fixed — record it as a repeat: it costs double.",
    },
    "walk.item.record_repeat": {"ru": "Не исправлено", "en": "Not fixed"},
    "walk.none.title": {"ru": "Проверка не начата", "en": "No inspection in progress"},
    "walk.none.text": {
        "ru": "Начните проверку в чате с ботом — кнопка «Новая проверка». Обход появится "
        "здесь сам.",
        "en": "Start an inspection in the chat with the bot — the “New inspection” button. "
        "The walk-through will appear here by itself.",
    },
    "walk.back": {"ru": "Вернуться в чат", "en": "Back to the chat"},
    "walk.closed": {
        "ru": "Обход пока открыт только тестерам. Проверку ведите в чате, как обычно.",
        "en": (
            "The walk-through is open to testers only for now. Keep recording in the chat as usual."
        ),
    },
    "walk.error": {
        "ru": "Обход не загрузился. Закройте окно и откройте снова.",
        "en": "The walk-through did not load. Close the window and open it again.",
    },
    "walk.loading": {"ru": "Загружаю обход…", "en": "Loading the walk-through…"},
    # ── запись из мини-аппа (D312) ──────────────────────────────────────
    "walk.add.violation": {"ru": "Записать нарушение", "en": "Record an issue"},
    "walk.add.measure": {"ru": "Записать замер", "en": "Record a reading"},
    "walk.add.short": {"ru": "Нарушение", "en": "Issue"},
    "walk.add.short_measure": {"ru": "Замер", "en": "Reading"},
    "walk.sheet.new": {"ru": "Новое нарушение", "en": "New issue"},
    "walk.sheet.new_measure": {"ru": "Новый замер", "en": "New reading"},
    "walk.sheet.edit": {"ru": "Запись №{n}", "en": "Record #{n}"},
    "walk.sheet.close": {"ru": "Закрыть", "en": "Close"},
    "walk.sheet.photos": {"ru": "Фото", "en": "Photos"},
    "walk.sheet.photos_hint": {
        "ru": "Без фото запись не ведётся. Несколько ракурсов одного нарушения — в одну запись.",
        "en": "A record needs a photo. Several angles of one issue go into one record.",
    },
    "walk.photo.camera": {"ru": "Снять", "en": "Take photo"},
    "walk.photo.gallery": {"ru": "Из галереи", "en": "From gallery"},
    "walk.photo.uploading": {"ru": "Загружаю…", "en": "Uploading…"},
    "walk.photo.failed": {"ru": "Не загрузилось — повторить", "en": "Failed — retry"},
    "walk.photo.remove": {"ru": "Убрать фото", "en": "Remove photo"},
    "walk.photo.chat": {"ru": "фото из чата", "en": "photo from chat"},
    "walk.photo.last": {
        "ru": "Это последнее фото записи. Сначала добавьте другое.",
        "en": "This is the record's last photo. Add another one first.",
    },
    "walk.sheet.zone": {"ru": "Зона", "en": "Zone"},
    "walk.sheet.item": {"ru": "Что нарушено", "en": "What is wrong"},
    "walk.sheet.item_measure": {"ru": "Что замеряем", "en": "What is measured"},
    "walk.sheet.search": {
        "ru": "Найти пункт: пол, дата, перчатки…",
        "en": "Find an item: floor, date, gloves…",
    },
    "walk.sheet.search_empty": {
        "ru": "Ничего не нашлось. Попробуйте другое слово или покажите все пункты.",
        "en": "Nothing found. Try another word or show all items.",
    },
    "walk.sheet.show_all": {
        "ru": "Все пункты, не только этой зоны",
        "en": "All items, not just this zone",
    },
    "walk.sheet.change": {"ru": "Изменить", "en": "Change"},
    "walk.sheet.was_here": {"ru": "было в прошлый раз", "en": "found last time"},
    "walk.sheet.taken": {
        "ru": "Это уже записано в этой зоне (№{n}). Новые фото добавятся к той записи.",
        "en": "This is already recorded in this zone (#{n}). New photos will be added "
        "to that record.",
    },
    "walk.sheet.level": {"ru": "Класс", "en": "Class"},
    "walk.sheet.level_only": {
        "ru": "Для этого пункта возможен только {level}.",
        "en": "Only {level} is possible for this item.",
    },
    "walk.sheet.text": {"ru": "Что видно", "en": "What you see"},
    "walk.sheet.text_hint": {
        "ru": "Факт: что, где, сколько. Пусто — возьмём формулировку пункта.",
        "en": "The fact: what, where, how many. Empty — the item wording is used.",
    },
    "walk.sheet.text_measure": {"ru": "Показание", "en": "Reading"},
    "walk.sheet.text_measure_hint": {"ru": "Например: −18 °C", "en": "For example: −18 °C"},
    "walk.sheet.comment": {"ru": "Рекомендация партнёру", "en": "Recommendation to the partner"},
    "walk.sheet.comment_add": {"ru": "+ Добавить рекомендацию", "en": "+ Add a recommendation"},
    "walk.sheet.comment_hint": {
        "ru": "Попадёт в отчёт под этой записью.",
        "en": "Goes into the report under this record.",
    },
    "walk.sheet.repeat": {
        "ru": "Повтор прошлого нарушения — вычет ×2",
        "en": "Repeat of a previous issue — double deduction",
    },
    "walk.sheet.repeat_hint": {
        "ru": "В прошлый раз здесь было это же. Решаете вы: исправили и снова сломалось — "
        "не повтор.",
        "en": "The same was found here last time. Your call: fixed and broken again is "
        "not a repeat.",
    },
    "walk.sheet.save": {"ru": "Сохранить", "en": "Save"},
    "walk.sheet.saving": {"ru": "Сохраняю…", "en": "Saving…"},
    "walk.sheet.add_photos": {"ru": "Добавить фото к записи", "en": "Add photos to the record"},
    "walk.sheet.need_photo": {"ru": "Нужно фото", "en": "A photo is needed"},
    "walk.sheet.need_upload": {"ru": "Дождитесь загрузки фото", "en": "Wait for the photo upload"},
    "walk.sheet.need_item": {"ru": "Выберите пункт", "en": "Choose an item"},
    "walk.sheet.need_level": {"ru": "Выберите класс", "en": "Choose a class"},
    "walk.sheet.need_zone": {"ru": "Выберите зону", "en": "Choose a zone"},
    "walk.sheet.delete": {"ru": "Удалить запись", "en": "Delete the record"},
    "walk.sheet.delete_confirm": {"ru": "Удалить насовсем?", "en": "Delete for good?"},
    "walk.sheet.delete_yes": {"ru": "Да, удалить", "en": "Yes, delete"},
    "walk.sheet.cancel": {"ru": "Отмена", "en": "Cancel"},
    "walk.sheet.discard": {
        "ru": "Запись не сохранена. Закрыть без сохранения?",
        "en": "The record is not saved. Close without saving?",
    },
    "walk.sheet.discard_yes": {"ru": "Закрыть", "en": "Close"},
    "walk.sheet.restored": {
        "ru": "Вернули несохранённый черновик.",
        "en": "Your unsaved draft is back.",
    },
    "walk.sheet.saved": {"ru": "Записано", "en": "Recorded"},
    "walk.sheet.unusual": {
        "ru": "Зона не из списка пункта — запись пометится для перепроверки.",
        "en": "The zone is not on the item's list — the record will be flagged for review.",
    },
    "walk.rec.comment": {"ru": "Рекомендация: {text}", "en": "Recommendation: {text}"},
    "walk.rec.repeat": {"ru": "повтор ×2", "en": "repeat ×2"},
    "walk.rec.edit": {"ru": "Открыть запись", "en": "Open the record"},
    "walk.sealed": {
        "ru": "Отчёт по этой проверке сдан — записи больше не меняются.",
        "en": "The report for this inspection is handed over — records can no longer change.",
    },
    "walk.info.title": {"ru": "Сведения о визите", "en": "Visit details"},
    "walk.info.hint": {
        "ru": "Можно заполнить по ходу. Что заполнено здесь, бот в конце не спросит.",
        "en": "Fill these in as you go. What is filled here, the bot will not ask at the end.",
    },
    "walk.info.yes": {"ru": "Да", "en": "Yes"},
    "walk.info.no": {"ru": "Нет", "en": "No"},
    "walk.info.save": {"ru": "Сохранить", "en": "Save"},
    "walk.info.saved": {"ru": "Сохранено", "en": "Saved"},
    "walk.info.empty": {"ru": "не заполнено", "en": "not filled"},
    "walk.err.bad_request": {
        "ru": "Запрос не разобран. Обновите экран и повторите.",
        "en": "The request was not understood. Refresh and try again.",
    },
    "walk.err.too_long": {
        "ru": "Слишком длинно: не больше 1000 знаков.",
        "en": "Too long: 1000 characters at most.",
    },
    "walk.err.empty_text": {
        "ru": "Формулировка не может быть пустой.",
        "en": "The wording cannot be empty.",
    },
    "walk.err.photo_required": {
        "ru": "Нужно хотя бы одно фото: без фотофиксации запись не ведётся.",
        "en": "At least one photo is needed: no record without a photo.",
    },
    "walk.err.photo_lost": {
        "ru": "Фото не дошло до сервера — снимите его ещё раз.",
        "en": "The photo did not reach the server — take it again.",
    },
    "walk.err.photo_bad": {
        "ru": "Фото не принято: нужен снимок JPEG не больше 10 МБ.",
        "en": "The photo was not accepted: a JPEG up to 10 MB is needed.",
    },
    "walk.err.empty_answer": {
        "ru": "Пустой ответ не сохраняется — просто оставьте поле незаполненным.",
        "en": "An empty answer is not saved — just leave the field blank.",
    },
    "walk.err.repeat_level": {
        "ru": "Повтор ставится только нарушению класса D1 или D2.",
        "en": "Only a D1 or D2 issue can be marked as a repeat.",
    },
    "walk.err.server": {
        "ru": "Не получилось записать. Повторите через минуту.",
        "en": "Could not save. Try again in a minute.",
    },
    "walk.err.bad_date": {"ru": "Дата не разобрана.", "en": "The date was not understood."},
    "walk.err.network": {
        "ru": "Нет связи с сервером. Черновик сохранён на телефоне — повторите, когда "
        "появится сеть.",
        "en": "No connection. The draft is kept on the phone — retry when you are back online.",
    },
}
