"""Тексты экрана «Пользователи» вместе с карточкой человека (#585, переделка экрана).

Отдельным модулем, а не строками в `texts.py`: тот длиннее предела файла.
Сливаются в общий каталог (`texts.TEXTS`) — `t()` знает один словарь.

Роль называется как должность — одно-два слова; что она может, — одна строка
пояснения под названием (`users.hint.*`), а не в самом названии. У партнёра
своя пара названий (`users.role.partner.*`): код `auditor` в УК — «Аудитор», в
пространстве партнёра — «Сотрудник» (D346). Название выбирает
`users_view.role_key`, шаблоны ключ руками не собирают.
"""

from __future__ import annotations

_ROLES: dict[str, dict[str, str]] = {
    # Названия — как должности (владелец 09.10.2026).
    "users.role.superadmin": {"ru": "Главный админ", "en": "Super admin"},
    "users.role.admin": {"ru": "Админ", "en": "Admin"},
    "users.role.control": {"ru": "Контролинг", "en": "Controller"},
    "users.role.auditor": {"ru": "Аудитор", "en": "Auditor"},
    "users.role.partner.admin": {"ru": "Админ", "en": "Admin"},
    "users.role.partner.auditor": {"ru": "Сотрудник", "en": "Staff"},
    # Что роль может — по D344, D346, D360, D364, D367.
    "users.hint.superadmin": {
        "ru": "Всё по проекту: люди любых пространств, другие главные админы, партнёры и страны.",
        "en": "Everything in the project: people of any space, other super admins, partners.",
    },
    "users.hint.admin": {
        "ru": "Правит методику, ведёт аудиторов, контролинг и партнёров с их людьми.",
        "en": "Edits the methodology, manages auditors, controllers, partners and their people.",
    },
    "users.hint.control": {
        "ru": "Только рейтинги: загрузка и справочники. Ведёт людей контролинга.",
        "en": "Ratings only: uploads and settings. Manages controller accounts.",
    },
    "users.hint.auditor": {
        "ru": "Проводит проверки в боте и видит их результаты.",
        "en": "Runs inspections in the bot and sees their results.",
    },
    "users.hint.partner.admin": {
        "ru": "Добавляет и отключает людей своего пространства, вычитывает их проверки.",
        "en": "Adds and disables people of their space, reviews their inspections.",
    },
    "users.hint.partner.auditor": {
        "ru": "Проводит проверки и видит статистику. Людей не добавляет.",
        "en": "Runs inspections and sees statistics. Does not add people.",
    },
}

_SCREEN: dict[str, dict[str, str]] = {
    "users.count": {"ru": "С доступом: {count}", "en": "With access: {count}"},
    "users.count_off": {"ru": "отключено: {count}", "en": "disabled: {count}"},
    # Охват — одна строка под заголовком (#585, D364).
    "users.scope.super": {"ru": "Все пространства.", "en": "Every space."},
    "users.scope.hq_admin": {
        "ru": "Люди УК, кроме админов, и люди партнёров.",
        "en": "HQ people except admins, and partner people.",
    },
    "users.scope.control": {"ru": "Люди контролинга.", "en": "Controller accounts."},
    "users.scope.partner_admin": {"ru": "Люди вашего пространства.", "en": "People of your space."},
    "users.tab.people": {"ru": "Люди", "en": "People"},
    "users.add.open": {"ru": "Добавить человека", "en": "Add a person"},
    # Фильтры — одной строкой над списком.
    "users.filter.search": {"ru": "Логин или почта", "en": "Login or email"},
    "users.filter.space_all": {"ru": "Все пространства", "en": "All spaces"},
    "users.filter.role_all": {"ru": "Все роли", "en": "All roles"},
    "users.filter.auditor_any": {"ru": "Аудитор или сотрудник", "en": "Auditor or staff"},
    "users.filter.off": {"ru": "Показать отключённых", "en": "Show disabled"},
    "users.filter.apply": {"ru": "Показать", "en": "Apply"},
    "users.filter.reset": {"ru": "Сбросить", "en": "Reset"},
    "users.col.person": {"ru": "Человек", "en": "Person"},
    "users.col.space": {"ru": "Пространство", "en": "Space"},
    "users.col.role": {"ru": "Роль", "en": "Role"},
    "users.col.bot": {"ru": "Бот", "en": "Bot"},
    "users.col.status": {"ru": "Статус", "en": "Status"},
    "users.bot.yes": {"ru": "Привязан", "en": "Linked"},
    "users.bot.no": {"ru": "Нет", "en": "No"},
    "users.status.active": {"ru": "Работает", "en": "Active"},
    "users.status.off": {"ru": "Отключён", "en": "Disabled"},
    "users.no_email": {"ru": "почта не задана", "en": "no email"},
    "users.empty.title": {"ru": "Пока никого", "en": "Nobody yet"},
    "users.empty.text": {
        "ru": "Добавьте первого человека: система выдаст ему пароль.",
        "en": "Add the first person: the system will issue a password.",
    },
    "users.empty_filter.title": {"ru": "Никого не нашли", "en": "Nobody found"},
    "users.empty_filter.text": {
        "ru": "Поменяйте запрос или сбросьте фильтры.",
        "en": "Change the query or reset the filters.",
    },
    "users.unknown.title": {"ru": "Список не загрузился", "en": "The list did not load"},
    "users.unknown": {
        "ru": "База не ответила. Это не значит, что людей нет: обновите страницу через минуту.",
        "en": "The database did not answer. It does not mean there is nobody: reload in a minute.",
    },
    "users.self.title": {"ru": "Людей добавляет админ", "en": "An admin adds people"},
    "users.self.text": {
        "ru": "Список людей вам не открыт. Здесь ваша учётка: роль, пароль, бот.",
        "en": "The list of people is not open to you. Here is your account: role, password, bot.",
    },
    "users.forbidden.title": {"ru": "Этот раздел не для всех", "en": "This section is restricted"},
    "users.forbidden.note": {
        "ru": (
            "Людей добавляет админ. Если доступ нужен вам — попросите того, "
            "кто уже админ: роль выдаётся изнутри админки."
        ),
        "en": (
            "Only an admin manages people. If you need access, ask someone "
            "who already is one — the role is granted from inside."
        ),
    },
}

_PANEL: dict[str, dict[str, str]] = {
    "users.panel.close": {"ru": "Закрыть", "en": "Close"},
    "users.panel.created": {"ru": "Добавлен", "en": "Added"},
    "users.panel.email": {"ru": "Почта для Google", "en": "Google sign-in email"},
    "users.panel.role_title": {"ru": "Роль", "en": "Role"},
    "users.panel.role_self": {
        "ru": "Свою роль сменить нельзя: так можно закрыть себе этот экран.",
        "en": "You cannot change your own role: it could lock you out of this screen.",
    },
    "users.panel.email_title": {"ru": "Вход через Google", "en": "Google sign-in"},
    "users.panel.email_hint": {
        "ru": "Пустое поле закрывает вход через Google; пароль продолжает работать.",
        "en": "An empty field closes Google sign-in; the password keeps working.",
    },
    "users.panel.bot_title": {"ru": "Бот в Telegram", "en": "Telegram bot"},
    "users.panel.bot_bound": {
        "ru": "Привязан к Telegram ID {id} с {date}.",
        "en": "Linked to Telegram ID {id} since {date}.",
    },
    "users.panel.bot_unbound": {"ru": "Не привязан.", "en": "Not linked."},
    "users.panel.disabled": {
        "ru": "Доступ отключён {date}. Вернуть его с этого экрана нельзя.",
        "en": "Access disabled on {date}. It cannot be restored from this screen.",
    },
    "users.save": {"ru": "Сохранить", "en": "Save"},
    "users.email.placeholder": {"ru": "name@dodobrands.io", "en": "name@dodobrands.io"},
    "users.bot.unlink_other": {"ru": "Отвязать бота", "en": "Unlink the bot"},
    "users.disable.open": {"ru": "Отключить доступ", "en": "Disable access"},
    "users.disable.confirm": {
        "ru": (
            "{login} больше не сможет войти, открытые сессии закроются. "
            "Вернуть доступ с этого экрана нельзя."
        ),
        "en": (
            "{login} will no longer be able to sign in; open sessions will end. "
            "Access cannot be restored from this screen."
        ),
    },
    "users.disable.yes": {"ru": "Да, отключить", "en": "Yes, disable"},
}

_ADD: dict[str, dict[str, str]] = {
    "users.add.title": {"ru": "Новый человек", "en": "New person"},
    "users.add.login": {"ru": "Логин", "en": "Login"},
    "users.add.login_hint": {
        "ru": "Строчная латиница, цифры, точка, дефис. По нему человек входит.",
        "en": "Lower-case Latin, digits, dot, hyphen. The person signs in with it.",
    },
    "users.add.email": {"ru": "Почта для Google", "en": "Google sign-in email"},
    "users.add.email_hint": {
        "ru": "Необязательно. С ней человек входит через Google.",
        "en": "Optional. With it the person signs in with Google.",
    },
    "users.add.space": {"ru": "Пространство", "en": "Space"},
    "users.add.role": {"ru": "Роль", "en": "Role"},
    "users.add.submit": {"ru": "Добавить", "en": "Add"},
    "users.add.hint": {
        "ru": "Пароль придумает система и покажет один раз.",
        "en": "The system makes up the password and shows it once.",
    },
    "users.add.failed": {
        "ru": "Не добавлено: логин уже занят или не годится по форме.",
        "en": "Not added: the login is taken or malformed.",
    },
    "users.add.role_space": {
        "ru": "Главный админ и контролинг бывают только в пространстве УК (HQ). Не добавлено.",
        "en": "Super admin and controller exist only in the HQ space. Nothing was added.",
    },
    "users.add.space_unknown": {
        "ru": "Такого пространства нет. Выберите из списка.",
        "en": "There is no such space. Pick one from the list.",
    },
    "users.added.title": {"ru": "{login} добавлен", "en": "{login} added"},
    "users.added.text": {
        "ru": "Передайте человеку логин и пароль. Пароль показан один раз: потом его не узнать.",
        "en": "Pass the login and password on. The password is shown once, never again.",
    },
    "users.added.password": {"ru": "Пароль", "en": "Password"},
    "users.added.copy": {"ru": "Скопировать", "en": "Copy"},
    "users.added.copied": {"ru": "Скопировано", "en": "Copied"},
    "users.added.more": {"ru": "Добавить ещё", "en": "Add another"},
    "users.added.done": {"ru": "Готово", "en": "Done"},
    "users.added.email_failed": {
        "ru": "Почта не сохранена: она уже у другой учётки или база не ответила. "
        "Задайте её в карточке человека.",
        "en": "The email was not saved: another account has it or the database did not answer. "
        "Set it on the person's card.",
    },
}

_OUTCOMES: dict[str, dict[str, str]] = {
    "users.edit.missing": {
        "ru": "Учётка не найдена или отключена — ничего не изменено.",
        "en": "Account not found or disabled — nothing changed.",
    },
    "users.edit.space": {
        "ru": "Такого пространства нет — ничего не изменено.",
        "en": "No such space — nothing changed.",
    },
    "users.edit.failed": {
        "ru": "База не ответила — ничего не изменено. Попробуйте ещё раз.",
        "en": "The database did not respond — nothing changed. Please try again.",
    },
    "users.role.ok": {"ru": "Роль изменена.", "en": "Role changed."},
    "users.role.unknown": {
        "ru": "Такой роли нет — ничего не изменено.",
        "en": "No such role — nothing changed.",
    },
    "users.role.self": {
        "ru": "Свою роль сменить нельзя: так можно закрыть себе этот экран.",
        "en": "You cannot change your own role: it could lock you out of this screen.",
    },
    "users.role.failed": {
        "ru": "Роль не изменена: база не ответила. Попробуйте ещё раз.",
        "en": "Role not changed: the database did not respond. Please try again.",
    },
    "users.role.forbidden": {
        "ru": "Эту роль вы выдать не можете.",
        "en": "You cannot grant this role.",
    },
    "users.role.last_super": {
        "ru": "Это последний действующий главный админ: сначала назначьте другого.",
        "en": "This is the last active super admin: appoint another one first.",
    },
    "users.email.ok": {
        "ru": "Почта сохранена: человек может входить через Google.",
        "en": "Email saved: the person can sign in with Google.",
    },
    "users.email.removed": {
        "ru": "Почта снята: вход через Google закрыт, пароль остался.",
        "en": "Email removed: Google sign-in is closed, the password still works.",
    },
    "users.email.shape": {
        "ru": "Это не похоже на почту — ничего не изменено.",
        "en": "This does not look like an email address — nothing changed.",
    },
    "users.email.taken": {
        "ru": "Эта почта уже привязана к другой учётке — ничего не изменено.",
        "en": "This email is already linked to another account — nothing changed.",
    },
    "users.email.failed": {
        "ru": "Почта не сохранена: база не ответила. Попробуйте ещё раз.",
        "en": "Email not saved: the database did not respond. Please try again.",
    },
    "users.disable.ok": {
        "ru": "Доступ отключён. Открытые сессии этого человека закрыты.",
        "en": "Access disabled. This person's open sessions have ended.",
    },
    "users.disable.missing": {
        "ru": "Такой работающей учётки нет — возможно, её уже отключили.",
        "en": "No such active account — it may already be disabled.",
    },
    "users.disable.self": {
        "ru": "Себя отключить нельзя: это выход без возврата.",
        "en": "You cannot disable yourself: there is no way back.",
    },
    "users.disable.failed": {
        "ru": "Не отключено — база не ответила.",
        "en": "Not disabled — the database did not answer.",
    },
    "users.disable.last_super": {
        "ru": "Последнего главного админа отключить нельзя: сначала назначьте другого.",
        "en": "The last active super admin cannot be disabled: appoint another one first.",
    },
    "users.bot.unlinked": {
        "ru": "Бот отвязан. Этот Telegram больше не проводит проверки от учётки.",
        "en": "The bot is unlinked. This Telegram no longer runs inspections for the account.",
    },
    "users.bot.unlink_missing": {
        "ru": "Привязки не было — отвязывать нечего.",
        "en": "There was no link — nothing to unlink.",
    },
    "users.bot.unlink_failed": {
        "ru": "Не отвязано — база не ответила. Попробуйте ещё раз.",
        "en": "Not unlinked — the database did not respond. Try again.",
    },
}

_SPACES: dict[str, dict[str, str]] = {
    "users.spaces.title": {"ru": "Пространства партнёров", "en": "Partner spaces"},
    "users.spaces.own_title": {"ru": "Ваше пространство", "en": "Your space"},
    "users.spaces.count": {"ru": "Пространств: {count}", "en": "Spaces: {count}"},
    "users.spaces.col.space": {"ru": "Пространство", "en": "Space"},
    "users.spaces.col.countries": {"ru": "Страны", "en": "Countries"},
    "users.spaces.col.people": {"ru": "Людей", "en": "People"},
    "users.spaces.none": {"ru": "Пространств партнёров пока нет", "en": "No partner spaces yet"},
    "users.spaces.none_text": {
        "ru": "Заведите первое: код партнёра и его страны.",
        "en": "Create the first one: a partner code and its countries.",
    },
    "users.spaces.unknown": {
        "ru": "Список пространств не загрузился: база не ответила.",
        "en": "The list of spaces did not load: the database did not answer.",
    },
    "users.spaces.readonly": {
        "ru": "Страны пространства меняет главный админ или админ УК.",
        "en": "A super admin or an HQ admin changes the space's countries.",
    },
    "users.spaces.show_people": {"ru": "Показать людей", "en": "Show people"},
    "users.spaces.add.open": {"ru": "Добавить пространство", "en": "Add a space"},
    "users.spaces.add.title": {"ru": "Новое пространство", "en": "New space"},
    "users.spaces.add.code": {"ru": "Код", "en": "Code"},
    "users.spaces.add.code_hint": {
        "ru": "Заглавная латиница, например GE. Не меняется никогда.",
        "en": "Upper-case Latin, e.g. GE. It never changes.",
    },
    "users.spaces.add.name": {"ru": "Название", "en": "Name"},
    "users.spaces.add.countries": {"ru": "Страны", "en": "Countries"},
    "users.spaces.add.countries_hint": {
        "ru": "Коды ISO через пробел. Одна страна — один партнёр.",
        "en": "ISO codes, space-separated. One country — one partner.",
    },
    "users.spaces.add.submit": {"ru": "Добавить", "en": "Add"},
    "users.spaces.countries.add": {"ru": "Добавить страны", "en": "Add countries"},
    "users.spaces.countries.submit": {"ru": "Добавить", "en": "Add"},
    "users.spaces.space_added": {"ru": "Пространство заведено.", "en": "Space created."},
    "users.spaces.space_failed": {
        "ru": (
            "Пространство не заведено: код занят или не годится, страна уже у другого партнёра "
            "или база не ответила. Ничего не записано."
        ),
        "en": (
            "Space not created: the code is taken or invalid, a country belongs to another "
            "partner, or the database did not answer. Nothing was saved."
        ),
    },
    "users.spaces.countries_added": {"ru": "Страны добавлены.", "en": "Countries added."},
    "users.spaces.countries_failed": {
        "ru": (
            "Страны не добавлены: код страны не годится, страна уже у другого партнёра "
            "или база не ответила. Ничего не записано."
        ),
        "en": (
            "Countries not added: a code is invalid, a country belongs to another partner, "
            "or the database did not answer. Nothing was saved."
        ),
    },
}

_PROFILE: dict[str, dict[str, str]] = {
    "profile.open": {"ru": "Моя карточка", "en": "My card"},
    "profile.login": {"ru": "Логин", "en": "Login"},
    "profile.role": {"ru": "Роль", "en": "Role"},
    "profile.space": {"ru": "Пространство", "en": "Space"},
    "profile.bot.title": {"ru": "Бот в Telegram", "en": "Telegram bot"},
    "profile.bot.bound": {
        "ru": "Бот привязан: Telegram ID {id}, с {date}.",
        "en": "The bot is linked: Telegram ID {id}, since {date}.",
    },
    "profile.bot.unbound": {
        "ru": "Бот не привязан. Привяжите его, чтобы проводить проверки в Telegram.",
        "en": "The bot is not linked. Link it to run inspections in Telegram.",
    },
    "profile.bot.unknown": {
        "ru": "Не удалось узнать, привязан ли бот. Это не значит, что не привязан.",
        "en": "Could not check whether the bot is linked. That does not mean it is not.",
    },
    "profile.bot.link_submit": {"ru": "Привязать бота", "en": "Link the bot"},
    "profile.bot.link": {
        "ru": "Откройте эту ссылку в Telegram на своём телефоне — бот привяжется к вашей учётке:",
        "en": "Open this link in Telegram on your phone — the bot will link to your account:",
    },
    "profile.bot.until": {
        "ru": "Ссылка одноразовая и действует 10 минут (до {time}). Новая ссылка отменяет прежнюю.",
        "en": (
            "The link works once and for 10 minutes (until {time}). A new link cancels the old one."
        ),
    },
    "profile.bot.unset": {
        "ru": "Привязка бота на этом стенде не настроена: не задана переменная {var}.",
        "en": "Bot linking is not set up on this server: the {var} variable is not set.",
    },
    "profile.bot.link_failed": {
        "ru": "Ссылку выпустить не вышло — база не ответила. Попробуйте ещё раз.",
        "en": "Could not issue the link — the database did not respond. Try again.",
    },
    "profile.bot.unlink": {"ru": "Отвязать", "en": "Unlink"},
    "profile.password.title": {"ru": "Пароль", "en": "Password"},
    "profile.password.current": {"ru": "Текущий пароль", "en": "Current password"},
    "profile.password.new": {"ru": "Новый пароль", "en": "New password"},
    "profile.password.repeat": {"ru": "Повтор нового", "en": "Repeat new password"},
    "profile.password.submit": {"ru": "Сменить пароль", "en": "Change password"},
    "profile.password.hint": {
        "ru": "Не короче {min} знаков. После смены все остальные ваши входы закрываются, "
        "этот остаётся.",
        "en": "At least {min} characters. After the change all your other sessions are "
        "signed out; this one stays.",
    },
    "profile.password.ok": {
        "ru": "Пароль сменён. Остальные ваши входы закрыты.",
        "en": "Password changed. Your other sessions have been signed out.",
    },
    "profile.password.wrong": {
        "ru": "Пароль не сменён: проверьте текущий пароль.",
        "en": "Password not changed: check your current password.",
    },
    "profile.password.mismatch": {
        "ru": "Пароль не сменён: повтор не совпадает с новым.",
        "en": "Password not changed: the repeat does not match the new password.",
    },
    "profile.password.short": {
        "ru": "Пароль не сменён: новый короче {min} знаков.",
        "en": "Password not changed: the new password is shorter than {min} characters.",
    },
    "profile.password.long": {
        "ru": "Пароль не сменён: новый длиннее {max} знаков.",
        "en": "Password not changed: the new password is longer than {max} characters.",
    },
    "profile.password.empty": {
        "ru": "Пароль не сменён: заполните текущий и новый пароль.",
        "en": "Password not changed: fill in the current and the new password.",
    },
    "profile.password.locked": {
        "ru": "Слишком много неудачных попыток. Попробуйте через {minutes} мин.",
        "en": "Too many failed attempts. Try again in {minutes} min.",
    },
    "profile.password.failed": {
        "ru": "Пароль не сменён: база не ответила. Попробуйте ещё раз.",
        "en": "Password not changed: the database did not respond. Please try again.",
    },
}

_MCP: dict[str, dict[str, str]] = {
    "users.mcp.title": {"ru": "Claude (MCP)", "en": "Claude (MCP)"},
    "users.mcp.on": {"ru": "Доступ есть", "en": "Has access"},
    "users.mcp.token": {"ru": "токен выпущен", "en": "token issued"},
    "users.mcp.no_token": {"ru": "токен ещё не выпущен", "en": "no token yet"},
    "users.mcp.off": {"ru": "Доступа нет", "en": "No access"},
    "users.mcp.was": {"ru": "Доступ снят", "en": "Access removed"},
    "users.mcp.need_bot": {
        "ru": "Доступ к Claude выдаётся на Telegram: сначала нужна привязка бота.",
        "en": "Claude access is tied to Telegram: the bot has to be linked first.",
    },
    "users.mcp.unknown": {
        "ru": "Не удалось узнать, есть ли доступ: база не ответила.",
        "en": "Could not check the access: the database did not answer.",
    },
    "users.mcp.grant": {"ru": "Дать доступ", "en": "Grant access"},
    "users.mcp.revoke": {"ru": "Снять доступ", "en": "Remove access"},
    "users.mcp.revoke_confirm": {
        "ru": "Снятие сразу гасит токены человека: его Claude перестанет получать данные.",
        "en": "Removing ends the person's tokens at once: their Claude stops getting data.",
    },
    "users.mcp.revoke_yes": {"ru": "Да, снять", "en": "Yes, remove"},
    "users.mcp.founder_note": {
        "ru": "Основатель круга: его доступ задан настройкой стенда и с экрана не снимается.",
        "en": "Circle founder: the access comes from the server settings and stays.",
    },
    "users.mcp.who_can": {
        "ru": "Давать и снимать доступ может тот, у кого он уже есть.",
        "en": "Only someone who already has access can grant or remove it.",
    },
    "users.mcp.setup_bot": {
        "ru": "Подключить Claude Desktop — в боте командой /mcp: бот выпустит личный токен "
        "и пришлёт команду настройки. Новый токен гасит прежний.",
        "en": "Connect Claude Desktop in the bot with /mcp: it issues a personal token "
        "and sends the setup command. A new token cancels the previous one.",
    },
    "users.mcp.granted": {
        "ru": "Доступ к Claude дан. Подключиться человек может в боте командой /mcp.",
        "en": "Claude access granted. The person connects in the bot with /mcp.",
    },
    "users.mcp.revoked": {
        "ru": "Доступ к Claude снят. Погашено токенов: {tokens}.",
        "en": "Claude access removed. Tokens ended: {tokens}.",
    },
    "users.mcp.founder": {
        "ru": "Основателя круга снять нельзя: его называет настройка стенда.",
        "en": "The circle founder cannot be removed: the server settings name them.",
    },
    "users.mcp.failed": {
        "ru": "Не вышло — база не ответила. Ничего не изменено.",
        "en": "Did not work — the database did not answer. Nothing changed.",
    },
}

_CARD: dict[str, dict[str, str]] = {
    "users.panel.who": {"ru": "Кто", "en": "Who"},
    "users.panel.login": {"ru": "Логин", "en": "Login"},
    "users.panel.space": {"ru": "Пространство", "en": "Space"},
    "users.panel.signin_title": {"ru": "Вход", "en": "Sign-in"},
    "users.panel.password_other": {
        "ru": "Сбросить пароль с экрана пока нельзя — это делает команда обслуживания.",
        "en": "A password cannot be reset from the screen yet — the maintenance command does it.",
    },
    "users.panel.bot_self_only": {
        "ru": "Привязать бота человек может сам в своей карточке.",
        "en": "The person links the bot in their own card.",
    },
    "users.panel.access_title": {"ru": "Доступ к учётке", "en": "Account access"},
    "users.panel.active": {
        "ru": "Учётка работает. Отключение закрывает вход и все открытые сессии.",
        "en": "The account is active. Disabling closes sign-in and every open session.",
    },
    "users.panel.pick_title": {"ru": "Выберите человека", "en": "Pick a person"},
    "users.panel.pick_text": {
        "ru": "Слева список. Здесь — роль, вход, бот и доступы выбранного.",
        "en": "The list is on the left. Here: role, sign-in, bot and access of the one picked.",
    },
    "users.me": {"ru": "вы", "en": "you"},
}

USERS_TEXTS: dict[str, dict[str, str]] = {
    **_ROLES,
    **_SCREEN,
    **_PANEL,
    **_ADD,
    **_OUTCOMES,
    **_SPACES,
    **_PROFILE,
    **_MCP,
    **_CARD,
}
