"""Тексты подключения нейросетей входом через сайт (D417, D695): согласие, отказ, плитка.

Отдельным модулем, как тексты экрана людей: `texts.py` длиннее предела файла.
Сливаются в общий каталог (`texts.TEXTS`).
"""

from __future__ import annotations

OAUTH_TEXTS: dict[str, dict[str, str]] = {
    # --- страница согласия -------------------------------------------------
    "oauth.consent.title": {"ru": "Подключить нейросеть", "en": "Connect an AI assistant"},
    # Вид клиента — по адресу возврата, а не по имени, которое клиент пишет о себе сам.
    "oauth.kind.claude": {"ru": "Claude", "en": "Claude"},
    "oauth.kind.chatgpt": {"ru": "ChatGPT", "en": "ChatGPT"},
    "oauth.kind.local": {
        "ru": "Программа на этом компьютере (Claude Code, Codex, Kimi Code, ZCode)",
        "en": "A program on this computer (Claude Code, Codex, Kimi Code, ZCode)",
    },
    "oauth.consent.lead": {
        "ru": "{kind} просит доступ к decimus от имени вашей учётки {login}.",
        "en": "{kind} asks for access to decimus on behalf of your account {login}.",
    },
    "oauth.consent.unverified": {
        "ru": "Клиент называет себя «{client}» — это имя он выбрал сам, его никто не проверял.",
        "en": "The client calls itself “{client}” — it chose that name itself; nobody has "
        "verified it.",
    },
    "oauth.consent.only_you": {
        "ru": "Разрешайте, только если подключение начали вы сами и только что. Если вы "
        "попали сюда по чужой ссылке — нажмите «Отказать».",
        "en": "Allow only if you started this connection yourself just now. If you came here "
        "from someone else's link, press “Deny”.",
    },
    "oauth.consent.role": {"ru": "Ваша роль: {role}.", "en": "Your role: {role}."},
    "oauth.consent.rights": {
        "ru": "Нейросеть получит права вашей роли — не больше. Отключить подключение можно в "
        "любой момент в разделе «Настройки».",
        "en": "The assistant gets the rights of your role, no more. You can disconnect it at "
        "any time under “Settings”.",
    },
    "oauth.consent.host": {
        "ru": "После решения вы вернётесь на {host}.",
        "en": "After you decide, you will be returned to {host}.",
    },
    "oauth.consent.loopback": {
        "ru": "Доступ получит программа на этом компьютере ({host}). Разрешайте, только если "
        "вы сами только что начали подключение в Claude Code, Codex, Kimi Code или ZCode.",
        "en": "Access goes to a program on this computer ({host}). Allow only if you have just "
        "started the connection in Claude Code, Codex, Kimi Code or ZCode yourself.",
    },
    "oauth.consent.allow": {"ru": "Разрешить", "en": "Allow"},
    "oauth.consent.deny": {"ru": "Отказать", "en": "Deny"},
    # --- отказ без редиректа -----------------------------------------------
    "oauth.refused.title": {"ru": "Подключение не начато", "en": "Connection not started"},
    "oauth.refused.unknown_client": {
        "ru": "Этот клиент здесь не зарегистрирован или ссылка устарела. Начните "
        "подключение в нейросети заново.",
        "en": "This client is not registered here or the link is out of date. Start "
        "the connection in the assistant again.",
    },
    "oauth.refused.bad_redirect": {
        "ru": "Адрес возврата не из разрешённых: через сайт подключаются Claude, ChatGPT и "
        "программы на компьютере.",
        "en": "The return address is not allowed: Claude, ChatGPT and programs on a computer "
        "can be connected through the site.",
    },
    "oauth.refused.no_account": {
        "ru": "Войдите в decimus и начните подключение заново.",
        "en": "Sign in to decimus and start the connection again.",
    },
    # --- блок «Подключить Claude» в «Настройках» -----------------------------
    "users.claude.address": {
        "ru": "Адрес decimus для Claude:",
        "en": "The decimus address for Claude:",
    },
    "users.claude.copy": {"ru": "Скопировать", "en": "Copy"},
    "users.claude.copied": {"ru": "Скопировано", "en": "Copied"},
    "users.claude.step_add": {
        "ru": "claude.ai в браузере или телефон: Настройки → Коннекторы → Добавить свой "
        "коннектор → вставьте адрес. Claude Desktop — командой установки в «Настройках».",
        "en": "claude.ai in a browser or phone: Settings → Connectors → Add custom "
        "connector → paste the address. Claude Desktop — the install command in “Settings”.",
    },
    "users.claude.step_login": {
        "ru": "Claude откроет вход decimus: войдите своей учёткой и нажмите «Разрешить». Права "
        "в Claude — как у вашей роли.",
        "en": "Claude opens the decimus sign-in: sign in with your account and press “Allow”. "
        "Claude gets the rights of your role.",
    },
    "users.claude.code": {
        "ru": "Claude Code — команда в терминале:",
        "en": "Claude Code — run in a terminal:",
    },
    "users.claude.connections": {"ru": "Подключения", "en": "Connections"},
    "users.claude.none": {"ru": "Подключений пока нет.", "en": "No connections yet."},
    "users.claude.unknown": {
        "ru": "Список подключений сейчас недоступен: база не ответила.",
        "en": "The list of connections is unavailable right now: the database did not answer.",
    },
    "users.claude.row": {
        "ru": "{client} · подключено {created}",
        "en": "{client} · connected {created}",
    },
    "users.claude.used": {"ru": "последний вызов {used}", "en": "last call {used}"},
    "users.claude.unused": {"ru": "вызовов ещё не было", "en": "no calls yet"},
    "users.claude.revoke": {"ru": "Отключить", "en": "Disconnect"},
    "users.claude.revoked": {
        "ru": "Подключение отключено: нейросеть потеряет доступ на следующем же вызове.",
        "en": "Disconnected: the assistant loses access on its very next call.",
    },
    "users.claude.revoke_missing": {
        "ru": "Такого подключения у вас нет — возможно, оно уже отключено.",
        "en": "You have no such connection; it may already be disconnected.",
    },
    "users.claude.failed": {
        "ru": "Не удалось отключить: база не ответила. Попробуйте ещё раз.",
        "en": "Could not disconnect: the database did not answer. Try again.",
    },
}
