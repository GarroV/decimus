"""Тексты подключения Claude входом через сайт (D417): согласие, отказ, блок на карточке.

Отдельным модулем, как тексты экрана людей: `texts.py` длиннее предела файла.
Сливаются в общий каталог (`texts.TEXTS`).
"""

from __future__ import annotations

OAUTH_TEXTS: dict[str, dict[str, str]] = {
    # --- страница согласия -------------------------------------------------
    "oauth.consent.title": {"ru": "Подключить Claude", "en": "Connect Claude"},
    "oauth.consent.lead": {
        "ru": "«{client}» просит доступ к decimus от имени вашей учётки {login}.",
        "en": "“{client}” asks for access to decimus on behalf of your account {login}.",
    },
    "oauth.consent.role": {"ru": "Ваша роль: {role}.", "en": "Your role: {role}."},
    "oauth.consent.rights": {
        "ru": "Claude получит права вашей роли — не больше. Отключить подключение можно в "
        "любой момент на своей карточке в разделе «Пользователи».",
        "en": "Claude gets the rights of your role, no more. You can disconnect it at any "
        "time on your own card under “Users”.",
    },
    "oauth.consent.host": {
        "ru": "После решения вы вернётесь на {host}.",
        "en": "After you decide, you will be returned to {host}.",
    },
    "oauth.consent.loopback": {
        "ru": "Доступ получит программа на этом компьютере ({host}). Разрешайте, только если "
        "вы сами только что начали подключение в Claude Code.",
        "en": "Access goes to a program on this computer ({host}). Allow only if you have just "
        "started the connection in Claude Code yourself.",
    },
    "oauth.consent.allow": {"ru": "Разрешить", "en": "Allow"},
    "oauth.consent.deny": {"ru": "Отказать", "en": "Deny"},
    # --- отказ без редиректа -----------------------------------------------
    "oauth.refused.title": {"ru": "Подключение не начато", "en": "Connection not started"},
    "oauth.refused.unknown_client": {
        "ru": "Этот клиент Claude здесь не зарегистрирован или ссылка устарела. Начните "
        "подключение в Claude заново.",
        "en": "This Claude client is not registered here or the link is out of date. Start "
        "the connection in Claude again.",
    },
    "oauth.refused.bad_redirect": {
        "ru": "Адрес возврата не из разрешённых: подключить через сайт можно только Claude.",
        "en": "The return address is not allowed: only Claude can be connected through the site.",
    },
    "oauth.refused.no_account": {
        "ru": "Войдите в decimus и начните подключение заново.",
        "en": "Sign in to decimus and start the connection again.",
    },
}
