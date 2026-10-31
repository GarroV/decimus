"""Тексты мини-аппа обхода (#418) — сливаются в общий каталог `texts.TEXTS`.

Экран рисует скрипт, но строки живут здесь, а не в `walk.js`: сервер отдаёт
их вместе с данными на языке проверки. Так язык остаётся параметром, а третий
язык добавляется строками каталога, а не правкой скрипта.

Числа — после двоеточия («Замечаний: 3»), а не перед существительным: так
русская форма не зависит от числа, и склонение не нужно ни на одном языке.
"""

from __future__ import annotations

from .texts_app import APP_TEXTS
from .texts_edit import EDIT_TEXTS
from .texts_hints import HINT_TEXTS
from .texts_level import LEVEL_TEXTS
from .texts_split import SPLIT_TEXTS

WALK_TEXTS: dict[str, dict[str, str]] = {
    "walk.sheet.search_tag.dirty": {"ru": "Грязно", "en": "Dirty"},
    "walk.sheet.search_tag.expired": {"ru": "Просрочка", "en": "Expired"},
    "walk.sheet.search_tag.segregation": {"ru": "Товарное соседство", "en": "Food segregation"},
    "walk.sheet.search_tag.labels": {"ru": "Маркировки", "en": "Labels"},
    "walk.sheet.search_clear_tags": {"ru": "Снять фильтры", "en": "Clear filters"},
    "walk.err.run_changed": {
        "ru": "Начата другая проверка. Обновите экран; черновик прежней сохранён на устройстве.",
        "en": (
            "Another inspection has started. Refresh the screen; "
            "the old draft is kept on this device."
        ),
    },
    "walk.draft.marks": {"ru": "Отметки прежнего обхода", "en": "Marks from an earlier walk"},
    "walk.draft.marks_preview": {
        "ru": "Осмотренные зоны: {zones}\nПерепроверенные пункты: {findings}",
        "en": "Checked zones: {zones}\nRechecked items: {findings}",
    },
    "walk.draft.marks_confirm": {
        "ru": (
            "Перенести эти отметки в текущую проверку? Подтвердите, что они относятся "
            "к ней. Исходная копия сохранится."
        ),
        "en": (
            "Copy these marks into the current inspection? Confirm they belong to it. "
            "The original will be kept."
        ),
    },
    "walk.draft.recovery": {"ru": "Черновик прежнего обхода", "en": "Draft from an earlier walk"},
    "walk.draft.unknown": {
        "ru": (
            "Начало этого черновика неизвестно. Проверьте текст и кадры перед "
            "переносом в текущую проверку. Исходная копия сохранится."
        ),
        "en": (
            "This draft's inspection is unknown. Review its text and photos before "
            "copying into this inspection. The original will be kept."
        ),
    },
    "walk.draft.copy": {"ru": "Перенести в эту проверку…", "en": "Copy into this inspection…"},
    "walk.draft.confirm": {
        "ru": (
            "Заменить текущую незавершённую форму этим черновиком и перенести "
            "показанные кадры? Подтвердите, что они относятся к этой проверке."
        ),
        "en": (
            "Replace the current unsaved form with this draft and copy the photos "
            "shown? Confirm they belong to this inspection."
        ),
    },
    "walk.progress": {
        "ru": "Осмотрено зон: {done} из {total}",
        "en": "Zones checked: {done} of {total}",
    },
    "walk.all_done": {"ru": "Все зоны осмотрены", "en": "All zones checked"},
    "walk.prev.none": {
        "ru": "Это первая проверка пиццерии — сравнивать не с чем.",
        "en": "This is the pizzeria's first inspection — nothing to compare with.",
    },
    "walk.prev.unavailable": {
        "ru": "История сейчас недоступна, подсказок о прошлой проверке не будет.",
        "en": "History is unavailable right now, so there are no hints from last time.",
    },
    "walk.prev.line": {
        "ru": "Прошлый раз, {date}: не перепроверено {count}",
        "en": "Last time, {date}: {count} not rechecked",
    },
    "walk.prev.line_done": {
        "ru": "Прошлый раз, {date}: всё перепроверено",
        "en": "Last time, {date}: all rechecked",
    },
    "walk.prev.line_clean": {
        "ru": "Прошлый раз, {date}: без замечаний",
        "en": "Last time, {date}: no findings",
    },
    "walk.switch.all": {"ru": "Все зоны", "en": "All zones"},
    "walk.switch.prev": {"ru": "Предыдущая зона", "en": "Previous zone"},
    "walk.switch.next": {"ru": "Следующая зона", "en": "Next zone"},
    "walk.hint.left": {"ru": "Осталось:", "en": "Left:"},
    "walk.hint.more": {"ru": "ещё {count}", "en": "{count} more"},
    "walk.tile.done": {"ru": "осмотрено", "en": "checked"},
    "walk.tile.todo": {"ru": "не были", "en": "not yet"},
    "walk.tile.started": {"ru": "в работе", "en": "in progress"},
    "walk.zone.measure_here": {"ru": "Измерения в этой зоне", "en": "Measurements in this zone"},
    "walk.zone.measure_add": {"ru": "внести", "en": "add"},
    "walk.zone.need_prev": {
        "ru": "Сначала отметьте прошлое замечание: исправлено или нет.",
        "en": "First mark last time's finding: fixed or not.",
    },
    "walk.add.short_advice": {"ru": "Рекомендация", "en": "Recommendation"},
    "walk.kind.violation": {"ru": "Нарушение", "en": "Finding"},
    "walk.kind.advice": {"ru": "Рекомендация", "en": "Recommendation"},
    "walk.rec.advice": {"ru": "Рек.", "en": "Rec."},
    "walk.cl.title": {"ru": "Чек-лист зоны", "en": "Zone checklist"},
    "walk.cl.count": {"ru": "{count} пунктов", "en": "{count} items"},
    "walk.cl.hint": {
        "ru": "Нажмите пункт, чтобы записать по нему нарушение.",
        "en": "Tap an item to record a finding against it.",
    },
    "walk.timing.active": {"ru": "Идёт проверка", "en": "Inspection in progress"},
    "walk.timing.finished": {"ru": "Длительность проверки", "en": "Inspection duration"},
    "walk.timing.unknown": {"ru": "Время не фиксировалось", "en": "Time was not recorded"},
    "walk.timing.unavailable": {"ru": "Время недоступно", "en": "Time unavailable"},
    "walk.cl.hide": {"ru": "Скрыть пункт памятки", "en": "Hide checklist item"},
    "walk.cl.show": {"ru": "Показать скрытый пункт", "en": "Show hidden item"},
    "walk.item.kind.info": {"ru": "Информация", "en": "Information"},
    "walk.item.kind.violation": {"ru": "Нарушение", "en": "Violation"},
    "walk.item.kind.advice": {"ru": "Рекомендация", "en": "Recommendation"},
    "walk.sheet.search_tags": {"ru": "Поиск по процессу", "en": "Search by process"},
    "walk.cl.was": {"ru": "было", "en": "last time"},
    "walk.unseen.title": {"ru": "Ещё не смотрели", "en": "Not looked at yet"},
    "walk.unseen.info": {"ru": "Замеры без баллов:", "en": "Readings, no points:"},
    "walk.cl.more": {"ru": "Показать ещё {count}", "en": "Show {count} more"},
    "walk.zone.ic.todo": {"ru": "не осмотрена", "en": "not checked yet"},
    "walk.zone.ic.started": {"ru": "в работе", "en": "in progress"},
    "walk.zone.ic.clean": {"ru": "осмотрена, нарушений нет", "en": "checked, no issues"},
    "walk.zone.ic.found_done": {
        "ru": "осмотрена, нарушений: {count}",
        "en": "checked, issues: {count}",
    },
    "walk.zone.ic.found_open": {
        "ru": "в работе, нарушений: {count}",
        "en": "in progress, issues: {count}",
    },
    "walk.finish.native.photos_pending": {
        "ru": "Дождитесь загрузки кадров, повторите отправку или отмените вложение.",
        "en": "Wait for the photos, retry their upload or remove the attachment.",
    },
    "walk.finish.native.photo_answer": {"ru": "Ответ фотографиями", "en": "Photo answer"},
    "walk.finish.native.photo_value_required": {
        "ru": "К фото даты или ответа «да/нет» добавьте значение либо отмените вложение.",
        "en": "Enter the date or yes/no answer for these photos, or remove the attachment.",
    },
    "walk.finish.photos.hint": {
        "ru": "Фото к этому ответу. Подпись — только ваши слова; сохранённые кадры остаются.",
        "en": "Photos for this answer. Captions use your words only; saved photos are retained.",
    },
    "walk.finish.photos.add": {"ru": "Добавить фото ответа", "en": "Add answer photos"},
    "walk.sheet.remaining_material": {
        "ru": "Запись сохранена. Неиспользованных кадров в черновике: {n}.",
        "en": "Record saved. Unused photos remaining in the draft: {n}.",
    },
    "walk.sheet.save_conflict": {
        "ru": (
            "Запись изменилась. Сверьте сохранённые записи перед повтором; "
            "ввод и кадры остаются в черновике."
        ),
        "en": (
            "The record changed. Review saved records before retrying; "
            "your input and photos remain in the draft."
        ),
    },
    "walk.finish.photos.failed": {"ru": "Повторите отправку", "en": "Retry upload"},
    "walk.finish.photos.no_storage": {
        "ru": (
            "Хранилище телефона недоступно. Не закрывайте форму: повторите загрузку "
            "или отмените вложение."
        ),
        "en": "Device storage is unavailable. Keep this form open; retry or remove the attachment.",
    },
    "walk.finish.native.loading": {
        "ru": "Загружаем актуальную проверку…",
        "en": "Loading the current inspection…",
    },
    "walk.finish.native.details": {
        "ru": "Сведения и обратная связь",
        "en": "Visit details and feedback",
    },
    "walk.finish.native.optional": {
        "ru": (
            "Все поля необязательны. Заполните известное; пустые ответы можно пропустить. "
            "Текст обратной связи сохраняется без автоматического перевода."
        ),
        "en": (
            "All fields are optional. Record what you know; unanswered fields can be skipped. "
            "Feedback text is saved without automatic translation."
        ),
    },
    "walk.finish.native.feedback_language": {
        "ru": (
            "Текст обратной связи на языке {lang} не включается в отчёт и письмо "
            "на выбранном языке. Вернитесь к сведениям для смены языка отчёта."
        ),
        "en": (
            "Feedback text recorded in {lang} is omitted from the report and letter "
            "in the selected language. Return to details to change the report language."
        ),
    },
    "walk.finish.native.skip": {"ru": "Не отвечать", "en": "No answer"},
    "walk.finish.native.saved": {"ru": "Сохранено: {value}", "en": "Saved: {value}"},
    "walk.finish.native.review": {"ru": "Проверить итог", "en": "Review the summary"},
    "walk.finish.native.chat": {"ru": "Продолжить в чате", "en": "Continue in chat"},
    "walk.finish.native.records": {
        "ru": "Зафиксировано записей: {count}",
        "en": "Recorded entries: {count}",
    },
    "walk.finish.native.not_answered": {
        "ru": "Не заполнено — в отчёте не печатается",
        "en": "Unanswered — omitted from the report",
    },
    "walk.finish.native.advice": {
        "ru": "Добавить рекомендацию или заметку",
        "en": "Add a recommendation or note",
    },
    "walk.finish.native.pick_language": {"ru": "Выберите язык", "en": "Choose a language"},
    "walk.finish.native.skip_confirm": {
        "ru": "Пропустить незаполненные сведения; не добавлять ответы за меня.",
        "en": "Skip unanswered visit details; do not invent answers.",
    },
    "walk.finish.native.confirm": {
        "ru": "Я проверил записи и обратную связь. Подтверждаю завершение и формирование отчёта.",
        "en": (
            "I reviewed the records and feedback. I confirm finishing the inspection "
            "and building the report."
        ),
    },
    "walk.finish.native.confirm_required": {
        "ru": "Подтвердите итог и пропуск незаполненных полей.",
        "en": "Confirm the summary and any unanswered fields you want to skip.",
    },
    "walk.finish.native.submit": {
        "ru": "Подтвердить и сформировать отчёт",
        "en": "Confirm and build the report",
    },
    "walk.finish.native.status": {"ru": "Завершение проверки", "en": "Finishing the inspection"},
    "walk.finish.native.completed": {
        "ru": "Проверка завершена. Отчёт передан в ваш чат.",
        "en": "The inspection is complete. The report was delivered to your chat.",
    },
    "walk.finish.native.retry": {
        "ru": "Сборка не завершилась. Записи сохранены; проверьте итог и повторите.",
        "en": "The report was not completed. Your records are saved; review the summary and retry.",
    },
    "walk.finish.native.building": {
        "ru": (
            "Отчёт собирается. Оставайтесь здесь или вернитесь позже — повторная "
            "сборка не запускается."
        ),
        "en": "Building the report. Stay here or return later; this does not start another build.",
    },
    "walk.finish.native.check_status": {"ru": "Проверить состояние", "en": "Check status"},
    "walk.finish.err.stale": {
        "ru": "Проверка изменилась. Откройте итог заново и подтвердите актуальные записи.",
        "en": "The inspection changed. Reopen the summary and confirm the current records.",
    },
    "walk.finish.title": {"ru": "Завершить проверку", "en": "Finish the inspection"},
    # Короткая подпись для нижней кнопки: полная не влезает в строку на 390px.
    "walk.finish.dock": {"ru": "Завершить", "en": "Finish"},
    "walk.finish.ask": {
        "ru": "Дальше — итог и отчёт в чате.",
        "en": "Next come the summary and the report in the chat.",
    },
    "walk.finish.sent": {"ru": "Итог отправлен в чат", "en": "The summary is in the chat"},
    "walk.finish.yes": {"ru": "Завершить", "en": "Finish"},
    # Режим «Сразу отчёт» (D449).
    "walk.finish.ask_report": {
        "ru": "Сформировать отчёт и прислать в чат?",
        "en": "Build the report and send it to the chat?",
    },
    "walk.finish.report_lang": {"ru": "Язык отчёта", "en": "Report language"},
    "walk.finish.yes_report": {"ru": "Сформировать", "en": "Build"},
    "walk.finish.sent_report": {
        "ru": "Отчёт собирается — он придёт в чат",
        "en": "The report is being built — it will arrive in the chat",
    },
    "walk.finish.err.lang": {
        "ru": "Выберите язык отчёта из предложенных.",
        "en": "Pick the report language from the offered ones.",
    },
    "walk.finish.err.info": {
        "ru": "Сначала заполните сведения о визите: {count}",
        "en": "Fill in the visit details first: {count}",
    },
    "walk.finish.err.busy": {
        "ru": "Отчёт уже собирается — дождитесь его в чате.",
        "en": "The report is already being built — wait for it in the chat.",
    },
    "walk.finish.err.none": {
        "ru": "Проверки нет — завершать нечего.",
        "en": "There is no inspection to finish.",
    },
    "walk.finish.err.failed": {
        "ru": "Не получилось. Завершите проверку командой /finish в чате.",
        "en": "That did not work. Finish with the /finish command in the chat.",
    },
    "walk.zone.clean_done": {
        "ru": "Зона осмотрена, нарушений нет.",
        "en": "Zone checked, nothing found.",
    },
    "walk.zone.done_toast": {"ru": "{zone}: осмотрено", "en": "{zone}: checked"},
    "walk.next.mark": {"ru": "Осмотрено →", "en": "Checked →"},
    "walk.next.go": {"ru": "Следующая →", "en": "Next →"},
    "walk.info.open": {"ru": "Сведения", "en": "Details"},
    "walk.zone.unmark": {"ru": "Вернуть в неосмотренные", "en": "Mark as not checked"},
    "walk.zone.now": {"ru": "Записано сейчас", "en": "Recorded now"},
    "walk.zone.before": {"ru": "Было в прошлый раз", "en": "Found last time"},
    "walk.count.now": {"ru": "сейчас: {count}", "en": "now: {count}"},
    "walk.count.before": {"ru": "было: {count}", "en": "last time: {count}"},
    "walk.item.again": {"ru": "Записано снова", "en": "Recorded again"},
    "walk.item.fixed": {"ru": "Исправлено", "en": "Fixed"},
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
    # ── запись из мини-аппа (D312) ──────────────────────────────────────
    "walk.add.short": {"ru": "Нарушение", "en": "Issue"},
    "walk.sheet.new": {"ru": "Новое нарушение", "en": "New issue"},
    "walk.sheet.new_measure": {"ru": "Новый замер", "en": "New reading"},
    "walk.sheet.new_advice": {"ru": "Новая рекомендация", "en": "New recommendation"},
    "walk.sheet.edit": {"ru": "Запись №{n}", "en": "Record #{n}"},
    "walk.sheet.edit_advice": {"ru": "Рекомендация №{n}", "en": "Recommendation #{n}"},
    "walk.sheet.advice_hint": {
        "ru": "Без вычета: что команде стоит сделать. Не про пункт — «Общая заметка».",
        "en": "No deduction: what the team should do. Not about an item — “General note”.",
    },
    "walk.sheet.measure_hint": {
        "ru": "Показание без вычета: температура, настройки печи, снимок изделия.",
        "en": "A reading, no deduction: temperature, oven settings, product photo.",
    },
    "walk.sheet.photos_measure": {
        "ru": "Снимок прибора, табло или изделия — обязателен.",
        "en": "A photo of the gauge, display or product is required.",
    },
    "walk.sheet.search_measure": {
        "ru": "Найти: температура, печь, изделие…",
        "en": "Find: temperature, oven, product…",
    },
    "walk.note.item": {"ru": "Общая заметка — без пункта", "en": "General note — no item"},
    "walk.note.hint": {
        "ru": "Уйдёт в конец отчёта, в «Заметки проверяющего».",
        "en": "Goes to the end of the report, under “Auditor's notes”.",
    },
    "walk.eq.title": {
        "ru": "Печь и холодильники",
        "en": "Oven and fridges",
    },
    "walk.eq.hint": {
        "ru": (
            "Показания без вычета — уходят в приложение отчёта. "
            "У каждого — снимок прибора или изделия."
        ),
        "en": (
            "Readings with no deduction — they go to the report appendix. "
            "Each needs a photo of the gauge or product."
        ),
    },
    "walk.rec.note": {"ru": "Заметка", "en": "Note"},
    "walk.sheet.photos_optional": {
        "ru": "По желанию, но с фото команде понятнее.",
        "en": "Optional, but a photo makes it clearer for the team.",
    },
    "walk.sheet.item_advice": {"ru": "К какому пункту", "en": "Which item"},
    "walk.sheet.text_advice": {"ru": "Что сделать", "en": "What to do"},
    "walk.sheet.text_advice_hint": {
        "ru": "Например: смазать петли крышки линии — открывается туго.",
        "en": "For example: grease the line lid hinges — it is hard to open.",
    },
    "walk.sheet.need_advice": {"ru": "Напишите, что сделать", "en": "Write what to do"},
    "walk.sheet.advice_has_violation": {
        "ru": "По этому пункту здесь уже есть нарушение №{n}. Рекомендацию можно дописать в него.",
        "en": "Finding #{n} already covers this item here. Add the recommendation to it.",
    },
    "walk.sheet.close": {"ru": "Закрыть", "en": "Close"},
    "walk.sheet.back": {"ru": "Назад", "en": "Back"},
    "walk.sheet.kind": {"ru": "Что записываем", "en": "What are you recording"},
    "walk.kind.violation_hint": {"ru": "с вычетом", "en": "deducted"},
    "walk.kind.advice_hint": {"ru": "совет", "en": "advice"},
    "walk.sheet.pick_zone": {"ru": "Выбрать зону", "en": "Choose area"},
    "walk.photo.hero": {"ru": "Фото нарушения", "en": "Photo of the issue"},
    "walk.photo.more": {"ru": "Ещё фото", "en": "Another photo"},
    "walk.photo.gallery": {"ru": "Галерея", "en": "Gallery"},
    "walk.camera.title": {"ru": "Камера", "en": "Camera"},
    "walk.camera.shoot": {"ru": "Снять", "en": "Take photo"},
    "walk.camera.close": {"ru": "Закрыть камеру", "en": "Close camera"},
    "walk.camera.torch.on": {"ru": "Включить фонарик", "en": "Turn torch on"},
    "walk.camera.torch.off": {"ru": "Выключить фонарик", "en": "Turn torch off"},
    "walk.camera.torch.unavailable": {
        "ru": "Фонарик этой камеры недоступен",
        "en": "Torch is unavailable for this camera",
    },
    "walk.camera.denied": {
        "ru": "Камера недоступна — выберите снимок в «Галерее»",
        "en": "Camera unavailable — pick a photo from the Gallery",
    },
    "walk.sheet.words": {"ru": "Что не так", "en": "What is wrong"},
    "walk.sheet.words_hint": {
        "ru": "Пара слов: «нагар на крышке линии», «просрочка на сыре»",
        "en": "A few words: “burnt residue on the lid”, “expired cheese”",
    },
    "walk.sheet.find": {"ru": "Найти пункт", "en": "Find the item"},
    "walk.sheet.finding": {"ru": "Система ищет пункт…", "en": "Looking for the item…"},
    "walk.sheet.finding_short": {"ru": "Ищу…", "en": "Searching…"},
    # Мгновенная подсказка, пока модель думает (#1267, D646).
    "walk.sheet.preview": {
        "ru": "Пока система уточняет — вероятно, это:",
        "en": "While the system checks, this is likely:",
    },
    "walk.sheet.found": {"ru": "Система предлагает", "en": "Suggested"},
    # Второе нарушение по тем же кадрам (D593).
    "walk.sheet.also": {"ru": "+ Тоже записать", "en": "+ Record this too"},
    "walk.sheet.also_on": {"ru": "✓ Запишется тоже", "en": "✓ Will be recorded too"},
    "walk.sheet.save_n": {"ru": "Сохранить ({n})", "en": "Save ({n})"},
    # Показание термометра (#836).
    "walk.sheet.reading": {"ru": "Температура, °C", "en": "Temperature, °C"},
    "walk.sheet.reading_hint": {
        "ru": (
            "Система прочитала число с фото. Если цифры прочитаны неверно — "
            "исправьте, предложение пересчитается."
        ),
        "en": (
            "The system read this number from the photo. If the digits are wrong, "
            "correct it and the suggestion is recalculated."
        ),
    },
    "walk.sheet.reading_reset": {
        "ru": "Искать заново без температуры",
        "en": "Search again without the temperature",
    },
    "walk.sheet.recheck": {
        "ru": "Пересчитать по температуре",
        "en": "Recalculate for this temperature",
    },
    "walk.sheet.rechecking": {"ru": "Пересчитываю…", "en": "Recalculating…"},
    "walk.sheet.reading_none": {
        "ru": (
            "При температуре {value} °C нарушения нет — записывать нечего. "
            "Верните прежнее число или удалите запись."
        ),
        "en": (
            "At {value} °C there is no violation, so there is nothing to record. "
            "Restore the previous number or delete the entry."
        ),
    },
    "walk.sheet.found_none": {
        "ru": "Подходящего пункта система не нашла. Добавьте слов или выберите пункт вручную.",
        "en": "No matching item found. Add a few words or pick the item yourself.",
    },
    "walk.sheet.found_stale": {
        "ru": "Кадры или слова поменялись.",
        "en": "Photos or words have changed.",
    },
    "walk.sheet.find_again": {"ru": "Найти заново", "en": "Search again"},
    "walk.sheet.pick_manual": {"ru": "Выбрать пункт вручную", "en": "Pick the item yourself"},
    "walk.sheet.pick_item": {"ru": "Выбрать пункт", "en": "Choose item"},
    "walk.sheet.photos": {"ru": "Фото", "en": "Photos"},
    "walk.photo.uploading": {"ru": "Загружаю…", "en": "Uploading…"},
    "walk.photo.failed": {"ru": "Не загрузилось — повторить", "en": "Failed — retry"},
    "walk.photo.waiting": {"ru": "Ждёт связи", "en": "Waiting for signal"},
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
        "ru": "Ничего не нашлось. Попробуйте другое слово.",
        "en": "Nothing found. Try another word.",
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
    "walk.sheet.text_aside": {
        "ru": "Похоже, это рассуждение модели, а не находка. Перепишите текст своими словами.",
        "en": "This looks like the model's reasoning, not a finding. Rewrite it in your own words.",
    },
    "walk.sheet.text_hint": {
        "ru": "Что, где, сколько. Пусто — формулировка пункта.",
        "en": "What, where, how many. Empty — the item wording.",
    },
    "walk.sheet.text_measure": {"ru": "Показание", "en": "Reading"},
    "walk.sheet.text_measure_hint": {"ru": "Например: −18 °C", "en": "For example: −18 °C"},
    "walk.sheet.comment": {"ru": "Рекомендация партнёру", "en": "Recommendation to the partner"},
    "walk.sheet.comment_add": {"ru": "+ Добавить рекомендацию", "en": "+ Add a recommendation"},
    "walk.sheet.repeat": {
        "ru": "Повтор прошлого нарушения — вычет ×2",
        "en": "Repeat of a previous issue — double deduction",
    },
    "walk.sheet.repeat_hint": {
        "ru": "В прошлый раз здесь было это же. Исправили и снова сломалось — не повтор.",
        "en": "Found here last time too. Fixed and broken again is not a repeat.",
    },
    "walk.sheet.save": {"ru": "Сохранить", "en": "Save"},
    "walk.sheet.saving": {"ru": "Сохраняю…", "en": "Saving…"},
    "walk.sheet.add_photos": {"ru": "Добавить фото к записи", "en": "Add photos to the record"},
    "walk.sheet.need_photo": {"ru": "Нужно фото", "en": "A photo is needed"},
    "walk.sheet.need_upload": {"ru": "Дождитесь загрузки фото", "en": "Wait for the photo upload"},
    "walk.sheet.need_online": {
        "ru": "Кадры ждут связи — сохранить можно, когда они загрузятся",
        "en": "Photos are waiting for a connection — you can save once they are uploaded",
    },
    "walk.sheet.need_item": {"ru": "Выберите пункт", "en": "Choose an item"},
    "walk.sheet.need_level": {"ru": "Выберите класс", "en": "Choose a class"},
    "walk.sheet.need_factual_text": {
        "ru": "Опишите наблюдаемый факт для каждой записи о нарушении",
        "en": "Describe the observed fact for each violation",
    },
    "walk.sheet.extra_text": {
        "ru": "Факт для дополнительной записи",
        "en": "Fact for the extra finding",
    },
    "walk.sheet.text_model_review": {
        "ru": (
            "Проверьте полный текст факта. Предложение модели можно изменить; "
            "вопрос методики не заменяет наблюдение."
        ),
        "en": (
            "Review the full factual description. Edit the model suggestion; "
            "a checklist question is not an observation."
        ),
    },
    "walk.sheet.class_review.not_established": {
        "ru": (
            "Нарушение по этим фактам не установлено. "
            "Проверьте пункт и факты или явно выберите класс вручную."
        ),
        "en": (
            "These facts do not establish a violation. "
            "Review the item and facts, or explicitly select a class manually."
        ),
    },
    "walk.sheet.class_review.history": {
        "ru": "Вопросы и ответы по этому пункту",
        "en": "Questions and answers for this item",
    },
    "walk.sheet.class_review.review_changed": {
        "ru": "Факты или фото изменились. Проверьте прежние ответы перед повторным использованием.",
        "en": "The facts or photos changed. Review the earlier answers before using them again.",
    },
    "walk.sheet.class_review.reaffirm": {
        "ru": "Проверил: ответы относятся к текущим фактам",
        "en": "I checked: the answers apply to the current facts",
    },
    "walk.sheet.class_review.choose_item": {
        "ru": "Сначала выберите пункт. Класс определим по его критериям после выбора.",
        "en": "Choose an item first. Its class will be checked against that item's criteria.",
    },
    "walk.sheet.class_review.check_hint": {
        "ru": "Проверьте факты и определите класс по критериям выбранного пункта.",
        "en": "Check the facts, then determine the class for the selected item.",
    },
    "walk.sheet.class_review.pending": {"ru": "Определяем класс…", "en": "Checking the class…"},
    "walk.sheet.class_review.proposed": {
        "ru": "Предложенный класс: {level}",
        "en": "Proposed class: {level}",
    },
    "walk.sheet.class_review.provisional": {
        "ru": "Предварительно: {level}. Этот класс пока не выбран — нужен ответ на вопрос.",
        "en": "Provisional: {level}. This class is not selected; answer the question first.",
    },
    "walk.sheet.class_review.manual": {
        "ru": "Выбрать класс вручную",
        "en": "Choose class manually",
    },
    "walk.sheet.class_review.manual_active": {
        "ru": "Класс выбирает аудитор",
        "en": "The auditor selects the class",
    },
    "walk.sheet.class_review.check": {
        "ru": "Определить класс по фактам",
        "en": "Check class against the facts",
    },
    "walk.sheet.class_review.facts": {
        "ru": "Уточнение фактов для этого пункта",
        "en": "Facts for this item",
    },
    "walk.sheet.class_review.need_class": {
        "ru": "Определите или явно выберите класс",
        "en": "Determine or explicitly select a class",
    },
    "walk.sheet.class_review.unavailable": {
        "ru": "Проверить класс не удалось. Повторите или выберите его вручную.",
        "en": "Could not check the class. Retry or select it manually.",
    },
    "walk.sheet.class_review.confirm_reading": {
        "ru": "Проверьте и подтвердите показание термометра или очистите поле",
        "en": "Check and confirm the thermometer reading, or clear it",
    },
    "walk.sheet.class_review.reading_checked": {
        "ru": "Проверил показание: это число относится к выбранному пункту",
        "en": "I checked: this reading belongs to the selected item",
    },
    "walk.sheet.class_review.add_reading": {"ru": "Указать показание", "en": "Add a reading"},
    "walk.sheet.class_review.context_changed": {
        "ru": "Проверка изменилась. Откройте запись в текущей проверке заново.",
        "en": "The inspection changed. Reopen the finding in the current inspection.",
    },
    "walk.sheet.class_review.facts_limit": {
        "ru": "Сократите слова и уточнение до 1000 знаков",
        "en": "Shorten the words and clarification to 1000 characters",
    },
    "walk.sheet.class_review.photos_limit": {
        "ru": "Для проверки класса выберите до 10 кадров или выберите класс вручную",
        "en": "Choose up to 10 photos for the class check, or select the class manually",
    },
    "walk.sheet.class_review.saved_facts": {
        "ru": "Сохранённые уточнения требуют проверки",
        "en": "Saved facts need review",
    },
    "walk.sheet.class_review.use_saved_facts": {
        "ru": "Использовать этот текст для выбранного пункта",
        "en": "Use this text for the selected item",
    },
    "walk.sheet.class_review.draft_level": {
        "ru": "В черновике был {level}. Подтвердите класс вручную или проверьте по фактам.",
        "en": "The draft had {level}. Select the class explicitly or check it against the facts.",
    },
    "walk.sheet.photo_assignment.title": {
        "ru": "Фото этой записи",
        "en": "Photos for this finding",
    },
    "walk.sheet.photo_assignment.hint": {
        "ru": "Выберите кадры, подтверждающие именно этот факт, и проверьте привязку.",
        "en": "Choose the photos supporting this particular fact and check the assignment.",
    },
    "walk.sheet.photo_assignment.frame": {"ru": "Кадр {n}", "en": "Frame {n}"},
    "walk.sheet.photo_assignment.confirm": {
        "ru": "Проверил: выбранные фото относятся к этой записи",
        "en": "I checked: the selected photos belong to this finding",
    },
    "walk.sheet.photo_assignment.need": {
        "ru": "Выберите и подтвердите фото для каждой выбранной записи",
        "en": "Choose and confirm photos for each selected finding",
    },
    "walk.err.photo_assignment": {
        "ru": "Привязка фото устарела или не подтверждена. Выберите фото записи заново.",
        "en": "Photo assignment is stale or unconfirmed. Select this finding's photos again.",
    },
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
    "walk.sheet.saved_in": {"ru": "Записано: {zone}", "en": "Recorded: {zone}"},
    "walk.sheet.saved_go": {"ru": "Перейти", "en": "Go there"},
    "walk.sheet.where": {"ru": "Где?", "en": "Where?"},
    "walk.sheet.zone_other": {"ru": "Другая зона…", "en": "Another zone…"},
    "walk.sheet.need_where": {
        "ru": "Укажите, где нарушение",
        "en": "Say where the issue is",
    },
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
    "walk.err.photo_quota": {
        "ru": "Лимит фото на сегодня исчерпан — новые кадры примутся через сутки. "
        "Если это живая проверка, напишите администратору.",
        "en": "Today's photo limit is used up — new photos will be accepted within a day. "
        "If this is a live inspection, contact the administrator.",
    },
    "walk.err.empty_answer": {
        "ru": "Пустой ответ не сохраняется — просто оставьте поле незаполненным.",
        "en": "An empty answer is not saved — just leave the field blank.",
    },
    "walk.err.reading": {
        "ru": "Это не похоже на температуру. Введите число в °C, например 6 или -18.",
        "en": "That does not look like a temperature. Enter a number in °C, for example 6 or -18.",
    },
    "walk.err.repeat_level": {
        "ru": "Повтор ставится только нарушению класса D1 или D2.",
        "en": "Only a D1 or D2 issue can be marked as a repeat.",
    },
    "walk.err.suggest_busy": {
        "ru": "Система ещё ищет пункт по прошлому нажатию — подождите пару секунд.",
        "en": "Still looking for the item from your last tap — give it a few seconds.",
    },
    "walk.err.recognize": {
        "ru": "Система сейчас не может найти пункт. Выберите его вручную — запись не потеряется.",
        "en": "The system can't find the item right now. Pick it yourself — nothing is lost.",
    },
    "walk.err.translate": {
        "ru": "Перевод сейчас недоступен. Текст остался как был — его можно перевести самому.",
        "en": "Translation is unavailable right now. Your text is unchanged — translate by hand.",
    },
    "walk.err.overloaded": {
        "ru": "Сервер сейчас занят другими запросами — повторите через несколько секунд.",
        "en": "The server is busy with other requests right now — try again in a few seconds.",
    },
    "walk.err.translate_busy": {
        "ru": "Система ещё переводит по прошлому нажатию — подождите пару секунд.",
        "en": "Still translating from your last tap — give it a few seconds.",
    },
    "walk.err.translate_long": {
        "ru": "Перевод вышел длиннее 1000 знаков. Сократите текст и переведите снова.",
        "en": "The translation came out over 1000 characters. Shorten the text and retry.",
    },
    "walk.translate.btn": {"ru": "Перевести на {lang}", "en": "Translate to {lang}"},
    "walk.translate.busy": {"ru": "Перевожу…", "en": "Translating…"},
    "walk.translate.undo": {"ru": "Вернуть как было", "en": "Restore original"},
    "walk.translate.hint": {
        "ru": "Перевод предложен системой — проверьте текст и сохраните.",
        "en": "Translation proposed by the system — check the text, then save.",
    },
    "walk.translate.lang.ru": {"ru": "русский", "en": "Russian"},
    "walk.translate.lang.en": {"ru": "английский", "en": "English"},
    "walk.voice.start": {"ru": "Надиктовать", "en": "Dictate"},
    "walk.voice.stop": {"ru": "Стоп · {time}", "en": "Stop · {time}"},
    "walk.voice.busy": {"ru": "Расшифровываю…", "en": "Transcribing…"},
    "walk.voice.denied": {
        "ru": (
            "Нет доступа к микрофону — разрешите его Telegram или используйте диктовку клавиатуры."
        ),
        "en": "No microphone access — allow it for Telegram or use your keyboard's dictation.",
    },
    "walk.err.voice": {
        "ru": "Не разобрал запись — скажите ещё раз или напишите текстом.",
        "en": "Couldn't make out the recording — say it again or type it.",
    },
    "walk.err.voice_busy": {
        "ru": "Прошлая запись ещё расшифровывается — подождите пару секунд.",
        "en": "The last recording is still being transcribed — give it a few seconds.",
    },
    "walk.err.voice_big": {
        "ru": "Запись слишком большая — скажите короче или напишите текстом.",
        "en": "The recording is too large — say it shorter or type it.",
    },
    "walk.err.too_fast": {
        "ru": "Слишком много запросов подряд. Подождите минуту и повторите.",
        "en": "Too many requests in a row. Wait a minute and try again.",
    },
    "walk.err.server": {
        "ru": "Не получилось записать. Повторите через минуту.",
        "en": "Could not save. Try again in a minute.",
    },
    "walk.err.rejected": {
        "ru": "Запись не принята. Проверьте выбранный пункт и уровень и повторите.",
        "en": "The entry was not accepted. Check the chosen item and level and try again.",
    },
    "walk.err.bad_date": {"ru": "Дата не разобрана.", "en": "The date was not understood."},
    "walk.offline.parked": {
        "ru": "Нет связи. Кадр сохранён на телефоне и уйдёт сам, когда сеть вернётся.",
        "en": "No connection. The photo is kept on the phone and will upload by itself when "
        "the network is back.",
    },
    "walk.offline.sent": {
        "ru": "Кадры, снятые без связи, загружены: {n}. Они в черновике записи.",
        "en": "Photos taken offline are uploaded: {n}. They are in the record draft.",
    },
    "walk.offline.full": {
        "ru": "Память для кадров без связи заполнена — этот кадр не сохранён. "
        "Дождитесь сети и снимите снова.",
        "en": "The offline photo storage is full — this photo was not kept. "
        "Wait for the network and take it again.",
    },
    "walk.offline.nostore": {
        "ru": "Телефон не даёт сохранить кадр без связи. Дождитесь сети и снимите снова.",
        "en": "The phone would not keep the photo offline. Wait for the network and take it again.",
    },
    "walk.offline.dropped": {
        "ru": "Не удалось отправить кадров: {n}. Они удалены с телефона — снимите заново.",
        "en": "Photos that could not be sent: {n}. They were removed from the phone — "
        "take them again.",
    },
    "walk.offline.expired": {
        "ru": "Кадры без связи старше {days} дней удалены: {n}. Снимите заново.",
        "en": "Offline photos older than {days} days were removed: {n}. Take them again.",
    },
    "walk.err.network": {
        "ru": "Нет связи с сервером. Черновик сохранён на телефоне — повторите, когда "
        "появится сеть.",
        "en": "No connection. The draft is kept on the phone — retry when you are back online.",
    },
}

# Главная и настройки приложения (D373) — тем же каталогом, одним ответом.
WALK_TEXTS.update(APP_TEXTS)
WALK_TEXTS.update(HINT_TEXTS)

WALK_TEXTS.update(SPLIT_TEXTS)

WALK_TEXTS.update(LEVEL_TEXTS)

WALK_TEXTS.update(EDIT_TEXTS)
