"""Тексты онбординга (D756, D759 п.6, #1668): «Начало работы», тур по интерфейсу, готовность.

Три части: карточка «Начало работы» на «Главной» партнёра (`onboarding.*`), тур по
интерфейсу (`tour.*`) и строки «Готовность к работе» в карточке пространства у УК
(`readiness.*`). Пункты меню учётки (`menu.start`, `menu.tour`) — рядом с остальными в
этом же модуле, чтобы весь онбординг лежал одним файлом.
"""

from __future__ import annotations

_STEP_KEYS = ("bot", "people", "countries", "units", "checklist", "inspection", "claude")


def _step(
    key: str, ru: tuple[str, str, str], en: tuple[str, str, str]
) -> dict[str, dict[str, str]]:
    """Шаг карточки: название, что и зачем, надпись на кнопке (пусто — кнопки у шага нет)."""
    texts = {
        f"onboarding.step.{key}.title": {"ru": ru[0], "en": en[0]},
        f"onboarding.step.{key}.text": {"ru": ru[1], "en": en[1]},
    }
    if ru[2] and en[2]:
        texts[f"onboarding.step.{key}.cta"] = {"ru": ru[2], "en": en[2]}
    return texts


def _section(key: str, ru: str, en: str) -> dict[str, dict[str, str]]:
    """Одна строка о разделе для тура: название раздела берётся из `section.<key>.title`."""
    return {f"tour.section.{key}": {"ru": ru, "en": en}}


ONBOARDING_TEXTS: dict[str, dict[str, str]] = {
    # ── «Начало работы» ───────────────────────────────────────────────────
    "onboarding.title": {"ru": "Начало работы", "en": "Getting started"},
    "onboarding.lead": {
        "ru": "Несколько шагов, после которых можно проводить проверки.",
        "en": "A few steps before you can run inspections.",
    },
    "onboarding.progress": {"ru": "Сделано {done} из {total}", "en": "{done} of {total} done"},
    "onboarding.state.done": {"ru": "Сделано", "en": "Done"},
    "onboarding.state.todo": {"ru": "Сделайте", "en": "To do"},
    "onboarding.state.waiting": {
        "ru": "Ждём управляющую компанию",
        "en": "Waiting for the management company",
    },
    "onboarding.optional": {"ru": "по желанию", "en": "optional"},
    "onboarding.hide": {"ru": "Скрыть", "en": "Hide"},
    "onboarding.hide_note": {
        "ru": "Вернуть карточку можно из меню учётки: «Начало работы».",
        "en": "You can bring the card back from the account menu: “Getting started”.",
    },
    "onboarding.show": {"ru": "Показывать на главной", "en": "Show on the home page"},
    "onboarding.all_done": {
        "ru": "Всё готово — карточка на главной больше не появится.",
        "en": "All set — the card will no longer appear on the home page.",
    },
    "onboarding.failed": {
        "ru": "Часть сведений не прочиталась, поэтому эти шаги не показаны.",
        "en": "Some details could not be read, so those steps are not shown.",
    },
    **_step(
        "bot",
        (
            "Привяжите бота в Telegram",
            "Проверки проводятся в Telegram. Пока бот не привязан к вашей учётке, он вас не "
            "узнает и откажет.",
            "Привязать бота",
        ),
        (
            "Link the Telegram bot",
            "Inspections are run in Telegram. Until the bot is linked to your account, it will "
            "not recognise you and will refuse.",
            "Link the bot",
        ),
    ),
    **_step(
        "people",
        (
            "Заведите сотрудников",
            "Каждый проверяющий входит под своей учёткой. Добавьте их на вкладке «Люди».",
            "Открыть «Люди»",
        ),
        (
            "Add your team",
            "Every inspector signs in with their own account. Add them on the “People” tab.",
            "Open “People”",
        ),
    ),
    **_step(
        "countries",
        (
            "Страны пространства",
            "Страны за вашим пространством закрепляет управляющая компания. Без них не видны "
            "ни пиццерии, ни проверки.",
            "",
        ),
        (
            "Countries of your space",
            "The management company assigns countries to your space. Without them you see "
            "neither pizzerias nor inspections.",
            "",
        ),
    ),
    **_step(
        "units",
        (
            "Пиццерии в справочнике",
            "Справочник пиццерий ведёт управляющая компания. Проверку можно начать только по "
            "пиццерии из него.",
            "Открыть «Страны»",
        ),
        (
            "Pizzerias in the directory",
            "The management company maintains the pizzeria directory. An inspection can only "
            "start for a pizzeria listed there.",
            "Open “Countries”",
        ),
    ),
    **_step(
        "checklist",
        (
            "Чек-лист для проверок",
            "Проверка идёт по чек-листу. Эталон управляющей компании доступен сразу, свой чек-лист "
            "можно вести в «Методике».",
            "Открыть «Методику»",
        ),
        (
            "A checklist for inspections",
            "An inspection follows a checklist. The management company's reference checklist is "
            "available at once; you can keep your own in “Methodology”.",
            "Open “Methodology”",
        ),
    ),
    **_step(
        "inspection",
        (
            "Проведите первую проверку",
            "В боте: «Начать проверку», пиццерия, затем обход по зонам. На время теста число "
            "проверок на пиццерию ограничено.",
            "",
        ),
        (
            "Run your first inspection",
            "In the bot: “Start inspection”, a pizzeria, then the walk through the zones. During "
            "the trial the number of inspections per pizzeria is limited.",
            "",
        ),
    ),
    **_step(
        "claude",
        (
            "Подключите Claude",
            "Claude читает ваши проверки и помогает с методикой. Загружать проверки через него "
            "партнёру нельзя.",
            "Открыть «Нейросети»",
        ),
        (
            "Connect Claude",
            "Claude reads your inspections and helps with the methodology. A partner cannot "
            "upload inspections through it.",
            "Open “AI assistants”",
        ),
    ),
    # ── Меню учётки ───────────────────────────────────────────────────────
    "menu.help": {"ru": "Помощь", "en": "Help"},
    "menu.start": {"ru": "Начало работы", "en": "Getting started"},
    "menu.tour": {"ru": "Тур по интерфейсу", "en": "Interface tour"},
    # ── Тур по интерфейсу ─────────────────────────────────────────────────
    "tour.next": {"ru": "Дальше", "en": "Next"},
    "tour.prev": {"ru": "Назад", "en": "Back"},
    "tour.done": {"ru": "Готово", "en": "Done"},
    "tour.close": {"ru": "Закрыть тур", "en": "Close the tour"},
    "tour.progress": {
        "ru": "{{{{current}}}} из {{{{total}}}}",
        "en": "{{{{current}}}} of {{{{total}}}}",
    },
    "tour.welcome.title": {"ru": "Покажем, где что находится", "en": "A quick look around"},
    "tour.welcome.text": {
        "ru": "Короткий тур по разделам — около минуты. Повторить его можно из меню учётки: "
        "«Тур по интерфейсу».",
        "en": "A short tour of the sections — about a minute. You can repeat it from the account "
        "menu: “Interface tour”.",
    },
    "tour.group.work": {"ru": "Проверки", "en": "Inspections"},
    "tour.group.stats": {"ru": "Статистика", "en": "Statistics"},
    "tour.group.admin": {
        "ru": "Методика и администрирование",
        "en": "Methodology and administration",
    },
    "tour.tabbar.title": {"ru": "Разделы", "en": "Sections"},
    "tour.search.title": {"ru": "Поиск", "en": "Search"},
    "tour.search.text": {
        "ru": "Найдите проверки по названию пиццерии. Быстрый переход к поиску — ⌘K.",
        "en": "Find inspections by pizzeria name. ⌘K jumps straight to the search.",
    },
    "tour.bell.title": {"ru": "Уведомления", "en": "Notifications"},
    "tour.bell.text": {
        "ru": "Здесь появляется то, что требует вашего внимания.",
        "en": "Whatever needs your attention shows up here.",
    },
    "tour.menu.title": {"ru": "Меню учётки", "en": "Account menu"},
    "tour.menu.text": {
        "ru": "Подключения, язык, тема и выход. Отсюда же можно снова запустить этот тур и "
        "открыть «Начало работы».",
        "en": "Connections, language, theme and sign-out. You can also restart this tour from "
        "here and open “Getting started”.",
    },
    "tour.settings.title": {"ru": "Настройки и Claude", "en": "Settings and Claude"},
    "tour.settings.text": {
        "ru": "В «Настройках» подключаются бот в Telegram, Claude и другие нейросети, "
        "меняются пароль и язык. Что именно Claude может делать, зависит от вашей роли.",
        "en": "Settings is where you link the Telegram bot, Claude and other AI assistants, and "
        "change your password and language. What Claude can do depends on your role.",
    },
    "tour.settings.text_partner": {
        "ru": "В «Настройках» подключаются бот в Telegram, Claude и другие нейросети, "
        "меняются пароль и язык. Claude читает ваши проверки и помогает с методикой; "
        "загружать проверки через него партнёру нельзя.",
        "en": "Settings is where you link the Telegram bot, Claude and other AI assistants, and "
        "change your password and language. Claude reads your inspections and helps with the "
        "methodology; a partner cannot upload inspections through it.",
    },
    "tour.settings.link": {"ru": "Открыть «Нейросети»", "en": "Open “AI assistants”"},
    **_section(
        "overview",
        "что требует внимания, итоги проверок и рейтинги",
        "what needs attention, inspection totals and ratings",
    ),
    **_section(
        "registry",
        "все проверки, отбор и карточка проверки",
        "all inspections, filters and the inspection card",
    ),
    **_section("calendar", "проверки по дням", "inspections by day"),
    **_section("actions", "предписания и ответы на них", "orders and the replies to them"),
    **_section("osb", "очередь предписаний сети", "the network's queue of orders"),
    **_section(
        "country",
        "страны и пиццерии, история каждой пиццерии",
        "countries and pizzerias, the history of each pizzeria",
    ),
    **_section(
        "ratings",
        "оценки гостей РС и РКО, карты и агрегаторы",
        "guest ratings, maps and aggregators",
    ),
    **_section("quality", "здоровье пиццерий за месяц", "pizzeria health for the month"),
    **_section("training", "кто из пиццерий прошёл обучение", "which pizzerias completed training"),
    **_section(
        "admin", "чек-лист, по которому идёт проверка", "the checklist an inspection follows"
    ),
    **_section(
        "administration",
        "люди и доступ, ваше пространство",
        "people and access, your space",
    ),
    # ── Готовность пространства (карточка пространства у УК) ──────────────
    "readiness.title": {"ru": "Готовность к работе", "en": "Ready to work"},
    "readiness.note": {
        "ru": "Что нужно, чтобы партнёр мог провести первую проверку.",
        "en": "What a partner needs to run a first inspection.",
    },
    "readiness.countries": {"ru": "Страны закреплены", "en": "Countries assigned"},
    "readiness.units": {"ru": "Пиццерии в справочнике", "en": "Pizzerias in the directory"},
    "readiness.checklist": {"ru": "Чек-лист открыт", "en": "Checklist available"},
    "readiness.yes": {"ru": "есть", "en": "yes"},
    "readiness.no": {"ru": "нет", "en": "no"},
    "readiness.unknown": {"ru": "не прочиталось", "en": "could not be read"},
    "readiness.ready": {"ru": "Пространство готово.", "en": "The space is ready."},
}

#: Ключи шагов карточки — сверяются тестом с `onboarding.py`.
STEP_KEYS = _STEP_KEYS
