"""Тексты пакетного ввода нарушений в обходе: несколько кадров со словами."""

BATCH_TEXTS: dict[str, dict[str, str]] = {
    "walk.batch.open": {"ru": "Серия фото", "en": "Photo set"},
    "walk.batch.open_aria": {
        "ru": "Несколько нарушений с фото",
        "en": "Several issues with photos",
    },
    "walk.batch.title": {"ru": "Несколько нарушений", "en": "Several issues"},
    "walk.batch.close": {"ru": "Закрыть", "en": "Close"},
    "walk.batch.intro": {
        "ru": (
            "Одно фото — одно или несколько нарушений. Напишите или надиктуйте, что не так: "
            "разные дефекты в комментарии система разделит на отдельные пункты. "
            "Зону можно назвать в начале комментария — запись встанет в неё."
        ),
        "en": (
            "One photo can hold one or several issues. Type or dictate what is wrong: different "
            "defects in the comment are split into separate items. You can name the zone at "
            "the start of the comment — the record goes into it."
        ),
    },
    "walk.batch.pick": {"ru": "Выбрать фото из галереи", "en": "Pick photos from the gallery"},
    "walk.batch.pick_more": {"ru": "Добавить ещё фото", "en": "Add more photos"},
    "walk.batch.limit": {
        "ru": "Не больше {n} фото за раз. Остальные не добавлены.",
        "en": "No more than {n} photos at a time. The rest were not added.",
    },
    "walk.batch.full": {
        "ru": "В одной пачке не больше {n} фото. Запишите эти, затем добавьте следующие.",
        "en": "No more than {n} photos in one batch. Save these, then add the next ones.",
    },
    "walk.batch.too_many": {
        "ru": "В одной пачке не больше {n} фото.",
        "en": "No more than {n} photos in one batch.",
    },
    "walk.batch.card": {"ru": "Фото {n}", "en": "Photo {n}"},
    "walk.batch.line": {"ru": "Нарушение {n}", "en": "Issue {n}"},
    "walk.batch.line_drop": {"ru": "Убрать нарушение", "en": "Remove the issue"},
    "walk.batch.add_line": {
        "ru": "+ ещё нарушение на этом фото",
        "en": "+ another issue on this photo",
    },
    "walk.batch.line_find": {"ru": "Найти пункт", "en": "Find the item"},
    "walk.batch.split_failed": {
        "ru": (
            "Не удалось разделить комментарий на нарушения — он взят одним. "
            "Если там несколько, добавьте остальные кнопкой «+ ещё нарушение на этом фото»."
        ),
        "en": (
            "Could not split the comment into issues — it was taken as one. If there are "
            "several, add the rest with “+ another issue on this photo”."
        ),
    },
    "walk.batch.words_hint": {
        "ru": "Что не так (можно с зоной в начале)",
        "en": "What is wrong (you can start with the zone)",
    },
    "walk.batch.drop": {"ru": "Убрать карточку", "en": "Remove the card"},
    "walk.batch.find": {"ru": "Найти пункты", "en": "Find items"},
    "walk.batch.finding": {"ru": "Ищу пункты…", "en": "Finding items…"},
    "walk.batch.need_photos": {
        "ru": "Дождитесь загрузки фото: часть ещё грузится или ждёт связи.",
        "en": "Wait for the photos: some are still uploading or waiting for a connection.",
    },
    "walk.batch.need_cards": {"ru": "Добавьте хотя бы одно фото.", "en": "Add at least one photo."},
    "walk.batch.find_failed": {
        "ru": "Не получилось подобрать пункты. Попробуйте ещё раз.",
        "en": "Could not find the items. Try again.",
    },
    "walk.batch.save_ready": {"ru": "Сохранить все готовые ({n})", "en": "Save all ready ({n})"},
    "walk.batch.saving": {"ru": "Записываю…", "en": "Saving…"},
    "walk.batch.saved_n": {"ru": "Записано: {n}", "en": "Saved: {n}"},
    "walk.batch.waiting_n": {"ru": "Ждут вашего решения: {n}", "en": "Waiting for you: {n}"},
    "walk.batch.done": {"ru": "Готово", "en": "Done"},
    "walk.batch.saved": {"ru": "Записано", "en": "Saved"},
    "walk.batch.saved_to": {"ru": "Добавлено к записи №{n}", "en": "Added to record #{n}"},
    "walk.batch.ready": {"ru": "Готово к записи", "en": "Ready to save"},
    "walk.batch.doubt": {"ru": "Нужно ваше решение", "en": "Needs your decision"},
    "walk.batch.zone": {"ru": "Зона: {zone}", "en": "Zone: {zone}"},
    "walk.batch.zone_words": {"ru": "названа в комментарии", "en": "named in the comment"},
    "walk.batch.zone_screen": {
        "ru": "зона не названа — текущая",
        "en": "zone not named — the current one",
    },
    "walk.batch.zone_item": {"ru": "по пункту", "en": "from the item"},
    "walk.batch.zone_human": {"ru": "выбрана вами", "en": "chosen by you"},
    "walk.batch.zone_ask": {"ru": "зона не определена", "en": "zone not determined"},
    "walk.batch.zone_change": {"ru": "Сменить зону", "en": "Change zone"},
    "walk.batch.zone_pick": {"ru": "Зона записи", "en": "Zone of the record"},
    "walk.batch.no_item": {
        "ru": "Пункт не найден. Уточните комментарий и найдите заново или выберите пункт сами.",
        "en": "No item found. Clarify the comment and search again, or pick the item yourself.",
    },
    "walk.batch.retry": {"ru": "Найти заново", "en": "Search again"},
    "walk.batch.fact_hint": {
        "ru": "Допишите это в комментарий и нажмите «Найти заново».",
        "en": "Add this to the comment and press “Search again”.",
    },
    "walk.batch.measure": {
        "ru": "Это замер: вносите его кнопкой «Замер» в зоне. Выберите другой пункт.",
        "en": "This is a reading: record it with the Reading button in the zone. Pick another one.",
    },
    "walk.batch.no_facts": {
        "ru": "Нечего оценивать: напишите, что не так.",
        "en": "Nothing to assess: write what is wrong.",
    },
    "walk.batch.unavailable": {
        "ru": "Не получилось подобрать. Найдите заново.",
        "en": "Could not match this one. Search again.",
    },
    "walk.batch.model_busy": {
        "ru": "Система занята, повторите: нажмите «Найти заново».",
        "en": "The system is busy, try again: press “Search again”.",
    },
    "walk.batch.photo_warn": {
        "ru": (
            "Без комментария система смотрит только фото — это дольше и менее точно. "
            "Карточек без комментария: {n}."
        ),
        "en": (
            "Without a comment the system looks at the photo only — slower and less accurate. "
            "Cards without a comment: {n}."
        ),
    },
    "walk.batch.seen": {"ru": "Система видит:", "en": "The system sees:"},
    "walk.batch.item_ok": {"ru": "Пункт верный", "en": "The item is correct"},
    "walk.batch.item_ok_set": {"ru": "Пункт подтверждён", "en": "Item confirmed"},
    "walk.batch.photo_none": {
        "ru": "Система не нашла нарушение на фото. Опишите словами и найдите заново.",
        "en": "The system found no issue in the photo. Describe it in words and search again.",
    },
    "walk.batch.level_pick": {"ru": "Класс", "en": "Class"},
    "walk.batch.prev": {"ru": "Прошлый раз, {date}: {text}", "en": "Last time, {date}: {text}"},
    "walk.batch.prev_ask": {"ru": "Это то же самое?", "en": "Is it the same thing?"},
    "walk.batch.prev_yes": {"ru": "Да, повтор", "en": "Yes, a repeat"},
    "walk.batch.prev_no": {"ru": "Нет, другое", "en": "No, a different one"},
    "walk.batch.prev_yes_set": {"ru": "Повтор", "en": "Repeat"},
    "walk.batch.prev_no_set": {"ru": "Не повтор", "en": "Not a repeat"},
    "walk.batch.dup_recorded": {
        "ru": "Это нарушение уже записано в этой зоне (запись №{n}).",
        "en": "This issue is already recorded in this zone (record #{n}).",
    },
    "walk.batch.dup_ask": {
        "ru": "Это то же нарушение или другое?",
        "en": "Is it the same issue or a different one?",
    },
    "walk.batch.dup_attach": {
        "ru": "То же: добавить фото к записи",
        "en": "The same: add photos to the record",
    },
    "walk.batch.dup_other": {
        "ru": "Другое: записать отдельно",
        "en": "Different: record separately",
    },
    "walk.batch.dup_batch": {
        "ru": "Такое же нарушение в этой зоне есть в другой карточке списка.",
        "en": "The same issue in this zone is in another card of this list.",
    },
}
