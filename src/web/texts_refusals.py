"""Тексты отказов раздела «Методика»: хранилище методики и формы экрана (#475).

Отдельным модулем, а не строками в `texts.py`: тот уже длиннее предела файла.
Сливаются в общий каталог (`texts.TEXTS`) — `t()` знает один словарь.

**Ключ — код отказа, а не формулировка.** Хранилище методики (`src/mcp`)
отказывает по-русски, потому что его главный читатель — агент партнёра по MCP,
и язык ответа ему никто не менял. Тот же отказ веб показывает человеку на языке
интерфейса: дверь кладёт в исключение код и параметры (`McpError.refusal`,
`McpError.params`), а фраза берётся здесь по ключу `refusal.<код>`. Параметры
подставляются как есть: код пункта и слова движка не переводятся.

Фразы здесь — для человека с экрана, а не для агента: имён инструментов MCP
(`checklist_versions`, `version_name`) в них нет, вместо них — что сделать на
экране. Что каждый код из `src/mcp` имеет текст на обоих языках, а параметры
фразы совпадают с параметрами отказа, держит `tests/test_web_refusal_texts.py`.

`refusal.web.*` — отказы самого экрана (разбор ввода формы), не двери.
"""

from __future__ import annotations

REFUSAL_TEXTS: dict[str, dict[str, str]] = {
    # --- чек-листы: заведение, карточка, прод, бот ---------------------------
    "refusal.checklist_exists": {
        "ru": "Чек-лист «{code}» в пространстве «{space}» уже есть. Код не меняется никогда — "
        "им чек-лист связан с проверками; заведите чек-лист под другим кодом.",
        "en": "Checklist “{code}” already exists in space “{space}”. A code never changes — "
        "it links the checklist to its inspections; create the checklist under another code.",
    },
    "refusal.code_is_reference": {
        "ru": "Код «{code}» — код чек-листа эталона УК: эталон виден в вашем пространстве под "
        "этим кодом. Заведите свой чек-лист под другим кодом.",
        "en": "Code “{code}” belongs to the reference checklist, which is visible in your space "
        "under that code. Create your checklist under another code.",
    },
    "refusal.code_taken_by_partner": {
        "ru": "Код «{code}» занят чек-листом пространства партнёра. Коды эталона и чек-листов "
        "партнёров не повторяются: партнёр видит эталон рядом со своими.",
        "en": "Code “{code}” is taken by a checklist in a partner's space. Reference and partner "
        "checklist codes never repeat: a partner sees the reference next to their own.",
    },
    "refusal.names_required": {
        "ru": "У чек-листа должны быть оба названия — русское и английское: показывается "
        "чек-лист названием на языке интерфейса, а не кодом.",
        "en": "A checklist needs both names, Russian and English: it is shown by its name "
        "in the interface language, not by its code.",
    },
    "refusal.blank_incomplete": {
        "ru": "Бланк методики в репозитории неполный: не хватает {missing}. Новый чек-лист "
        "рождается из него, и завести его не с чего.",
        "en": "The methodology blank in the repository is incomplete: {missing} is missing. "
        "A new checklist is born from it, so there is nothing to create it from.",
    },
    "refusal.blank_rejected": {
        "ru": "Движок не принимает бланк методики — завести чек-лист с нуля нечем. "
        "Движок сказал: {engine}",
        "en": "The engine rejects the methodology blank, so a checklist cannot be created "
        "from scratch. The engine said: {engine}",
    },
    "refusal.checklist_missing": {
        "ru": "Чек-листа «{code}» в пространстве «{space}» нет. Перечень чек-листов — "
        "в разделе «Чек-листы».",
        "en": "There is no checklist “{code}” in space “{space}”. The list of checklists "
        "is in the Checklists section.",
    },
    "refusal.applied_cannot_retire": {
        "ru": "Чек-лист «{code}» применён к проду — по нему идут проверки, и снять его значит "
        "считать по снятой методике. Сначала примените к проду другой.",
        "en": "Checklist “{code}” is applied to production — inspections run on it, and retiring "
        "it would mean scoring by a retired methodology. Apply another one to production first.",
    },
    "refusal.retired_not_applicable": {
        "ru": "Чек-лист «{code}» снят, а снятый к проду не применяется. Верните его в работу, "
        "если снят он по ошибке.",
        "en": "Checklist “{code}” is retired, and a retired checklist cannot be applied to "
        "production. Put it back to work if it was retired by mistake.",
    },
    "refusal.no_published_edition": {
        "ru": "У чек-листа «{code}» нет опубликованной версии — применять к проду нечего.",
        "en": "Checklist “{code}” has no published version — there is nothing to apply "
        "to production.",
    },
    "refusal.no_violation_items": {
        "ru": "В чек-листе «{code}» нет ни одного пункта, по которому бывает нарушение. Такой "
        "чек-лист дал бы партнёру 100% и высшую оценку без единого вопроса. Заведите пункты "
        "и примените снова.",
        "en": "Checklist “{code}” has no item that can be violated. Such a checklist would give "
        "the partner 100% and the top grade without a single question. Add items and apply "
        "again.",
    },
    "refusal.apply_only_reference": {
        "ru": "К проду применяет только УК: указатель прода один на всю сеть. В пространстве "
        "партнёра доступ в боте задаётся галочкой «в боте».",
        "en": "Only the management company applies a checklist to production: there is one "
        "production pointer for the whole network. In a partner's space, bot access is set by "
        "the “in the bot” checkbox.",
    },
    "refusal.draft_not_for_bot": {
        "ru": "Чек-лист «{code}» — черновик. В бот открывается только чек-лист в работе: "
        "черновик ещё правят, и аудитор получил бы вопросы, которых завтра не будет.",
        "en": "Checklist “{code}” is a draft. Only a checklist in use is opened in the bot: "
        "a draft is still being edited, and the auditor would get questions that may be gone "
        "tomorrow.",
    },
    # --- имена и коды ---------------------------------------------------------
    "refusal.set_name_has_date": {
        "ru": "Имя набора «{name}» кончается датой. Дату версии ставит хранилище само — "
        "назовите набор без даты, например «imf».",
        "en": "Set name “{name}” ends with a date. The store adds the version date itself — "
        "name the set without a date, for example “imf”.",
    },
    "refusal.set_name_invalid": {
        "ru": "Имя набора «{name}» не годится: ожидаются строчные латинские буквы, цифры, "
        "дефис и подчёркивание, до 32 знаков (например «imf»).",
        "en": "Set name “{name}” is not valid: use lowercase Latin letters, digits, hyphens "
        "and underscores, up to 32 characters (for example “imf”).",
    },
    "refusal.set_name_missing": {
        "ru": "У методики нет имени набора: она ещё никем не издана. Правка даёт версию с "
        "датой, а дата без имени набора — не идентификатор. Назовите набор в поле имени "
        "набора, например «imf»; дальше имя подхватится само.",
        "en": "The methodology has no set name: nobody has issued it yet. An edit produces a "
        "dated version, and a date without a set name is not an identifier. Enter a set name, "
        "for example “imf”; it will be picked up automatically after that.",
    },
    "refusal.bad_version": {
        "ru": "«{version}» не может быть именем версии. Версия выглядит как "
        "«imf-2026-09-03-3f5a91b2c7d0» — имя набора, дата и отпечаток данных.",
        "en": "“{version}” cannot be a version name. A version looks like "
        "“imf-2026-09-03-3f5a91b2c7d0” — set name, date and data fingerprint.",
    },
    "refusal.bad_code": {
        "ru": "«{code}» не похоже на код: ожидаются латинские буквы, цифры и подчёркивание "
        "(например «CLN05» или «fridge»).",
        "en": "“{code}” does not look like a code: use Latin letters, digits and underscores "
        "(for example “CLN05” or “fridge”).",
    },
    # --- версии ---------------------------------------------------------------
    "refusal.version_missing": {
        "ru": "Версии методики «{version}» в хранилище нет.",
        "en": "There is no methodology version “{version}” in the store.",
    },
    "refusal.item_missing": {
        "ru": "Пункта «{code}» нет в методике версии {version}.",
        "en": "There is no item “{code}” in methodology version {version}.",
    },
    "refusal.edit_changed_nothing": {
        "ru": "Правка ничего не изменила в методике: отпечаток данных остался прежним "
        "({fingerprint}). Новой версии не будет.",
        "en": "The edit changed nothing in the methodology: the data fingerprint is the same "
        "({fingerprint}). No new version will be written.",
    },
    "refusal.version_repeated": {
        "ru": "Версия {version} уже есть, и получилась она ровно этой правкой от версии "
        "{base_version}: то же самое уже сделано, повторять нечего.",
        "en": "Version {version} already exists and was produced by exactly this edit from "
        "version {base_version}: it has already been done, there is nothing to repeat.",
    },
    "refusal.version_reverted": {
        "ru": "Новой версии не будет, и правка не записана: методика после неё совпадает с "
        "версией {version}, которая уже есть. Это возврат к её состоянию — от основы "
        "{base_version} правка отличается. Чтобы движок считал по этому состоянию, опубликуйте "
        "{version}; чтобы записать его отдельной версией, назовите другой набор.",
        "en": "No new version, and the edit is not recorded: after it the methodology matches "
        "version {version}, which already exists. This is a return to its state — the edit "
        "differs from base {base_version}. To have the engine score by this state, publish "
        "{version}; to record it as a separate version, use another set name.",
    },
    "refusal.edit_refused": {
        "ru": "Правка отклонена, новой версии не появилось. Движок сказал: {engine}",
        "en": "The edit was rejected, no new version was created. The engine said: {engine}",
    },
    # --- правка: аргументы ------------------------------------------------------
    "refusal.note_too_long": {
        "ru": "Пояснение к правке длиннее {max} знаков. В журнале нужна причина правки одной "
        "фразой.",
        "en": "The edit note is longer than {max} characters. The log needs the reason for the "
        "edit in one sentence.",
    },
    "refusal.unknown_item_kind": {
        "ru": "Вид пункта «{kind}» неизвестен, ожидается один из: {kinds}. Выключается пункт "
        "отдельной кнопкой, а не видом.",
        "en": "Item kind “{kind}” is unknown, expected one of: {kinds}. An item is switched off "
        "with its own button, not by its kind.",
    },
    "refusal.no_shares": {
        "ru": "Не названо ни одной доли зоны. Доли задаются набором сразу и складываются в 100%.",
        "en": "No zone share was given. Shares are set together and add up to 100%.",
    },
    "refusal.share_not_number": {
        "ru": "Доля зоны {zone} должна быть числом процентов, а пришло «{value}».",
        "en": "The share of zone {zone} must be a percentage, but got “{value}”.",
    },
    "refusal.no_rates": {
        "ru": "Не названо ни одной ставки: укажите начальный процент, D1, D2 или множитель "
        "повтора.",
        "en": "No rate was given: enter the starting percentage, D1, D2 or the repeat multiplier.",
    },
    # --- окружение: каталог методики и движок -------------------------------
    "refusal.live_missing": {
        "ru": "Каталог методики на сервере не найден — хранилищу версий не с чего начать. "
        "Подробности — в логе сервера.",
        "en": "The methodology folder was not found on the server, so the version store has "
        "nothing to start from. Details are in the server log.",
    },
    "refusal.live_incomplete": {
        "ru": "Каталог методики на сервере неполный: не хватает {missing}. Подробности — "
        "в логе сервера.",
        "en": "The methodology folder on the server is incomplete: {missing} is missing. "
        "Details are in the server log.",
    },
    "refusal.engine_reads_outside_store": {
        "ru": "Движок читает методику не из хранилища версий: публикация переставит указатель "
        "«{link}», а движок её не увидит. Это настройка сервера — подробности в логе сервера.",
        "en": "The engine reads the methodology outside the version store: publishing would "
        "move the “{link}” pointer, and the engine would not see it. This is a server setting — "
        "details are in the server log.",
    },
    "refusal.engine_died": {
        "ru": "Движок не дал ответа: {script} умер до ответа (попыток: {attempts}). Это отказ "
        "сервера, а не методики — повторите правку.",
        "en": "The engine gave no answer: {script} died before answering (attempts: {attempts}). "
        "This is a server failure, not a methodology one — repeat the edit.",
    },
    "refusal.engine_silent": {
        "ru": "Движок не дал ответа: {script} вышел с кодом {exit_code} и не сказал ни слова. "
        "Это отказ сервера, а не методики — повторите правку.",
        "en": "The engine gave no answer: {script} exited with code {exit_code} without a word. "
        "This is a server failure, not a methodology one — repeat the edit.",
    },
    "refusal.engine_timeout": {
        "ru": "Движок не дал ответа: {script} не уложился в {seconds} с. Это отказ сервера, "
        "а не методики — повторите правку.",
        "en": "The engine gave no answer: {script} did not finish within {seconds} s. This is "
        "a server failure, not a methodology one — repeat the edit.",
    },
    "refusal.engine_killed": {
        "ru": "Движок не дал ответа: {script} снят сигналом {signal}. Это отказ сервера, "
        "а не методики — повторите правку.",
        "en": "The engine gave no answer: {script} was stopped by signal {signal}. This is "
        "a server failure, not a methodology one — repeat the edit.",
    },
    # --- порядок обхода (#504) -----------------------------------------------------
    "refusal.route_not_list": {
        "ru": "Порядок обхода ожидается списком кодов, а пришла одна строка «{value}».",
        "en": "The route order must be a list of codes, but a single string came: “{value}”.",
    },
    "refusal.route_code_twice": {
        "ru": "Код «{code}» назван в порядке обхода дважды — одно из двух мест ошибочно.",
        "en": "Code “{code}” appears twice in the route order — one of the two places is wrong.",
    },
    "refusal.route_unknown_zones": {
        "ru": "В порядке обхода названы зоны, которых в методике нет: {unknown}. Зоны этой "
        "версии: {known}.",
        "en": "The route order names zones that are not in the methodology: {unknown}. Zones of "
        "this version: {known}.",
    },
    "refusal.route_unknown_items": {
        "ru": "В порядке обхода названы пункты, которых в методике нет: {unknown}. Пунктов в "
        "этой версии: {count}.",
        "en": "The route order names items that are not in the methodology: {unknown}. Items in "
        "this version: {count}.",
    },
    "refusal.route_unreadable": {
        "ru": "Маршрут обхода ({file}) в этой версии методики не читается. Разбор сказал: {detail}",
        "en": "The route ({file}) in this methodology version cannot be read. The parser said: "
        "{detail}",
    },
    "refusal.route_arrange_refused": {
        "ru": "Порядок обхода не выстраивается. Разбор сказал: {detail}",
        "en": "The route order cannot be arranged. The parser said: {detail}",
    },
    "refusal.route_parsed_otherwise": {
        "ru": "После правки разбор видит порядок {seen}, а не {expected}. Правка записана не "
        "так, как задумана.",
        "en": "After the edit the parser sees the order {seen}, not {expected}. The edit was "
        "not recorded as intended.",
    },
    "refusal.route_arranged_otherwise": {
        "ru": "После правки аудитор пойдёт по порядку {got}, а не {wanted}. Правка записана не "
        "так, как задумана.",
        "en": "After the edit the auditor would follow the order {got}, not {wanted}. The edit "
        "was not recorded as intended.",
    },
    "refusal.route_nothing_given": {
        "ru": "Не задан ни порядок зон, ни порядок пунктов — менять нечего.",
        "en": "Neither a zone order nor an item order was given — there is nothing to change.",
    },
    # --- раскладка хранилища (#504) --------------------------------------------
    "refusal.bad_slug": {
        "ru": "Код «{value}» не годится: ожидаются строчные латинские буквы, цифры, дефис и "
        "подчёркивание, до 32 знаков (например «bizdev»).",
        "en": "Code “{value}” is not valid: use lowercase Latin letters, digits, hyphens and "
        "underscores, up to 32 characters (for example “bizdev”).",
    },
    "refusal.bad_state": {
        "ru": "Состояние «{value}» неизвестно. Годятся: {states}.",
        "en": "State “{value}” is unknown. Valid states: {states}.",
    },
    "refusal.prod_link_not_link": {
        "ru": "На месте указателя чек-листа, применённого к проду, лежит не ссылка: хранилище "
        "версий собрано не этим механизмом. Это настройка сервера — подробности в логе сервера.",
        "en": "The production checklist pointer in the store is not a link: the version store "
        "was not built by this mechanism. This is a server setting — details are in the "
        "server log.",
    },
    "refusal.version_link_not_link": {
        "ru": "На месте указателя действующей версии чек-листа лежит не ссылка: хранилище "
        "версий собрано не этим механизмом. Это настройка сервера — подробности в логе сервера.",
        "en": "The current-version pointer of the checklist is not a link: the version store "
        "was not built by this mechanism. This is a server setting — details are in the "
        "server log.",
    },
    "refusal.store_half_moved": {
        "ru": "Хранилище версий методики выглядит наполовину перенесённым: версии лежат и в "
        "старом месте, и в «{space}/{code}». Уберите одно из двух и повторите.",
        "en": "The methodology version store looks half moved: versions are both in the old "
        "place and in “{space}/{code}”. Remove one of the two and try again.",
    },
    # --- отказы самого экрана: разбор ввода формы ---------------------------------
    "refusal.web.term_not_number": {
        "ru": "Срок устранения «{value}» не число. Пустой срок и срок 0 — разные вещи: "
        "нулевой печатается партнёру как «устранить немедленно».",
        "en": "Fix deadline “{value}” is not a number. An empty deadline and 0 differ: "
        "zero is printed to the partner as “fix immediately”.",
    },
    "refusal.web.share_empty": {
        "ru": "Доля зоны «{zone}» не заполнена. Доли задаются набором сразу и обязаны сойтись "
        "к 100%.",
        "en": "The share of zone “{zone}” is empty. Shares are set together and must add up "
        "to 100%.",
    },
    "refusal.web.share_not_number": {
        "ru": "Доля зоны «{zone}» — «{value}», а это не число. Подставить ноль вместо "
        "непонятного ввода нельзя: доля задаёт вес зоны в оценке.",
        "en": "The share of zone “{zone}” is “{value}”, which is not a number. Zero cannot "
        "replace unclear input: the share sets the zone's weight in the score.",
    },
    "refusal.web.rate_not_number.start_pct": {
        "ru": "Начальный процент — «{value}», а это не число.",
        "en": "Starting percentage is “{value}”, which is not a number.",
    },
    "refusal.web.rate_not_number.d1": {
        "ru": "Ставка D1 — «{value}», а это не число.",
        "en": "Rate D1 is “{value}”, which is not a number.",
    },
    "refusal.web.rate_not_number.d2": {
        "ru": "Ставка D2 — «{value}», а это не число.",
        "en": "Rate D2 is “{value}”, which is not a number.",
    },
    "refusal.web.rate_not_number.repeat_multiplier": {
        "ru": "Множитель повтора — «{value}», а это не число.",
        "en": "Repeat multiplier is “{value}”, which is not a number.",
    },
}
