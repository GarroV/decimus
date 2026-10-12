"""Тексты экрана «Настройки» (D447): подключения, Google, язык, пароль.

Тексты Claude, бота и пароля остаются у своих ключей (`users.mcp.*`,
`users.claude.*`, `profile.*`): экран только собирает их вместе. Здесь — то, что
появилось с самим экраном. Сливаются в общий каталог (`texts.TEXTS`).
"""

from __future__ import annotations

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
        "ru": "Подключите Claude к данным Decimus: Claude Desktop — командой с личным токеном, "
        "Claude Code — строкой ниже. Читает и правит Claude в пределах вашей роли.",
        "en": "Connect Claude to Decimus data: Claude Desktop with a command and a personal "
        "token, Claude Code with the line below. Claude acts within the rights of your role.",
    },
    "settings.claude.desktop": {"ru": "Claude Desktop", "en": "Claude Desktop"},
    "settings.claude.code": {
        "ru": "Claude Code и другие клиенты",
        "en": "Claude Code and other clients",
    },
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
        "ru": "Почта Google не привязана, вы входите паролем. Почту к учётке привязывает "
        "администратор; с ней вход идёт через Google, а пароль закрывается.",
        "en": "No Google account is linked, you sign in with a password. An administrator "
        "links the email; after that you sign in with Google and the password is closed.",
    },
    "settings.google.unlink": {
        "ru": "Снять привязку почты — у администратора; он же вернёт вход паролем, если "
        "доступ к Google потерян.",
        "en": "An administrator removes the link; they also restore password sign-in if "
        "access to Google is lost.",
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
        "ru": "Язык этого сайта; выбор сохраняется, пока вы идёте по ссылкам сайта. Бот и "
        "мини-апп помнят язык отдельно (команда /lang, настройки мини-аппа).",
        "en": "The language of this site; the choice carries over while you follow the "
        "site's links. The bot and the mini-app keep their language separately "
        "(/lang, mini-app settings).",
    },
    "settings.password.google": {
        "ru": "Вход паролем для этой учётки закрыт: вы входите через Google.",
        "en": "Password sign-in is closed for this account: you sign in with Google.",
    },
    "users.panel.own_settings": {
        "ru": "Пароль, бот, Claude и язык — в «Настройках».",
        "en": "Password, bot, Claude and language are in “Settings”.",
    },
    "users.panel.open_settings": {"ru": "Открыть «Настройки»", "en": "Open “Settings”"},
}
