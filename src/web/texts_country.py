"""Тексты экрана «Страны» (D467, D504, D536): колонка, шапка, плитки, пиццерии, панели.

Отдельным модулем, а не строками в `texts.py`: тот уже длиннее предела файла.
Сливаются в общий каталог (`texts.TEXTS`) — `t()` знает один словарь.
"""

from __future__ import annotations

COUNTRY_TEXTS: dict[str, dict[str, str]] = {
    "country.search": {"ru": "Поиск страны или пиццерии", "en": "Search country or pizzeria"},
    "country.rail.average": {"ru": "средняя {avg}", "en": "average {avg}"},
    "country.rail.no_inspections": {
        "ru": "проверок за период нет",
        "en": "no inspections in the period",
    },
    "country.rail.group": {
        "ru": "сводка по группе · стран: {n}",
        "en": "group summary · countries: {n}",
    },
    "country.dev.label": {"ru": "Девелопер", "en": "Developer"},
    "country.dev.all": {"ru": "Все", "en": "All"},
    "country.dev.countries": {"ru": "Стран: {n}", "en": "Countries: {n}"},
    "country.dev.note": {
        "ru": "РС, РКО и оценки на картах по группе стран не складываются из средних: "
        "они — на экране каждой страны.",
        "en": "RS, CX and map ratings are not summed from country averages: "
        "see them on each country's screen.",
    },
    "country.facts.developer": {"ru": "Девелопер: {name}", "en": "Developer: {name}"},
    "country.facts.partner": {"ru": "Партнёр: {name}", "en": "Partner: {name}"},
    "country.facts.partners": {"ru": "Партнёры: {names}", "en": "Partners: {names}"},
    "country.facts.partners_more": {
        "ru": "Партнёры: {names} и ещё {n}",
        "en": "Partners: {names} and {n} more",
    },
    "country.facts.units": {"ru": "Пиццерий: {total}", "en": "Pizzerias: {total}"},
    "country.figures.title": {"ru": "Ключевые цифры", "en": "Key figures"},
    "country.tile.average": {"ru": "Средняя", "en": "Average"},
    "country.tile.inspections": {"ru": "по проверкам: {n}", "en": "over {n} inspections"},
    "country.tile.checked": {"ru": "Проверено", "en": "Inspected"},
    "country.tile.of": {"ru": "{checked} из {total}", "en": "{checked} of {total}"},
    "country.tile.units": {"ru": "пиццерий", "en": "pizzerias"},
    "country.tile.critical": {"ru": "Критические", "en": "Critical"},
    "country.tile.letters": {"ru": "Буквы", "en": "Grades"},
    "country.tile.rs.hint": {
        "ru": "Среднее РС по пиццериям страны (как на «Рейтингах»)",
        "en": "Average RS across the country's pizzerias (as on Ratings)",
    },
    "country.tile.rko.hint": {
        "ru": "Среднее РКО по пиццериям страны (как на «Рейтингах»)",
        "en": "Average CX across the country's pizzerias (as on Ratings)",
    },
    "country.none.period": {
        "ru": "За период проверок не было.",
        "en": "No inspections in the period.",
    },
    "country.none.all_time": {"ru": "Показать за всё время", "en": "Show all time"},
    "country.none.ever": {
        "ru": "Проверок в этой стране ещё не было.",
        "en": "There have been no inspections in this country yet.",
    },
    "country.hurt.title": {"ru": "Где болит", "en": "Pain points"},
    "country.hurt.systemic": {
        "ru": "Нарушено сразу в нескольких пиццериях",
        "en": "Violated in several pizzerias at once",
    },
    "country.hurt.processes": {
        "ru": "Где страна теряет больше всего",
        "en": "Where the country loses most",
    },
    "country.units.title": {"ru": "Пиццерии", "en": "Pizzerias"},
    "country.units.last": {"ru": "последняя {date}", "en": "latest {date}"},
    "country.units.never": {"ru": "не проверяли", "en": "never inspected"},
    "country.units.not_in_period": {"ru": "за период нет", "en": "none in the period"},
    "country.units.empty": {
        "ru": "В стране нет ни одной пиццерии.",
        "en": "There are no pizzerias in this country.",
    },
    "country.units.reach": {
        "ru": "Проверены хоть раз: {done} из {total} · ни разу: {never}",
        "en": "Inspected at least once: {done} of {total} · never: {never}",
    },
    "country.units.closed": {"ru": "Закрытые: {n}", "en": "Closed: {n}"},
    "country.units.profiles_failed": {
        "ru": "Свод пиццерий не прочитался: партнёр, адрес и статус пока не показаны.",
        "en": "The pizzeria register could not be read: partner, address and status are not shown.",
    },
    "country.units.ratings_failed": {
        "ru": "Оценки РС / РКО не прочитались.",
        "en": "RS / CX ratings could not be read.",
    },
    "country.units.maps_failed": {
        "ru": "Оценки на картах не прочитались.",
        "en": "Map ratings could not be read.",
    },
    "country.col.unit": {"ru": "Пиццерия", "en": "Pizzeria"},
    "country.col.last": {"ru": "Последняя проверка", "en": "Latest inspection"},
    "country.col.country": {"ru": "Страна", "en": "Country"},
    "country.col.average": {"ru": "Средняя", "en": "Average"},
    "country.col.checked": {"ru": "Проверено", "en": "Inspected"},
    "country.col.inspections": {"ru": "Проверок", "en": "Inspections"},
    "country.panel.facts": {"ru": "Сведения", "en": "Details"},
    "country.panel.address": {"ru": "Адрес", "en": "Address"},
    "country.panel.ratings": {"ru": "Рейтинги", "en": "Ratings"},
    "country.panel.history": {"ru": "Последние проверки", "en": "Latest inspections"},
    "country.panel.history_empty": {"ru": "Проверок не было.", "en": "No inspections yet."},
    "country.panel.no_card": {
        "ru": "Карточки пиццерии нет: точки нет в справочнике, она есть только в своде.",
        "en": "No pizzeria card: the unit is not in the directory, only in the register.",
    },
    # ── D536: «Мои страны», шапка, пиццерия справа, проверки, настройки ──
    "country.mine.title": {"ru": "Мои страны", "en": "My countries"},
    "country.mine.all": {"ru": "Все страны", "en": "All countries"},
    "country.mine.some": {"ru": "{n} из {total}", "en": "{n} of {total}"},
    "country.mine.hint": {
        "ru": "Отметьте страны, которые нужны вам, — остальные уйдут с экрана. Выбор сохраняется "
        "в вашем профиле и действует на всех устройствах.",
        "en": "Tick the countries you work with: the rest leave the screen. The choice is saved "
        "in your profile and applies on every device.",
    },
    "country.mine.clusters": {"ru": "Кластеры", "en": "Clusters"},
    "country.mine.save": {"ru": "Показывать выбранные", "en": "Show selected"},
    "country.mine.reset": {"ru": "Все страны", "en": "All countries"},
    "country.mine.empty": {
        "ru": "Не отмечено ни одной страны — отбор не применится.",
        "en": "No country ticked — the filter will not apply.",
    },
    "country.head.developer": {"ru": "Девелопер", "en": "Developer"},
    "country.head.partners": {"ru": "Партнёры", "en": "Partners"},
    "country.head.units": {"ru": "Пиццерии", "en": "Pizzerias"},
    "country.head.none": {"ru": "не указан", "en": "not set"},
    "country.head.none_partners": {"ru": "не указаны", "en": "not set"},
    "country.badge.open": {"ru": "работают {n}", "en": "open {n}"},
    "country.badge.pipeline": {"ru": "открываются {n}", "en": "opening {n}"},
    "country.badge.closed": {"ru": "закрыты {n}", "en": "closed {n}"},
    "country.badge.total": {"ru": "{n} всего", "en": "{n} total"},
    "country.settings.open": {"ru": "Карточка страны", "en": "Country card"},
    "country.back": {"ru": "К стране", "en": "Back to the country"},
    "country.unit.facts.city": {"ru": "Город", "en": "City"},
    "country.unit.facts.partner": {"ru": "Партнёр", "en": "Partner"},
    "country.unit.facts.stage": {"ru": "Стадия", "en": "Stage"},
    "country.unit.facts.address": {"ru": "Адрес", "en": "Address"},
    "country.unit.facts.opened": {"ru": "Открыта", "en": "Opened"},
    "country.unit.facts.closed": {"ru": "Закрыта", "en": "Closed"},
    "country.unit.facts.status": {"ru": "Статус", "en": "Status"},
    "country.unit.tile.last": {"ru": "Последняя проверка", "en": "Latest inspection"},
    "country.unit.tile.last_note": {"ru": "от {date}", "en": "on {date}"},
    "country.unit.tile.last_none": {"ru": "не проверяли", "en": "never inspected"},
    "country.unit.tile.trend": {"ru": "Движение", "en": "Trend"},
    "country.unit.tile.trend_note": {
        "ru": "против предыдущей проверки",
        "en": "versus the previous inspection",
    },
    "country.unit.tile.trend_none": {"ru": "мало проверок", "en": "too few inspections"},
    "country.unit.tile.maps": {"ru": "Оценки на картах", "en": "Map ratings"},
    "country.unit.tile.ratings": {"ru": "Рейтинги", "en": "Ratings"},
    "country.unit.no_card": {
        "ru": "Пиццерии нет в справочнике: она есть только в своде, проверок и карточки у неё нет.",
        "en": "The pizzeria is not in the directory, only in the register: no inspections or card.",
    },
    "country.list.title": {"ru": "Проверки", "en": "Inspections"},
    "country.list.country_hint": {"ru": "страны за период", "en": "of the country in the period"},
    "country.list.unit_hint": {"ru": "пиццерии, последние", "en": "of the pizzeria, latest"},
    "country.list.empty_period": {
        "ru": "За период проверок нет.",
        "en": "No inspections in the period.",
    },
    "country.list.empty_unit": {"ru": "Проверок не было.", "en": "No inspections yet."},
    "country.added": {
        "ru": "Пиццерия добавлена. Проверок у неё пока нет.",
        "en": "The pizzeria was added. It has no inspections yet.",
    },
    "country.settings.title": {"ru": "Карточка страны", "en": "Country card"},
    "country.card.people": {"ru": "Партнёр и девелопер", "en": "Partner and developer"},
    "country.card.legal": {
        "ru": "Юрлица партнёров в своде пиццерий",
        "en": "Partner legal entities in the pizzeria register",
    },
    "country.card.space": {"ru": "Партнёр в Decimus", "en": "Partner in Decimus"},
    "country.card.edit": {"ru": "Изменить", "en": "Change"},
    "country.card.unset": {"ru": "не задан", "en": "not set"},
    "country.card.units_n": {"ru": "пиццерий: {n}", "en": "pizzerias: {n}"},
    "country.card.units": {"ru": "Пиццерии", "en": "Pizzerias"},
    "country.card.profiles_failed": {
        "ru": "Свод пиццерий сейчас не прочитался: адресов, дат и площадей ниже нет.",
        "en": "The pizzeria register could not be read: addresses, dates and sizes "
        "are missing below.",
    },
    "country.card.no_units": {
        "ru": "В стране пока нет пиццерий.",
        "en": "No pizzerias in this country yet.",
    },
    "country.card.col.name": {"ru": "Название", "en": "Name"},
    "country.card.col.address": {"ru": "Город и адрес", "en": "City and address"},
    "country.card.col.stage": {"ru": "Стадия", "en": "Stage"},
    "country.card.col.dates": {"ru": "Открытие", "en": "Opening"},
    "country.card.col.scores": {"ru": "Оценки", "en": "Scores"},
    "country.card.col.last": {"ru": "Последняя проверка", "en": "Last inspection"},
    "country.card.never": {"ru": "не проверяли", "en": "never"},
    "country.card.auditors": {"ru": "Аудиторы за период", "en": "Auditors in the period"},
    "country.card.auditors_none": {
        "ru": "за период проверок нет",
        "en": "no inspections in the period",
    },
    "country.card.langs": {"ru": "Языки отчёта", "en": "Report languages"},
    "country.card.langs_hint": {
        "ru": "Бот предлагает их при сборке отчёта; они же — язык письма по умолчанию.",
        "en": "The bot offers them when building a report; they are also the default "
        "letter language.",
    },
    "country.langs.custom": {"ru": "заданы для страны", "en": "set for the country"},
    "country.langs.default": {
        "ru": "как по умолчанию",
        "en": "as default",
    },
    "country.langs.hint": {
        "ru": "Отметьте языки, на которых аудитор может напечатать отчёт этой страны. "
        "Не меньше одного, только языки методики.",
        "en": "Tick the languages an auditor may print this country's report in. "
        "At least one, methodology languages only.",
    },
    "country.langs.reset": {"ru": "Как по умолчанию", "en": "Reset to default"},
    "country.langs.invalid": {
        "ru": "Языки не сохранены: отметьте хотя бы один язык из методики.",
        "en": "Languages not saved: tick at least one methodology language.",
    },
    "country.card.agg_failed": {
        "ru": "Оценки на площадках доставки сейчас не прочитались.",
        "en": "Delivery platform scores could not be read right now.",
    },
    "country.card.restaurant_on": {"ru": "ресторан", "en": "restaurant"},
    "country.card.delivery_on": {"ru": "доставка", "en": "delivery"},
    "country.card.closed_on": {"ru": "закрыта", "en": "closed"},
    "country.card.seats": {"ru": "мест: {n}", "en": "{n} seats"},
    "country.card.inspections_n": {"ru": "проверок: {n}", "en": "inspections: {n}"},
    "country.settings.developer": {"ru": "Девелопер", "en": "Developer"},
    "country.settings.developer_hint": {
        "ru": "Имя из справочника рейтингов: по нему страны собираются в группу девелопера. "
        "Пустое поле снимает девелопера.",
        "en": "The name from the ratings directory: countries are grouped by it. "
        "An empty field clears the developer.",
    },
    "country.settings.partner": {"ru": "Партнёр страны", "en": "Country partner"},
    "country.settings.partner_hint": {
        "ru": "Пространство партнёра, которому принадлежит страна: он видит её пиццерии "
        "и проверки. "
        "Страна — один партнёр; закреплённую страну отсюда не перенести.",
        "en": "The partner space that owns the country: it sees the pizzerias and inspections. "
        "A country belongs to one partner; an assigned country cannot be moved from here.",
    },
    "country.settings.partner_none": {
        "ru": "Страна не закреплена за партнёром.",
        "en": "The country is not assigned to a partner.",
    },
    "country.settings.partner_pick": {"ru": "Пространство", "en": "Space"},
    "country.settings.partner_assign": {"ru": "Закрепить", "en": "Assign"},
    "country.settings.partner_failed": {
        "ru": "Пространства партнёров не прочитались.",
        "en": "Partner spaces could not be read.",
    },
    "country.settings.save": {"ru": "Сохранить", "en": "Save"},
    "country.settings.saved": {"ru": "Сохранено.", "en": "Saved."},
    "country.settings.failed": {
        "ru": "Не сохранилось: страны нет в справочнике, имя слишком длинное или страна уже у "
        "другого партнёра.",
        "en": "Not saved: the country is not in the directory, the name is too long or the "
        "country already belongs to another partner.",
    },
    "country.block.partner": {"ru": "Партнёр", "en": "Partner"},
    "country.block.partner_note": {
        "ru": "Пространство, которому принадлежит страна: оно видит её пиццерии и проверки.",
        "en": "The space that owns the country: it sees its pizzerias and inspections.",
    },
    "country.block.partner_locked": {
        "ru": "Страна принадлежит одному партнёру; закреплённую отсюда не перенести.",
        "en": "A country belongs to one partner; an assigned one cannot be moved from here.",
    },
    "country.block.developer": {"ru": "Девелопер", "en": "Developer"},
    "country.block.developer_note": {
        "ru": "По имени страны собираются в группу девелопера на экранах рейтингов.",
        "en": "Countries are grouped by this name on the ratings screens.",
    },
    "country.block.langs": {"ru": "Языки отчёта", "en": "Report languages"},
    "country.block.langs_note": {
        "ru": "Бот предлагает их при сборке отчёта; они же язык письма по умолчанию.",
        "en": "The bot offers them when building a report; also the default letter language.",
    },
    "country.block.contract": {"ru": "Договор", "en": "Agreement"},
    "country.block.contract_note": {
        "ru": "Юрлицо партнёра, договор и контакты по ДКК.",
        "en": "Partner legal entity, agreement and agreement contacts.",
    },
    "country.block.assign": {"ru": "Назначить", "en": "Assign"},
    "country.block.fill": {"ru": "Заполнить", "en": "Fill in"},
    "country.settings.people": {
        "ru": "Люди и пространства партнёров ведутся во вкладках «Люди» и «Пространства "
        "партнёров» этого раздела.",
        "en": "People and partner spaces are managed in the People and Partner spaces "
        "tabs of this section.",
    },
    "country.settings.edit_in_admin": {
        "ru": "Изменить в «Администрировании»",
        "en": "Change in Administration",
    },
    "country.contract.title": {"ru": "Договор", "en": "Agreement"},
    "country.contract.legal_name": {"ru": "Юрлицо партнёра", "en": "Partner legal entity"},
    "country.contract.registration_country": {
        "ru": "Страна регистрации",
        "en": "Country of registration",
    },
    "country.contract.company_number": {"ru": "Номер компании", "en": "Company number"},
    "country.contract.address": {"ru": "Адрес", "en": "Address"},
    "country.contract.agreement": {
        "ru": "Договор (название и дата)",
        "en": "Agreement (title and date)",
    },
    "country.contract.dkk_emails": {"ru": "Контакты по ДКК", "en": "Agreement contacts"},
    "country.contract.dkk_hint": {
        "ru": "Почты через запятую или с новой строки. Их форма предписания подставляет в "
        "«Кому». Договор здесь только записан текстом, его условия система не знает.",
        "en": "Email addresses separated by commas or new lines. The notice form fills them "
        'into "To". The agreement is only recorded as text; the system does not know its terms.',
    },
    "country.contract.none": {
        "ru": "Договор страны не заполнен. Пока контактов по ДКК нет, форма предписания "
        "подставляет адресатов прошлой отправки.",
        "en": "No agreement recorded for this country. Until there are agreement contacts, "
        "the notice form fills in the recipients of the last notice sent.",
    },
    "country.contract.read_failed": {
        "ru": "Договор не прочитался. Обновите страницу позже.",
        "en": "The agreement could not be read. Reload the page later.",
    },
    "country.contract.updated": {
        "ru": "Правил: {who} · {when}",
        "en": "Edited by {who} · {when}",
    },
    "country.contract.add": {"ru": "Добавить строку договора", "en": "Add an agreement row"},
    "country.contract.add_first": {"ru": "Заполнить договор", "en": "Fill in the agreement"},
    "country.contract.delete": {"ru": "Удалить строку", "en": "Delete this row"},
    "country.contract.invalid": {
        "ru": "Не сохранилось: проверьте почты (каждая должна быть адресом вида a@b.com) "
        "и заполните хотя бы одно поле. Строки не длиннее 300 знаков.",
        "en": "Not saved: check the emails (each must look like a@b.com) and fill in at "
        "least one field. Lines are at most 300 characters.",
    },
}
