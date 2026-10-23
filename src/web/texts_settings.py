"""Тексты экрана «Настройки» (D447): подключения, Google, язык, пароль.

Тексты Claude, бота и пароля остаются у своих ключей (`users.mcp.*`,
`users.claude.*`, `profile.*`): экран только собирает их вместе. Здесь — то, что
появилось с самим экраном. Сливаются в общий каталог (`texts.TEXTS`).
"""

from __future__ import annotations

#: Инструкция для проекта Claude (Projects → Instructions) — один текст на весь экран.
#: Инструменты — по `docs/inventory.md` («Инструменты MCP»); добавили группу
#: инструментов — допишите строку здесь. Одна строка кортежа — одна строка текста.
_INSTRUCTIONS_RU = "\n".join(
    (
        "Ты работаешь с Decimus — системой выездных проверок пиццерий — через MCP-сервер decimus.",
        "Что доступно, решает роль человека; чего инструмент не отдаёт, того нет в данных — "
        "не выдумывай.",
        "Проверки: list_inspections, get_inspection, findings_by_unit, unit_history, "
        "network_summary, inspection_letter (письмо партнёру).",
        "Оценку не считай сам: проценты, букву и разбивку по зонам бери из ответа get_inspection.",
        "Рейтинги РС и РКО (рейтинги Dodo, не наши проверки): ratings_summary, ratings_units, "
        "ratings_unit_periods; сбор оценок в агрегаторах: aggregators_status.",
        "Планы исправлений: list_action_plans, get_action_plan. Управляющая компания "
        "принимает и возвращает план и строки (accept_action_plan, return_action_plan, "
        "confirm_plan_row, return_plan_row, set_plan_count_from); партнёр заполняет строки и "
        "ведёт их (fill_plan_row, submit_action_plan, start_plan_row, finish_plan_row). "
        "Просрочку не считай сам — бери overdue из ответа.",
        "Методика: checklist_source и checklist_source_item (пункт с критериями D1/D2/D3); "
        "правка чек-листов — только если роль позволяет.",
        "Старые проверки: import_create_inspection и остальные import_* — это черновик, "
        "принимает его человек.",
        "Пункты, зоны и пиццерии называй как в ответе инструмента, коды не переводи.",
        "Ничего не фиксируй в отчёте и не отправляй без подтверждения человека. "
        "Отвечай на языке вопроса.",
    )
)
_INSTRUCTIONS_EN = "\n".join(
    (
        "You work with Decimus, the pizzeria field-inspection system, through the decimus "
        "MCP server.",
        "What is available depends on the person's role; if a tool does not return it, it is "
        "not in the data — do not invent it.",
        "Inspections: list_inspections, get_inspection, findings_by_unit, unit_history, "
        "network_summary, inspection_letter (partner letter).",
        "Never compute a score yourself: take the percentage, the grade and the zone "
        "breakdown from the get_inspection response.",
        "SS and CX ratings (Dodo ratings, not our inspections): ratings_summary, "
        "ratings_units, ratings_unit_periods; delivery-aggregator collection: "
        "aggregators_status.",
        "Correction plans: list_action_plans, get_action_plan. The management company "
        "accepts and returns a plan and its rows (accept_action_plan, return_action_plan, "
        "confirm_plan_row, return_plan_row, set_plan_count_from); the partner fills rows and "
        "moves them (fill_plan_row, submit_action_plan, start_plan_row, finish_plan_row). "
        "Never compute overdue yourself: take overdue from the answer.",
        "Methodology: checklist_source and checklist_source_item (an item with its D1/D2/D3 "
        "criteria); editing checklists only if the role allows it.",
        "Past inspections: import_create_inspection and the other import_* tools make a "
        "draft, and a person accepts it.",
        "Name items, zones and pizzerias as the tool does, do not translate codes.",
        "Never record anything in a report or send anything without a person's "
        "confirmation. Answer in the language of the question.",
    )
)


SETTINGS_TEXTS: dict[str, dict[str, str]] = {
    "section.settings.title": {"ru": "Настройки", "en": "Settings"},
    "settings.sub": {
        "ru": "Ваш профиль: подключения и вход. Доступ к Claude и боту никто никому не "
        "выдаёт — вы подключаете их сами; что в них доступно, решает ваша роль.",
        "en": "Your profile: connections and sign-in. Nobody grants anyone access to Claude "
        "or the bot — you connect them yourself; what you can do there depends on your role.",
    },
    "settings.claude.title": {"ru": "Claude (MCP)", "en": "Claude (MCP)"},
    "settings.claude.lead": {
        "ru": "Подключите Claude к данным Decimus одной командой в терминале. Что доступно, "
        "решает ваша роль.",
        "en": "Connect Claude to Decimus data with one command in a terminal. What you can "
        "do depends on your role.",
    },
    "settings.claude.get": {"ru": "Получить команду установки", "en": "Get the install command"},
    "settings.claude.reissue": {
        "ru": "Перевыпустить команду установки",
        "en": "Reissue the install command",
    },
    "settings.claude.reissue_confirm": {
        "ru": "Прежний токен перестанет работать — переустановите Claude по новой команде.",
        "en": "The previous token stops working — reinstall Claude with the new command.",
    },
    "settings.claude.reissue_yes": {"ru": "Да, перевыпустить", "en": "Yes, reissue"},
    "settings.claude.run": {
        "ru": "Вставьте в терминал на Mac и перезапустите Claude (⌘Q). Команда видна один "
        "раз, токен личный.",
        "en": "Paste it into a terminal on your Mac and restart Claude (⌘Q). The command is "
        "shown once; the token is personal.",
    },
    "settings.claude.address": {
        "ru": "Или коннектором в claude.ai и Claude Code — адрес:",
        "en": "Or as a connector in claude.ai and Claude Code — the address:",
    },
    "settings.claude.copy": {"ru": "Скопировать команду", "en": "Copy the command"},
    "settings.claude.copy_again": {"ru": "Скопировать ещё раз", "en": "Copy again"},
    "settings.claude.copied": {"ru": "Скопировано", "en": "Copied"},
    "settings.claude.instr": {"ru": "Инструкции для проекта", "en": "Project instructions"},
    "settings.claude.instr_text": {"ru": _INSTRUCTIONS_RU, "en": _INSTRUCTIONS_EN},
    "settings.bot.title": {"ru": "Бот в Telegram", "en": "Telegram bot"},
    "settings.bot.read_only": {
        "ru": "Бот для вашей роли не подключается: проверок в поле она не ведёт.",
        "en": "The bot is not available for your role: it does not run field inspections.",
    },
    "settings.google.title": {"ru": "Google", "en": "Google"},
    "settings.google.linked": {
        "ru": "К учётке привязана почта {email}. Вход на сайт — только через Google, "
        "паролем нельзя.",
        "en": "The account is linked to {email}. You sign in with Google only, not with "
        "a password.",
    },
    "settings.google.linked_off": {
        "ru": "К учётке привязана почта {email}, но вход через Google на этом стенде не "
        "включён — вы входите паролем.",
        "en": "The account is linked to {email}, but Google sign-in is not enabled on this "
        "server — you sign in with a password.",
    },
    "settings.google.none": {
        "ru": "Почта Google не привязана, вы входите паролем.",
        "en": "No Google account is linked, you sign in with a password.",
    },
    "settings.google.none_off": {
        "ru": "Вход через Google на этом стенде не включён — привязать почту пока нельзя.",
        "en": "Google sign-in is not enabled on this server — you cannot link an account yet.",
    },
    "settings.google.link": {"ru": "Привязать Google", "en": "Link Google"},
    "settings.google.link_warn": {
        "ru": "После привязки вход паролем для этой учётки закроется: входить вы будете "
        "кнопкой «Войти через Google». Ваши входы на других устройствах закроются, "
        "Claude, подключённый через сайт, нужно будет подключить заново.",
        "en": "Once linked, password sign-in is closed for this account: you will sign in "
        "with the “Sign in with Google” button. Your sessions on other devices are "
        "closed, and Claude connected through the site has to be connected again.",
    },
    "settings.google.link_hq": {
        "ru": "Подойдёт только рабочий аккаунт Google компании ({domains}), личный — нет.",
        "en": "Only a company Google Workspace account ({domains}) will do, not a personal one.",
    },
    "settings.google.link_partner": {
        "ru": "Подойдёт аккаунт Google с подтверждённой почтой, если она не привязана к "
        "другой учётке.",
        "en": "Any Google account with a verified email will do, as long as the email is "
        "not linked to another account.",
    },
    "settings.google.link_go": {"ru": "Продолжить в Google", "en": "Continue with Google"},
    "settings.google.unlink": {"ru": "Отвязать Google", "en": "Unlink Google"},
    "settings.google.unlink_note": {
        "ru": "Отвязать можно, только зная пароль учётки: после отвязки вы входите паролем, "
        "и без него вход закроется совсем. Пароль забыт — новый выдаст администратор на "
        "«Пользователях». Ваши входы на других устройствах закроются, Claude, "
        "подключённый через сайт, отключится.",
        "en": "You can unlink only if you know the account password: after unlinking you "
        "sign in with it, and without it you would lock yourself out. Forgot the "
        "password — an administrator issues a new one in “Users”. Your sessions on "
        "other devices are closed, and Claude connected through the site is disconnected.",
    },
    "settings.google.unlink_current": {"ru": "Пароль учётки", "en": "Account password"},
    "settings.google.unlink_submit": {"ru": "Отвязать", "en": "Unlink"},
    "settings.google.unlink.empty": {
        "ru": "Введите пароль учётки — без него отвязать нельзя.",
        "en": "Enter the account password — you cannot unlink without it.",
    },
    "settings.google.unlink.wrong": {
        "ru": "Пароль не подошёл — привязка осталась.",
        "en": "Wrong password — the link stays.",
    },
    "settings.google.unlink.locked": {
        "ru": "Слишком много попыток. Попробуйте через {minutes} мин.",
        "en": "Too many attempts. Try again in {minutes} min.",
    },
    "settings.google.done.linked": {
        "ru": "Почта Google привязана. Теперь вы входите через Google, вход паролем закрыт.",
        "en": "Google account linked. You now sign in with Google; password sign-in is closed.",
    },
    "settings.google.done.unlinked": {
        "ru": "Почта Google отвязана. Входите логином и паролем.",
        "en": "Google account unlinked. Sign in with your login and password.",
    },
    "settings.google.done.cancelled": {
        "ru": "Привязку отменили в окне Google — ничего не изменилось.",
        "en": "Linking was cancelled in the Google window — nothing changed.",
    },
    "settings.google.done.failed": {
        "ru": "Google не подтвердил аккаунт — попробуйте ещё раз.",
        "en": "Google did not confirm the account — please try again.",
    },
    "settings.google.done.state": {
        "ru": "Заход устарел или начат в другом окне — начните привязку заново.",
        "en": "The attempt expired or was started in another window — start linking again.",
    },
    "settings.google.done.unverified": {
        "ru": "Почта этого аккаунта Google не подтверждена — привязать её нельзя.",
        "en": "The email of this Google account is not verified — it cannot be linked.",
    },
    "settings.google.done.domain": {
        "ru": "Для учётки УК подходит только рабочий аккаунт Google компании, а не личный.",
        "en": "A head-office account takes only a company Google Workspace account, "
        "not a personal one.",
    },
    "settings.google.done.taken": {
        "ru": "Эта почта уже привязана к другой учётке.",
        "en": "This email is already linked to another account.",
    },
    "settings.google.done.already": {
        "ru": "К учётке уже привязана почта — сначала отвяжите её.",
        "en": "An email is already linked to the account — unlink it first.",
    },
    "settings.google.done.db": {
        "ru": "База не ответила — ничего не изменилось. Попробуйте позже.",
        "en": "The database did not respond — nothing changed. Try again later.",
    },
    "settings.google.gmail": {
        "ru": "Доступ к Gmail спрашивается отдельно — когда вы впервые уводите письмо "
        "партнёру в черновики. Мы его нигде не храним, поэтому статуса здесь нет: "
        "Google спросит снова, а выданное ранее отзывается в настройках аккаунта Google.",
        "en": "Gmail access is asked separately — the first time you send a letter to a "
        "partner to drafts. We do not store it, so there is no status here: Google asks "
        "again, and earlier grants are revoked in your Google account settings.",
    },
    "settings.lang.title": {"ru": "Язык интерфейса", "en": "Interface language"},
    "settings.lang.note": {
        "ru": "Сохраняется в профиле. У бота и мини-аппа — свой язык.",
        "en": "Saved in your profile. The bot and the mini-app keep their own.",
    },
    "settings.password.google": {
        "ru": "Вход паролем для этой учётки закрыт: вы входите через Google. Вернуть вход "
        "паролем — «Отвязать Google» в подключении Google.",
        "en": "Password sign-in is closed for this account: you sign in with Google. To "
        "sign in with a password again, use “Unlink Google” in the Google connection.",
    },
    "settings.confirm.title": {"ru": "Подтвердите вход", "en": "Confirm it's you"},
    "settings.confirm.why": {
        "ru": "Это действие даёт долгий доступ к вашей учётке — токен Claude, бот, почта "
        "Google или подключение Claude. Поэтому вход должен быть свежим: не старше 12 "
        "часов. Подтвердите, что это вы — и токен, ссылка на бота или "
        "переход к Google выполнятся (через Google — "
        "после кнопки «Продолжить»); остальное — нажмите кнопку ещё раз.",
        "en": "This action grants long-lived access to your account — a Claude token, the "
        "bot, a Google account or a Claude connection. So the sign-in must be recent: no "
        "older than 12 hours. Confirm it's you — a token, a bot link or the Google step "
        "then runs "
        "(with Google, after one “Continue” press); for anything else, press the button again.",
    },
    "settings.confirm.submit": {"ru": "Подтвердить", "en": "Confirm"},
    "settings.confirm.google": {
        "ru": "Подтвердить через Google",
        "en": "Confirm with Google",
    },
    "settings.confirm.failed": {
        "ru": "Пароль не подошёл.",
        "en": "Wrong password.",
    },
    "settings.confirm.failed_google": {
        "ru": "Google не подтвердил вход этой учётки — войдите тем аккаунтом, чья почта "
        "к ней привязана.",
        "en": "Google did not confirm this account — use the Google account whose email is "
        "linked to it.",
    },
    "settings.confirm.locked": {
        "ru": "Слишком много попыток. Попробуйте через {minutes} мин.",
        "en": "Too many attempts. Try again in {minutes} min.",
    },
    "settings.confirm.back": {"ru": "Вернуться в «Настройки»", "en": "Back to Settings"},
    "settings.continue.title": {"ru": "Продолжить действие", "en": "Continue"},
    "settings.continue.why": {
        "ru": "Вход подтверждён. Вы просили: {action}. Нажмите «Продолжить» — действие "
        "выполнится один раз.",
        "en": "Sign-in confirmed. You asked to: {action}. Press “Continue” — it will run once.",
    },
    "settings.continue.claude-token": {
        "ru": "выпустить токен Claude",
        "en": "issue a Claude token",
    },
    "settings.continue.bot-link": {
        "ru": "выпустить ссылку привязки бота",
        "en": "issue a bot link",
    },
    "settings.continue.google-link": {
        "ru": "привязать почту Google",
        "en": "link a Google account",
    },
    "settings.continue.submit": {"ru": "Продолжить", "en": "Continue"},
    "users.panel.own_settings": {
        "ru": "Пароль, бот, Claude и язык — в «Настройках».",
        "en": "Password, bot, Claude and language are in “Settings”.",
    },
    "users.panel.open_settings": {"ru": "Открыть «Настройки»", "en": "Open “Settings”"},
    # Меню учётки поверх страницы (D468).
    # Плитки (D470): профиль, малые карточки и подключения, как в Swarm Brain.
    "settings.profile.title": {"ru": "Профиль", "en": "Profile"},
    "settings.profile.role": {"ru": "Роль и пространство", "en": "Role and space"},
    "settings.profile.email": {"ru": "Почта", "en": "Email"},
    "settings.profile.email_none": {"ru": "Не привязана", "en": "Not linked"},
    "settings.profile.sessions": {"ru": "Другие входы", "en": "Other sessions"},
    "settings.profile.account": {"ru": "Аккаунт", "en": "Account"},
    "settings.profile.details": {"ru": "Подробнее", "en": "Details"},
    "settings.profile.change": {"ru": "Изменить", "en": "Change"},
    "settings.password.card": {
        "ru": "Пароль для входа на сайт.",
        "en": "The password you sign in to this site with.",
    },
    "settings.conn.count": {"ru": "{n} из {total}", "en": "{n} of {total}"},
    "menu.title": {"ru": "Меню учётки", "en": "Account menu"},
    "menu.connections": {"ru": "Подключения", "en": "Connections"},
    "menu.on": {"ru": "Подключено", "en": "Connected"},
    "menu.off": {"ru": "Не подключено", "en": "Not connected"},
    "menu.unknown": {"ru": "Не удалось узнать", "en": "Could not check"},
    "menu.theme": {"ru": "Тема", "en": "Theme"},
    "menu.lang": {"ru": "Язык", "en": "Language"},
    "menu.all_settings": {"ru": "Все настройки", "en": "All settings"},
    "settings.tile.password_set": {"ru": "Пароль задан", "en": "Password set"},
    "settings.tile.password_google": {"ru": "Вход через Google", "en": "Signing in with Google"},
    "settings.tile.signins": {"ru": "Когда и откуда входили", "en": "When and from where"},
    "settings.group.connect": {"ru": "Подключения", "en": "Connections"},
    "settings.group.profile": {"ru": "Профиль", "en": "Profile"},
    "settings.group.access": {"ru": "Вход и безопасность", "en": "Sign-in and security"},
    "settings.tile.signout": {"ru": "Сессии и выход", "en": "Sessions and sign-out"},
    "settings.signout.title": {"ru": "Выйти везде", "en": "Sign out everywhere"},
    "settings.signout.note": {
        "ru": "Закроет ваши сессии на сайте на всех устройствах, включая эту, отзовёт "
        "подключения Claude и личный токен. Бот в Telegram останется привязанным. "
        "Войдёте заново — как обычно.",
        "en": "Closes your web sessions on every device, including this one, and revokes "
        "your Claude connections and personal token. The Telegram bot stays linked. "
        "You sign in again as usual.",
    },
    "settings.signout.open": {"ru": "Выйти везде", "en": "Sign out everywhere"},
    "settings.signout.confirm": {
        "ru": "Все ваши входы и подключения Claude закроются сразу, вы выйдете и здесь.",
        "en": "All your sign-ins and Claude connections close at once; you are "
        "signed out here too.",
    },
    "settings.signout.yes": {"ru": "Да, выйти везде", "en": "Yes, sign out everywhere"},
    "settings.signout.failed": {
        "ru": "Не закрыто — база не ответила. Попробуйте ещё раз.",
        "en": "Not closed — the database did not respond. Please try again.",
    },
}
