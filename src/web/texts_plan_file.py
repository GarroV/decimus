"""Тексты файла «туда и обратно» электронного плана (#1168, шаг 3): выгрузка, итог, конфликт.

Отдельным модулем, как `texts_plan_rows.py`: каталог `texts.py` длиннее предела файла.
Сливаются в общий каталог (`texts.TEXTS`) со сверкой пересечений ключей.
"""

from __future__ import annotations

PLAN_FILE_TEXTS: dict[str, dict[str, str]] = {
    # --- книга xlsx --------------------------------------------------------
    "plans.sheet.hint": {
        "ru": (
            "Заполните жёлтые колонки: что сделаем, кто отвечает, почему (по желанию) и свой срок "
            "— не позже срока по методике. Остальное закрыто от правки. Колонку J и ячейки "
            "в ней не трогайте: по ним система узнаёт строки."
        ),
        "en": (
            "Fill in the yellow columns: what we will do, who is responsible, why (optional) and "
            "your own date — no later than the methodology date. The rest is locked. "
            "Leave column J and its cells alone: the system matches rows by them."
        ),
    },
    "plans.sheet.col.due_sys": {"ru": "Срок по методике", "en": "Methodology deadline"},
    "plans.sheet.col.measure": {"ru": "Что сделаем", "en": "What we will do"},
    "plans.sheet.col.responsible": {"ru": "Кто отвечает", "en": "Who is responsible"},
    "plans.sheet.col.reason": {"ru": "Почему так вышло", "en": "Why it happened"},
    "plans.sheet.col.due_own": {"ru": "Свой срок", "en": "Own date"},
    # --- блок «Файл» в панели ---------------------------------------------
    "plans.file.title": {"ru": "Заполнить файлом", "en": "Fill in with a file"},
    "plans.file.text": {
        "ru": (
            "Скачайте план, заполните жёлтые колонки и загрузите файл обратно: строки лягут в план "
            "так же, как если бы вы заполнили их на экране. Файл остаётся в истории версий. "
            "Файл другого вида принимается вложением, строки из него не читаются."
        ),
        "en": (
            "Download the plan, fill in the yellow columns and upload the file back: the rows land "
            "in the plan just as if you had filled them in on screen. The file stays in the "
            "version history. A file of another kind is accepted as an attachment and its rows "
            "are not read."
        ),
    },
    "plans.file.download": {"ru": "Скачать план для заполнения", "en": "Download plan to fill in"},
    "plans.file.unavailable": {
        "ru": "Файл для заполнения выдаётся партнёру, пока план ждёт его строк.",
        "en": "The fill-in file is available to the partner while the plan awaits its rows.",
    },
    "plans.file.parsed": {"ru": "строки прочитаны", "en": "rows read"},
    # --- итог загрузки -----------------------------------------------------
    "plans.file.unparsed_notice": {
        "ru": "Файл принят вложением, но не разобран — заполните строки на экране.",
        "en": "The file was accepted as an attachment but not parsed — fill in the rows on screen.",
    },
    "plans.file.other_plan_notice": {
        "ru": "Этот файл выгружен из другого плана. Принят вложением, но не разобран — "
        "заполните строки на экране или скачайте файл этого плана.",
        "en": "This file was exported from another plan. Accepted as an attachment but not "
        "parsed — fill in the rows on screen or download this plan's file.",
    },
    "plans.file.result.title": {
        "ru": "Файл прочитан: строк {n}",
        "en": "File read: {n} rows",
    },
    "plans.file.result.written": {
        "ru": "Записано в план строк: {n}.",
        "en": "Rows written to the plan: {n}.",
    },
    "plans.file.result.nothing": {
        "ru": "В плане ничего не изменилось: файл совпал с тем, что на экране.",
        "en": "Nothing changed in the plan: the file matches what is on screen.",
    },
    "plans.file.result.unfilled": {
        "ru": "Нет меры или ответственного в строках: {rows}. План не уйдёт на согласование, "
        "пока они не заполнены.",
        "en": "Measure or responsible person missing in rows: {rows}. The plan cannot be sent "
        "for approval until they are filled in.",
    },
    "plans.file.result.absent": {
        "ru": "Строк плана нет в файле, они остались как на экране: {rows}.",
        "en": "Plan rows missing from the file were left as on screen: {rows}.",
    },
    "plans.file.due.not_date": {
        "ru": "Строка {n}: срок не принят — в ячейке не дата.",
        "en": "Row {n}: date not accepted — the cell is not a date.",
    },
    "plans.file.due.late": {
        "ru": "Строка {n}: срок не принят — позже положенного ({bound}).",
        "en": "Row {n}: date not accepted — later than allowed ({bound}).",
    },
    "plans.file.due.past": {
        "ru": "Строка {n}: срок не принят — уже прошёл, не раньше {bound}.",
        "en": "Row {n}: date not accepted — already past, not before {bound}.",
    },
    "plans.file.skipped.title": {
        "ru": "Пропущено строк файла без пары: {n}",
        "en": "File rows skipped without a match: {n}",
    },
    "plans.file.skipped.unknown": {
        "ru": "Строка файла {line}: такой строки в этом плане нет.",
        "en": "File row {line}: there is no such row in this plan.",
    },
    "plans.file.skipped.duplicate": {
        "ru": "Строка файла {line}: эта строка плана уже была выше — повтор пропущен.",
        "en": "File row {line}: this plan row already appeared above — the repeat was skipped.",
    },
    "plans.file.skipped.too_long": {
        "ru": "Строка файла {line}: текст длиннее допустимого — строка не записана.",
        "en": "File row {line}: the text is too long — the row was not written.",
    },
    # --- конфликт ----------------------------------------------------------
    "plans.file.conflict.title": {
        "ru": "План на экране изменили после выгрузки файла",
        "en": "The plan on screen was changed after the file was exported",
    },
    "plans.file.conflict.text": {
        "ru": "Ничего не записано. Ниже строки, где файл и экран разошлись: выберите по каждой, "
        "какую версию оставить, или возьмите одну целиком.",
        "en": "Nothing was written. Below are the rows where the file and the screen differ: pick "
        "which version to keep for each, or take one version as a whole.",
    },
    "plans.file.conflict.same": {
        "ru": "Файл и экран не расходятся ни в одной строке — выбирать нечего.",
        "en": "The file and the screen do not differ in any row — nothing to choose.",
    },
    "plans.file.conflict.screen": {"ru": "На экране", "en": "On screen"},
    "plans.file.conflict.file": {"ru": "В файле", "en": "In the file"},
    "plans.file.conflict.keep_screen": {"ru": "Оставить экран", "en": "Keep the screen"},
    "plans.file.conflict.keep_file": {"ru": "Взять файл", "en": "Take the file"},
    "plans.file.conflict.apply_pick": {"ru": "Применить выбор", "en": "Apply my choices"},
    "plans.file.conflict.all_file": {"ru": "Всё из файла", "en": "Everything from the file"},
    "plans.file.conflict.all_screen": {
        "ru": "Всё как на экране",
        "en": "Everything as on screen",
    },
    "plans.file.empty": {"ru": "пусто", "en": "empty"},
    "plans.file.no_date": {"ru": "срок по методике", "en": "methodology deadline"},
    "plans.file.kept_screen": {
        "ru": "Оставлена версия экрана, файл остался в истории версий.",
        "en": "The screen version was kept; the file stays in the version history.",
    },
    "plans.file.stale": {
        "ru": "План на экране снова изменили, пока вы выбирали. Ничего не записано — "
        "выберите заново.",
        "en": "The plan on screen changed again while you were choosing. Nothing was written — "
        "choose again.",
    },
    "plans.file.gone": {
        "ru": "Файл не найден или не разбирается — выберите заново, загрузив его ещё раз.",
        "en": "The file was not found or cannot be read — upload it again.",
    },
    "plans.file.resolved": {
        "ru": "Выбор применён: записано строк {n}.",
        "en": "Your choices were applied: rows written: {n}.",
    },
    "plans.file.failed": {
        "ru": "Не удалось прочитать файл плана. Попробуйте ещё раз.",
        "en": "The plan file could not be read. Please try again.",
    },
}
