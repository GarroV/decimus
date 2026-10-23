"""Тексты второй ступени входа (D463): «Подтвердите вход» и «Вход и защита».

Сливаются в общий каталог (`texts.TEXTS`). Тексты отказов — одной формулой на все
осечки: по различиям перебирающий узнавал бы, что верно, а что нет.
"""

from __future__ import annotations

SECOND_FACTOR_TEXTS: dict[str, dict[str, str]] = {
    # --- «Подтвердите вход» после первой ступени ------------------------------------
    "sf.step.title": {"ru": "Подтвердите вход", "en": "Confirm sign-in"},
    "sf.step.lead": {
        "ru": "Первая проверка пройдена. Подтвердите, что это вы: ключом доступа или кодом.",
        "en": "The first check is done. Confirm it is you with a passkey or a code.",
    },
    "sf.step.who": {"ru": "Учётка: {login}", "en": "Account: {login}"},
    "sf.step.passkey": {"ru": "Войти ключом доступа", "en": "Use a passkey"},
    "sf.step.passkey_hint": {
        "ru": "Touch ID, Face ID или ключ безопасности.",
        "en": "Touch ID, Face ID or a security key.",
    },
    "sf.step.passkey_failed": {
        "ru": "Ключ не подошёл или окно закрыто. Попробуйте ещё раз или введите код.",
        "en": "The passkey was not accepted or the prompt was closed. Try again or enter a code.",
    },
    "sf.step.passkey_unavailable": {
        "ru": "Ключ доступа в этом окне недоступен. Откройте страницу в Safari или Chrome — "
        "или введите код.",
        "en": "Passkeys are not available in this window. Open the page in Safari or Chrome — "
        "or enter a code.",
    },
    "sf.step.passkey_off": {
        "ru": "Ключи доступа на этом адресе не включены. Введите код или обратитесь к "
        "главному админу.",
        "en": "Passkeys are not enabled at this address. Enter a code or ask a superadmin.",
    },
    "sf.step.code": {
        "ru": "Код из приложения или резервный код",
        "en": "Authenticator code or backup code",
    },
    "sf.step.code_hint": {
        "ru": "Шесть цифр из приложения-аутентификатора или резервный код вида ABCD-EFGH-….",
        "en": "Six digits from your authenticator app, or a backup code like ABCD-EFGH-….",
    },
    "sf.step.submit": {"ru": "Подтвердить", "en": "Confirm"},
    "sf.step.failed": {
        "ru": "Не подошло. Проверьте код и попробуйте ещё раз.",
        "en": "That did not work. Check the code and try again.",
    },
    "sf.step.locked": {
        "ru": "Слишком много попыток. Подождите {minutes} мин и попробуйте снова.",
        "en": "Too many attempts. Wait {minutes} min and try again.",
    },
    "sf.step.expired": {
        "ru": "Время на подтверждение вышло. Войдите заново.",
        "en": "The confirmation timed out. Sign in again.",
    },
    "sf.step.restart": {"ru": "Начать заново", "en": "Start over"},
    "sf.step.lost": {
        "ru": "Нет ни ключа, ни кода? Обратитесь к главному админу — он сбросит вторую ступень.",
        "en": "No passkey and no code? Ask a superadmin to reset your second step.",
    },
    # --- «Вход и защита» ----------------------------------------------------------------
    "sf.sec.title": {"ru": "Вход и защита", "en": "Sign-in and protection"},
    "sf.sec.sub": {
        "ru": "Touch ID сохраняется сам после входа и снимается, если не входили 30 дней.",
        "en": "Touch ID saves itself after you sign in and is removed after 30 days without use.",
    },
    "sf.sec.sub.fallback": {
        "ru": "Здесь — запасной способ: приложение-аутентификатор и резервные коды.",
        "en": "Here is the fallback: an authenticator app and backup codes.",
    },
    "sf.sec.card": {
        "ru": "Вход по Touch ID; приложение и резервные коды — запасные.",
        "en": "Touch ID sign-in; app and backup codes as a fallback.",
    },
    "sf.sec.open": {"ru": "Настроить", "en": "Set up"},
    "sf.sec.status_on": {"ru": "Подключено", "en": "On"},
    "sf.sec.status_off": {"ru": "Не подключено", "en": "Off"},
    "sf.sec.required": {
        "ru": "Запасной способ не подключён: подключите приложение-аутентификатор.",
        "en": "No fallback yet: connect an authenticator app.",
    },
    "sf.sec.prove_title": {
        "ru": "Подтвердите, что это вы",
        "en": "Confirm it is you",
    },
    "sf.sec.prove_lead": {
        "ru": "Вы вошли Google или паролем. Чтобы удалить или заменить способ входа, "
        "подтвердите вход ключом доступа или кодом.",
        "en": "You signed in with Google or a password. To remove or replace a sign-in method, "
        "confirm with a passkey or a code.",
    },
    "sf.sec.prove_key": {"ru": "Подтвердить ключом", "en": "Confirm with a passkey"},
    "sf.sec.prove_code": {
        "ru": "Код из приложения или резервный код",
        "en": "Authenticator code or backup code",
    },
    "sf.sec.prove_submit": {"ru": "Подтвердить", "en": "Confirm"},
    "sf.sec.prove_bad": {
        "ru": "Код не подошёл. Попробуйте ещё раз.",
        "en": "The code was not accepted. Try again.",
    },
    "sf.sec.proved": {
        "ru": "Подтверждено: теперь способы входа можно менять.",
        "en": "Confirmed: you can now change sign-in methods.",
    },
    "sf.here.line": {
        "ru": "Включить вход по Touch ID в этом браузере",
        "en": "Turn on Touch ID sign-in for this browser",
    },
    "sf.login.passkey": {"ru": "Войти по Touch ID", "en": "Sign in with Touch ID"},
    "sf.login.passkey_failed": {
        "ru": "Ключ не подошёл или окно закрыто. Войдите через Google или паролем.",
        "en": "The passkey was not accepted or the prompt was closed. Sign in with Google or a "
        "password.",
    },
    "sf.sec.optional": {
        "ru": "Запасной способ не подключён: подключите приложение-аутентификатор.",
        "en": "No fallback yet: connect an authenticator app.",
    },
    "sf.sec.stale": {
        "ru": "Менять способы входа можно только сразу после входа (не позже 10 минут). "
        "Войдите заново — и вернётесь сюда.",
        "en": "Sign-in methods can only be changed right after signing in (within 10 minutes). "
        "Sign in again and you will come back here.",
    },
    "sf.sec.relogin": {"ru": "Войти заново", "en": "Sign in again"},
    "sf.sec.recommend_codes": {
        "ru": "Выпустите резервные коды: без них потеря телефона или ключа закрывает вход.",
        "en": "Issue backup codes: without them a lost phone or key locks you out.",
    },
    # ключи доступа
    "sf.pk.title": {"ru": "Ключ доступа", "en": "Passkey"},
    "sf.pk.lead": {
        "ru": "Ключи входа по Touch ID: по одному на браузер. Потеряли устройство — удалите его "
        "ключ.",
        "en": "Touch ID sign-in keys: one per browser. Lost a device — remove its key.",
    },
    "sf.pk.none": {
        "ru": "Ключей пока нет.",
        "en": "No keys yet.",
    },
    "sf.pk.added": {"ru": "добавлен {date}", "en": "added {date}"},
    "sf.pk.used": {"ru": "последний вход {date}", "en": "last used {date}"},
    "sf.pk.never_used": {"ru": "ещё не использовался", "en": "not used yet"},
    "sf.pk.name": {"ru": "Название ключа", "en": "Passkey name"},
    "sf.pk.name_placeholder": {"ru": "Например, MacBook", "en": "For example, MacBook"},
    "sf.pk.add": {"ru": "Добавить ключ доступа", "en": "Add a passkey"},
    "sf.pk.remove": {"ru": "Удалить", "en": "Remove"},
    "sf.pk.remove_confirm": {
        "ru": "Удалить ключ «{name}»? Войти им больше не получится.",
        "en": "Remove the passkey “{name}”? You will not be able to sign in with it.",
    },
    "sf.pk.remove_yes": {"ru": "Да, удалить", "en": "Yes, remove"},
    "sf.pk.default_name": {"ru": "Ключ {n}", "en": "Passkey {n}"},
    "sf.pk.unavailable": {
        "ru": "Ключ доступа в этом окне недоступен. Откройте страницу в Safari или Chrome.",
        "en": "Passkeys are not available in this window. Open the page in Safari or Chrome.",
    },
    "sf.pk.off": {
        "ru": "Ключи доступа на этом адресе не включены (не задан адрес продукта).",
        "en": "Passkeys are not enabled at this address (the product address is not set).",
    },
    "sf.pk.failed": {
        "ru": "Ключ не добавлен: окно закрыто или проверка не прошла. Попробуйте ещё раз.",
        "en": "The passkey was not added: the prompt was closed or the check failed. Try again.",
    },
    "sf.pk.saved": {"ru": "Ключ доступа добавлен.", "en": "Passkey added."},
    "sf.pk.removed": {"ru": "Ключ доступа удалён.", "en": "Passkey removed."},
    "sf.pk.missing": {"ru": "Такого ключа нет.", "en": "No such passkey."},
    "sf.pk.limit": {
        "ru": "Ключей уже {max}: удалите ненужный.",
        "en": "Already {max} passkeys: remove one you do not need.",
    },
    # приложение
    "sf.totp.title": {"ru": "Приложение-аутентификатор", "en": "Authenticator app"},
    "sf.totp.lead": {
        "ru": "Запасной способ. Google Authenticator, 1Password, Authy и любое другое с кодами "
        "из шести цифр. При входе код не спрашивается.",
        "en": "A fallback. Google Authenticator, 1Password, Authy or any app with six-digit "
        "codes. Sign-in does not ask for the code.",
    },
    "sf.totp.on": {"ru": "Приложение подключено.", "en": "App connected."},
    "sf.totp.off": {"ru": "Приложение не подключено.", "en": "No app connected."},
    "sf.totp.start": {"ru": "Подключить приложение", "en": "Connect an app"},
    "sf.totp.scan": {
        "ru": "Отсканируйте код в приложении или введите ключ вручную.",
        "en": "Scan the code in your app or type the key by hand.",
    },
    "sf.totp.qr_alt": {"ru": "QR-код для приложения", "en": "QR code for the app"},
    "sf.totp.key": {"ru": "Ключ для ввода вручную", "en": "Key to type by hand"},
    "sf.totp.confirm_label": {
        "ru": "Код из приложения (шесть цифр)",
        "en": "Code from the app (six digits)",
    },
    "sf.totp.confirm": {"ru": "Подтвердить и подключить", "en": "Confirm and connect"},
    "sf.totp.bad": {
        "ru": "Код не подошёл. Проверьте время на телефоне и введите свежий код.",
        "en": "The code did not match. Check the time on your phone and enter a fresh code.",
    },
    "sf.totp.saved": {"ru": "Приложение подключено.", "en": "App connected."},
    "sf.totp.removed": {"ru": "Приложение отключено.", "en": "App disconnected."},
    "sf.totp.exists": {
        "ru": "Приложение уже подключено. Сначала отключите его.",
        "en": "An app is already connected. Disconnect it first.",
    },
    "sf.totp.remove": {"ru": "Отключить", "en": "Disconnect"},
    "sf.totp.remove_confirm": {
        "ru": "Отключить приложение? Коды из него перестанут подходить.",
        "en": "Disconnect the app? Its codes will stop working.",
    },
    "sf.totp.remove_yes": {"ru": "Да, отключить", "en": "Yes, disconnect"},
    # резервные коды
    "sf.codes.title": {"ru": "Резервные коды", "en": "Backup codes"},
    "sf.codes.lead": {
        "ru": "Если нет под рукой ни ключа, ни телефона, войти можно резервным кодом. Каждый "
        "работает один раз.",
        "en": "If you have neither your key nor your phone, a backup code gets you in. Each "
        "works once.",
    },
    "sf.codes.left": {"ru": "Осталось кодов: {n}.", "en": "Codes left: {n}."},
    "sf.codes.none": {"ru": "Кодов нет.", "en": "No codes."},
    "sf.codes.need_factor": {
        "ru": "Сначала подключите ключ доступа или приложение.",
        "en": "Connect a passkey or an app first.",
    },
    "sf.codes.generate": {"ru": "Выпустить коды", "en": "Issue codes"},
    "sf.codes.regenerate": {"ru": "Выпустить новые", "en": "Issue new ones"},
    "sf.codes.regenerate_confirm": {
        "ru": "Выпустить новые коды? Прежние перестанут действовать.",
        "en": "Issue new codes? The old ones stop working.",
    },
    "sf.codes.regenerate_yes": {"ru": "Да, выпустить новые", "en": "Yes, issue new ones"},
    "sf.codes.shown": {
        "ru": "Сохраните коды сейчас: больше они не покажутся. Каждый работает один раз.",
        "en": "Save the codes now: they will not be shown again. Each works once.",
    },
    # общее
    "sf.sec.last_factor": {
        "ru": "Это последний способ входа, а для вашей роли он обязателен: сначала подключите "
        "другой.",
        "en": "This is your last sign-in method and your role requires one: connect another first.",
    },
    "sf.sec.stale_refused": {
        "ru": (
            "Чтобы менять способы входа, войдите заново: вход должен быть свежим (до 10 минут, "
            "админу без способа — до 5) и подтверждённым вторым шагом."
        ),
        "en": (
            "To change sign-in methods, sign in again: the sign-in must be recent (up to 10 "
            "minutes, 5 for an admin without a method) and confirmed with the second step."
        ),
    },
    "sf.sec.db": {
        "ru": "Не удалось сохранить: база недоступна. Попробуйте ещё раз.",
        "en": "Could not save: the database is unavailable. Try again.",
    },
    # --- вход: заметка после просроченного подтверждения --------------------------------
    "sf.login.expired": {
        "ru": "Время на подтверждение вышло — войдите заново.",
        "en": "The confirmation timed out — sign in again.",
    },
    # --- «Пользователи»: сброс второй ступени -------------------------------------------
    "sf.reset.title": {"ru": "Вторая ступень входа", "en": "Second sign-in step"},
    "sf.reset.note": {
        "ru": "Потерян ключ и приложение? Сброс снимает все способы подтверждения: человек "
        "войдёт Google или паролем и подключит их заново.",
        "en": "Lost the key and the app? A reset removes all confirmation methods: the person "
        "signs in with Google or a password and connects them again.",
    },
    "sf.reset.open": {"ru": "Сбросить вторую ступень", "en": "Reset second step"},
    "sf.reset.confirm": {
        "ru": "Сбросить вторую ступень у {login}? Ключи, приложение и резервные коды будут сняты.",
        "en": "Reset the second step for {login}? Passkeys, the app and backup codes will be "
        "removed.",
    },
    "sf.reset.yes": {"ru": "Да, сбросить", "en": "Yes, reset"},
    "sf.reset.done": {
        "ru": "Вторая ступень у {login} сброшена.",
        "en": "Second step reset for {login}.",
    },
    "sf.reset.self": {
        "ru": "Свою вторую ступень через сайт не сбросить: её сбрасывает команда на сервере "
        "(tools/web_user.py reset-second-factor).",
        "en": "You cannot reset your own second step on the site: use the server command "
        "(tools/web_user.py reset-second-factor).",
    },
    "sf.reset.none": {
        "ru": "У {login} второй ступени не было — сбрасывать нечего.",
        "en": "{login} had no second step — nothing to reset.",
    },
}
