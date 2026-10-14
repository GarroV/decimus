"""Тексты журналов входов и действий (D462): подписи действий и экран «Журнал».

Подписи действий строятся из кода (имя маршрута веба или инструмента MCP): в журнале
хранится код, а читаемая фраза рисуется при показе и переводится здесь — переименовать
подпись можно без правки записей. Незнакомый код показывается как есть, а не падением:
журнал не должен пропадать из-за нового маршрута. Что у каждого изменяющего маршрута
и инструмента есть подпись, сверяет `tests/test_web_journal_labels.py`.
"""

from __future__ import annotations

#: Код действия → (русская подпись, английская). Маршруты веба.
_WEB: dict[str, tuple[str, str]] = {
    "actions_due": ("Срок по запросу экшн-плана", "Action plan request due date"),
    "actions_new": ("Запрос экшн-плана", "Action plan requested"),
    "actions_review": ("Вердикт по экшн-плану", "Action plan verdict"),
    "add_space": ("Заведено пространство партнёра", "Partner space added"),
    "add_user": ("Заведена учётка", "Account created"),
    "bot_unlink": ("Отвязан бот у человека", "Bot unlinked for a person"),
    "checklists_apply": ("Чек-лист применён к проду", "Checklist applied to production"),
    "checklists_create": ("Создан чек-лист", "Checklist created"),
    "checklists_master": ("Переключён главный чек-лист", "Master checklist toggled"),
    "checklists_state": ("Изменён статус чек-листа", "Checklist state changed"),
    "connections_issue": ("Выдан ключ API", "API key issued"),
    "connections_reissue": ("Перевыпущен ключ API", "API key reissued"),
    "connections_revoke": ("Отозван ключ API", "API key revoked"),
    "connections_update": ("Изменены права ключа API", "API key settings changed"),
    "model_key_check": ("Проверен ключ модели", "Model key checked"),
    "model_key_delete": ("Удалён ключ модели", "Model key removed"),
    "model_key_save": ("Задан ключ модели", "Model key set"),
    "do_accept": ("Принята проверка", "Inspection accepted"),
    "do_add_finding": ("Добавлено нарушение", "Finding added"),
    "do_add_photo": ("Добавлено фото", "Photo added"),
    "do_delete_photo": ("Удалено фото", "Photo deleted"),
    "do_move": ("Проверка перенесена", "Inspection moved"),
    "do_retract": ("Проверка снята", "Inspection retracted"),
    "do_revise": ("Нарушение исправлено", "Finding revised"),
    "reset_second_factor": (
        "Сброшена вторая ступень входа у человека",
        "Second sign-in step reset for a person",
    ),
    "security_passkey_register": ("Подключён ключ доступа", "Passkey added"),
    "security_passkey_delete": ("Удалён ключ доступа", "Passkey removed"),
    "passkey_expired": (
        "Сняты ключи доступа, которыми не входили 30 дней",
        "Passkeys unused for 30 days removed",
    ),
    "security_totp_confirm": (
        "Подключено приложение-аутентификатор",
        "Authenticator app connected",
    ),
    "security_totp_remove": (
        "Отключено приложение-аутентификатор",
        "Authenticator app disconnected",
    ),
    "second_step_code": ("Второй шаг входа: код", "Second sign-in step: code"),
    "second_step_passkey_options": (
        "Второй шаг входа: запрос ключа доступа",
        "Second sign-in step: passkey request",
    ),
    "second_step_passkey_verify": (
        "Второй шаг входа: ключ доступа",
        "Second sign-in step: passkey",
    ),
    "security_passkey_options": ("Запрос на добавление ключа доступа", "Passkey add request"),
    "security_relogin": ("Выход для повторного входа", "Sign-out to sign in again"),
    "security_totp_start": (
        "Начато подключение приложения-аутентификатора",
        "Authenticator app setup started",
    ),
    "security_backup_generate": ("Выпущены резервные коды", "Backup codes issued"),
    "freeze_user": ("Заморожена учётка", "Account frozen"),
    "unfreeze_user": ("Разморожена учётка", "Account unfrozen"),
    "letter_draft": ("Черновик письма", "Letter draft"),
    "login": ("Вход", "Sign-in"),
    "logout": ("Выход", "Sign-out"),
    "methodology_add": ("Добавлен пункт методики", "Methodology item added"),
    "methodology_bot": ("Доступ бота к чек-листу", "Bot access to checklist"),
    "methodology_disable": ("Пункт методики отключён", "Methodology item disabled"),
    "methodology_edit": ("Пункт методики изменён", "Methodology item edited"),
    "methodology_publish": ("Опубликована версия методики", "Methodology version published"),
    "methodology_restore": ("Пункт методики возвращён", "Methodology item restored"),
    "methodology_route": ("Изменён порядок обхода", "Walk route changed"),
    "methodology_scoring": ("Изменены веса и пороги оценки", "Scoring weights and grades changed"),
    "methodology_zone_add": ("Добавлена зона", "Zone added"),
    "methodology_zone_remove": ("Удалена зона", "Zone removed"),
    "methodology_zone_rename": ("Переименована зона", "Zone renamed"),
    "methodology_zone_shares": ("Изменены доли зон", "Zone shares changed"),
    "oauth_authorize": ("Подключение Claude разрешено", "Claude connection decided"),
    "oauth_register": ("Регистрация клиента Claude", "Claude client registered"),
    "oauth_token": ("Выдача токена Claude", "Claude token issued"),
    "order_reply": ("Ответ на предписание", "Prescription reply"),
    "plans_upload": ("Загружен экшн-план", "Action plan uploaded"),
    "ratings_agg_update": ("Обновление оценок агрегаторов", "Aggregator ratings update"),
    "ratings_coverage_link": ("Связана ссылка собираемости", "Coverage link set"),
    "ratings_developer": ("Изменены страны девелопера", "Developer countries changed"),
    "ratings_layout": ("Изменён состав блока рейтингов", "Ratings layout changed"),
    "ratings_rule_add": ("Добавлено жёсткое правило", "Hard rule added"),
    "ratings_rule_remove": ("Удалено жёсткое правило", "Hard rule removed"),
    "ratings_settings": ("Изменены настройки рейтингов", "Ratings settings changed"),
    "ratings_sheet_sync": ("Синхронизация таблицы рейтингов", "Ratings sheet sync"),
    "ratings_upload": ("Загружены рейтинги", "Ratings uploaded"),
    "reauth_confirm_google": ("Подтверждение входа через Google", "Sign-in confirmed with Google"),
    "reauth_confirm_password": ("Подтверждение входа паролем", "Sign-in confirmed with password"),
    "rx_close": ("Предписание закрыто", "Prescription closed"),
    "rx_create": ("Создано предписание", "Prescription created"),
    "rx_send": ("Предписание отправлено", "Prescription sent"),
    "rx_update": ("Предписание изменено", "Prescription edited"),
    "save_letter": ("Письмо сохранено", "Letter saved"),
    "settings_bot_link": ("Выпущена ссылка привязки бота", "Bot link issued"),
    "settings_bot_unlink": ("Отвязан свой бот", "Own bot unlinked"),
    "settings_claude_revoke": (
        "Отключено своё подключение Claude",
        "Own Claude connection removed",
    ),
    "settings_claude_token": ("Выпущен личный токен Claude", "Personal Claude token issued"),
    "settings_claude_token_revoke": (
        "Отозван личный токен Claude",
        "Personal Claude token revoked",
    ),
    "settings_continue": ("Продолжено подтверждённое действие", "Confirmed action continued"),
    "settings_google_link": ("Привязана почта Google", "Google email linked"),
    "settings_google_unlink": ("Отвязана почта Google", "Google email unlinked"),
    "settings_lang": ("Изменён язык сайта", "Site language changed"),
    "settings_own_password": ("Изменён свой пароль", "Own password changed"),
    "settings_sign_out_everywhere": ("Выход везде", "Signed out everywhere"),
    "space_countries": ("Изменены страны пространства", "Space countries changed"),
    "unit_create": ("Заведена пиццерия", "Pizzeria created"),
    "user_email": ("Изменена почта человека", "Person's email changed"),
    "user_role": ("Изменена роль человека", "Person's role changed"),
}

#: Действия командной строки на сервере (`tools/web_user.py`): маршрута у них нет.
_CLI: dict[str, tuple[str, str]] = {
    "reset_second_factor_cli": (
        "Сброшена вторая ступень входа командой с сервера",
        "Second sign-in step reset by a server command",
    ),
}

#: Инструменты MCP (Claude).
_MCP: dict[str, tuple[str, str]] = {
    "add_checklist_item": ("Добавлен пункт чек-листа", "Checklist item added"),
    "edit_checklist_item": ("Пункт чек-листа изменён", "Checklist item edited"),
    "remove_checklist_item": ("Пункт чек-листа отключён", "Checklist item removed"),
    "restore_checklist_item": ("Пункт чек-листа возвращён", "Checklist item restored"),
    "add_zone": ("Добавлена зона", "Zone added"),
    "remove_zone": ("Удалена зона", "Zone removed"),
    "rename_zone": ("Переименована зона", "Zone renamed"),
    "set_zone_shares": ("Изменены доли зон", "Zone shares changed"),
    "set_scoring": ("Изменены веса и пороги оценки", "Scoring weights and grades changed"),
    "set_route": ("Изменён порядок обхода", "Walk route changed"),
    "add_photo_cue": ("Добавлена подсказка по фото", "Photo cue added"),
    "edit_photo_cue": ("Подсказка по фото изменена", "Photo cue edited"),
    "set_photo_cue_zone": ("Подсказка по фото перенесена в зону", "Photo cue moved to a zone"),
    "remove_photo_cue": ("Подсказка по фото удалена", "Photo cue removed"),
    "retract_learned_phrase": ("Выученная фраза отозвана", "Learned phrase retracted"),
    "repoint_learned_phrase": ("Выученная фраза перенаправлена", "Learned phrase repointed"),
    "publish_checklist_version": ("Опубликована версия методики", "Methodology version published"),
    "retract_inspection": ("Проверка снята", "Inspection retracted"),
    "create_checklist": ("Создан чек-лист", "Checklist created"),
    "rename_checklist": ("Чек-лист переименован", "Checklist renamed"),
    "set_checklist_state": ("Изменён статус чек-листа", "Checklist state changed"),
    "set_checklist_bot_access": ("Доступ бота к чек-листу", "Bot access to checklist"),
    "apply_checklist": ("Чек-лист применён к проду", "Checklist applied to production"),
    "import_ratings": ("Загружены рейтинги", "Ratings uploaded"),
    "request_aggregators_update": ("Обновление оценок агрегаторов", "Aggregator ratings update"),
    "import_create_inspection": (
        "Создан черновик старой проверки",
        "Legacy inspection draft created",
    ),
    "import_add_finding": ("Добавлено нарушение в черновик", "Finding added to a draft"),
    "import_edit_finding": ("Изменено нарушение в черновике", "Finding edited in a draft"),
    "import_remove_finding": ("Удалено нарушение из черновика", "Finding removed from a draft"),
    "import_add_photo": ("Добавлено фото в черновик", "Photo added to a draft"),
    "import_accept_inspection": ("Принята загруженная проверка", "Imported inspection accepted"),
    "import_discard_draft": ("Отброшен черновик проверки", "Inspection draft discarded"),
}

#: Способы входа и исходы — подписи для таблицы.
_METHODS: dict[str, tuple[str, str]] = {
    "password": ("Пароль", "Password"),
    "google": ("Google", "Google"),
    "oauth-claude": ("Claude (через сайт)", "Claude (via the site)"),
    "personal-mcp-token": ("Личный токен Claude", "Personal Claude token"),
    "bot-link": ("Ссылка привязки бота", "Bot link"),
    "second-step": ("Вторая ступень входа", "Second sign-in step"),
    "passkey": ("Ключ доступа (Touch ID)", "Passkey (Touch ID)"),
}
_RESULTS: dict[str, tuple[str, str]] = {
    "ok": ("Вход выполнен", "Signed in"),
    "bad-password": ("Неверный пароль", "Wrong password"),
    "frozen": ("Учётка заморожена", "Account frozen"),
    "unknown": ("Нет такой учётки", "No such account"),
    "rate-limited": ("Запрещено: много попыток", "Blocked: too many attempts"),
    "refused": ("Способ закрыт для учётки", "Method closed for the account"),
    "bad-code": ("Код не подошёл", "Code rejected"),
    "passkey-fail": ("Ключ доступа не принят", "Passkey rejected"),
    "backup-used": ("Вход по резервному коду", "Signed in with a backup code"),
}
_DOORS: dict[str, tuple[str, str]] = {
    "web": ("Сайт", "Web"),
    "mcp": ("Claude", "Claude"),
    "bot": ("Бот", "Bot"),
}


def _pairs(prefix: str, source: dict[str, tuple[str, str]]) -> dict[str, dict[str, str]]:
    return {f"{prefix}.{код}": {"ru": ru, "en": en} for код, (ru, en) in source.items()}


#: Код → русская и английская подписи; тест сверяет покрытие по приложению и каталогу MCP.
WEB_ACTION_CODES = frozenset(_WEB)
MCP_ACTION_CODES = frozenset(_MCP)

_SCREEN: dict[str, dict[str, str]] = {
    "journal.tab": {"ru": "Журнал", "en": "Log"},
    "journal.sub": {
        "ru": "Кто входил, откуда и что меняли админы.",
        "en": "Who signed in, from where, and what admins changed.",
    },
    "journal.view.logins": {"ru": "Входы", "en": "Sign-ins"},
    "journal.view.actions": {"ru": "Действия", "en": "Actions"},
    "journal.filter.person": {"ru": "Человек", "en": "Person"},
    "journal.filter.everyone": {"ru": "Все", "en": "Everyone"},
    "journal.filter.apply": {"ru": "Показать", "en": "Show"},
    "journal.col.time": {"ru": "Время (UTC)", "en": "Time (UTC)"},
    "journal.col.person": {"ru": "Человек", "en": "Person"},
    "journal.col.ip": {"ru": "Адрес", "en": "Address"},
    "journal.col.browser": {"ru": "Браузер", "en": "Browser"},
    "journal.col.method": {"ru": "Способ", "en": "Method"},
    "journal.col.result": {"ru": "Итог", "en": "Result"},
    "journal.col.door": {"ru": "Вход", "en": "Door"},
    "journal.col.role": {"ru": "Роль", "en": "Role"},
    "journal.col.action": {"ru": "Действие", "en": "Action"},
    "journal.col.target": {"ru": "Над чем", "en": "Target"},
    "journal.col.outcome": {"ru": "Ответ", "en": "Outcome"},
    "journal.unknown_person": {"ru": "неизвестный логин", "en": "unknown login"},
    "journal.no_address": {"ru": "не определён", "en": "unknown"},
    "journal.count": {"ru": "Записей: {count}", "en": "Entries: {count}"},
    "journal.capped": {
        "ru": "Показаны последние {count}; сузьте период, чтобы увидеть остальное.",
        "en": "The latest {count} are shown; narrow the period to see the rest.",
    },
    "journal.empty.title": {"ru": "За этот период записей нет", "en": "No entries in this period"},
    "journal.empty.logins": {
        "ru": "Попытки входа за выбранный период появятся здесь.",
        "en": "Sign-in attempts in the chosen period will appear here.",
    },
    "journal.empty.actions": {
        "ru": "Действия админов за выбранный период появятся здесь.",
        "en": "Admin actions in the chosen period will appear here.",
    },
    "journal.failed.title": {"ru": "Журнал не прочитан", "en": "The log could not be read"},
    "journal.failed.text": {
        "ru": "База не ответила. Повторите чуть позже.",
        "en": "The database did not answer. Try again shortly.",
    },
    "journal.retention.logins": {
        "ru": "Входы хранятся 180 дней.",
        "en": "Sign-ins are kept for 180 days.",
    },
    "journal.retention.actions": {
        "ru": "Действия хранятся 365 дней. Пароли, токены и свободный текст в журнал не пишутся.",
        "en": "Actions are kept for 365 days. Passwords, tokens and free text are not recorded.",
    },
    "journal.own.title": {"ru": "Мои входы", "en": "My sign-ins"},
    "journal.own.sub": {
        "ru": (
            "Куда и как входили в вашу учётку. Увидели чужой вход — нажмите «Выйти везде» "
            "в настройках и смените пароль."
        ),
        "en": (
            "Where and how your account was signed into. See a sign-in that is not yours — "
            "use «Sign out everywhere» in settings and change your password."
        ),
    },
    "journal.own.row": {
        "ru": "Время, адрес, браузер и способ каждого входа в вашу учётку.",
        "en": "Time, address, browser and method of every sign-in to your account.",
    },
    "journal.own.link": {"ru": "Мои входы", "en": "My sign-ins"},
    "journal.own.back": {"ru": "К настройкам", "en": "Back to settings"},
}


def _build() -> dict[str, dict[str, str]]:
    return {
        **_SCREEN,
        **_pairs("journal.action", {**_MCP, **_WEB, **_CLI}),
        **_pairs("journal.method", _METHODS),
        **_pairs("journal.result", _RESULTS),
        **_pairs("journal.door", _DOORS),
    }


JOURNAL_TEXTS: dict[str, dict[str, str]] = _build()
