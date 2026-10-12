"""Тексты подсказок и обучения мини-аппа (D434).

Подсказка — всплывающий лист по долгому нажатию на элемент с
`data-hint="<ключ>"`; обучение собирается из тех же подсказок. Ключ подсказки —
`walk.hint.<ключ>.title` и `.text`; строки текста разделяются переводом строки
(1–3 короткие). Ключи `walk.hint.left` / `walk.hint.more` заняты полосой
«Осталось» — не называть так подсказки.

Сливаются в каталог обхода (`texts_walk.WALK_TEXTS`) вместе с `texts_app`.
"""

from __future__ import annotations


def _hint(key: str, ru: tuple[str, str], en: tuple[str, str]) -> dict[str, dict[str, str]]:
    return {
        f"walk.hint.{key}.title": {"ru": ru[0], "en": en[0]},
        f"walk.hint.{key}.text": {"ru": ru[1], "en": en[1]},
    }


HINT_TEXTS: dict[str, dict[str, str]] = {
    # ── главная: шаги обучения 1–3 ───────────────────────────────────────
    **_hint(
        "start",
        ("Начать проверку", "Выберите пиццерию, чек-лист и язык. Дальше — обход по зонам."),
        (
            "Start inspection",
            "Pick the pizzeria, the checklist and the language. Then walk the zones.",
        ),
    ),
    **_hint(
        "continue",
        ("Продолжить обход", "Вернуться в идущую проверку — туда, где остановились."),
        ("Continue the walk", "Go back to the inspection in progress, where you left off."),
    ),
    **_hint(
        "lang",
        ("Язык приложения", "RU или EN — на каком языке показывать кнопки и подписи."),
        ("App language", "RU or EN: the language of buttons and labels."),
    ),
    **_hint(
        "settings",
        ("Настройки", "Как завершать проверку и показывать ли подсказки."),
        ("Settings", "How to finish an inspection, and whether to show hints."),
    ),
    # ── обход: шаги обучения 4–9 ─────────────────────────────────────────
    **_hint(
        "zones",
        (
            "Зоны обхода",
            "Значок у зоны: пунктир — не осмотрена, половина — в работе, "
            "галка — чисто, число — столько нарушений.\n"
            "Листайте влево-вправо — откроется соседняя зона.",
        ),
        (
            "Walk zones",
            "The zone icon: dashed — not checked, half — in progress, "
            "tick — clean, number — that many findings.\n"
            "Swipe left or right to open the neighbouring zone.",
        ),
    ),
    **_hint(
        "add",
        (
            "+ Нарушение",
            "Снимите кадр и скажите пару слов. Пункт найдёт система — вы проверите и сохраните.",
        ),
        (
            "+ Issue",
            "Take a photo and add a few words. The system finds the item — you check it and save.",
        ),
    ),
    **_hint(
        "checklist",
        (
            "Чек-лист зоны",
            "Пункты этой зоны. Нажмите пункт — запишете по нему.\nОстальные — по «Показать ещё».",
        ),
        (
            "Zone checklist",
            "The items of this zone. Tap one to record against it.\n"
            "The rest are under “Show more”.",
        ),
    ),
    **_hint(
        "next",
        ("Осмотрено", "Засчитывает зону и ведёт к следующей."),
        ("Checked", "Counts the zone as checked and moves to the next one."),
    ),
    **_hint(
        "info",
        (
            "Сведения",
            "Вопросы для отчёта. Что заполнено здесь, бот потом не спросит.",
        ),
        (
            "Details",
            "Questions for the report. What you fill in here, the bot will not ask again.",
        ),
    ),
    **_hint(
        "finish",
        (
            "Завершить",
            "Сводка или сразу отчёт — как выбрано в настройках.",
        ),
        (
            "Finish",
            "A summary or the report right away, as chosen in settings.",
        ),
    ),
    **_hint(
        "final",
        (
            "Это всё",
            "Зажмите любую кнопку — появится подсказка. Обучение можно пройти снова в настройках.",
        ),
        (
            "That is all",
            "Press and hold any button for a hint. You can take the tour again in settings.",
        ),
    ),
    # ── форма записи и другие кнопки: только по долгому нажатию ──────────
    **_hint(
        "kind",
        ("Вид записи", "Нарушение или рекомендация. Рекомендация — совет без вычета."),
        ("Entry type", "Finding or recommendation. A recommendation is advice, with no deduction."),
    ),
    **_hint(
        "zonepill",
        ("Зона", "Где это найдено. Зона уже выбрана — нажмите, чтобы сменить."),
        ("Zone", "Where it was found. It is already set — tap to change it."),
    ),
    **_hint(
        "photo",
        ("Кадр", "Снимите нарушение или выберите из галереи. Кадров может быть несколько."),
        ("Photo", "Take a photo of the finding or pick one from the gallery. You can add several."),
    ),
    **_hint(
        "find",
        ("Найти пункт", "Система предложит пункт чек-листа по кадру и словам. Решаете вы."),
        (
            "Find the item",
            "The system suggests a checklist item from the photo and words. You decide.",
        ),
    ),
    **_hint(
        "pickitem",
        ("Выбрать пункт", "Если система не нашла нужный — выберите из чек-листа сами."),
        ("Choose item", "If the system missed the right one, pick it from the checklist yourself."),
    ),
    **_hint(
        "level",
        ("Класс нарушения", "D1, D2, D3 — насколько серьёзно. Выбираете вы."),
        ("Finding class", "D1, D2, D3 — how serious it is. You choose."),
    ),
    **_hint(
        "save",
        ("Сохранить", "Запись попадёт в проверку. Позже её можно открыть и поправить."),
        ("Save", "The entry goes into the inspection. You can open and edit it later."),
    ),
    **_hint(
        "translate",
        ("Перевод", "Переведёт ваши слова на язык отчёта. Можно вернуть как было."),
        ("Translate", "Translates your words into the report language. You can undo it."),
    ),
    # ── обучение: оболочка ───────────────────────────────────────────────
    "walk.tour.welcome.title": {
        "ru": "Децимус — проверка пиццерии с телефона",
        "en": "Decimus — a pizzeria inspection from your phone",
    },
    "walk.tour.welcome.text": {
        "ru": "Покажу за минуту, где что. Любую кнопку можно зажать — появится подсказка.",
        "en": "I will show you around in a minute. Press and hold any button for a hint.",
    },
    "walk.tour.welcome.show": {"ru": "Показать", "en": "Show me"},
    "walk.tour.welcome.later": {"ru": "Не сейчас", "en": "Not now"},
    "walk.tour.step": {"ru": "{n} из {total}", "en": "{n} of {total}"},
    "walk.tour.next": {"ru": "Дальше", "en": "Next"},
    "walk.tour.skip": {"ru": "Пропустить", "en": "Skip"},
    "walk.tour.done": {"ru": "Готово", "en": "Done"},
    # ── настройки ────────────────────────────────────────────────────────
    "walk.app.hints": {"ru": "Подсказки", "en": "Hints"},
    "walk.app.hints.on": {"ru": "Вкл", "en": "On"},
    "walk.app.hints.off": {"ru": "Выкл", "en": "Off"},
    "walk.app.tour": {"ru": "Пройти обучение заново", "en": "Take the tour again"},
}
