"""Тексты блока «Ключи сервисов» на вкладке «Подключения» (D491, D576).

Отдельным модулем по образцу `texts_connections.py`: сливаются в общий каталог
(`texts.TEXTS`). Подстановок со значением ключа нет и быть не может: единственная
подстановка — `{status}`, код ответа провайдера (число), а последние четыре знака
шаблон берёт из записи в базе, не из формы.
"""

from __future__ import annotations

SERVICE_KEYS_TEXTS: dict[str, dict[str, str]] = {
    "keys.title": {"ru": "Ключи сервисов", "en": "Service keys"},
    "keys.sub": {
        "ru": (
            "Хранятся зашифрованными и после сохранения не показываются. "
            "Замена и удаление — со вторым шагом входа."
        ),
        "en": (
            "Stored encrypted and never shown again. "
            "Replacing or removing needs the second sign-in step."
        ),
    },
    "keys.service.openai": {"ru": "Нейросеть (OpenAI)", "en": "AI model (OpenAI)"},
    "keys.service.pointer": {"ru": "Pointer", "en": "Pointer"},
    "keys.service.ispring": {"ru": "iSpring", "en": "iSpring"},
    "keys.purpose.openai": {
        "ru": "Ключом бот и веб разбирают комментарии и голосовые.",
        "en": "The bot and the web use it to read comments and voice notes.",
    },
    "keys.purpose.pointer": {
        "ru": "Ключом загружаются оценки пиццерий на картах.",
        "en": "It is used to load pizzeria ratings from the maps.",
    },
    "keys.purpose.ispring": {
        "ru": "Пара ключей для выгрузки данных об обучении из iSpring Learn.",
        "en": "A key pair for pulling training data from iSpring Learn.",
    },
    "keys.field.api_key": {"ru": "Ключ", "en": "Key"},
    "keys.field.client_id": {"ru": "Client ID", "en": "Client ID"},
    "keys.field.client_secret": {"ru": "Client secret", "en": "Client secret"},
    "keys.status.db": {"ru": "Задан в админке", "en": "Set in the admin"},
    "keys.status.env": {"ru": "Из окружения сервера", "en": "From the server environment"},
    "keys.status.unset": {"ru": "Не задан", "en": "Not set"},
    "keys.status.partial": {
        "ru": "Задан частично: часть полей из окружения сервера",
        "en": "Partly set: some fields come from the server environment",
    },
    "keys.set_by": {"ru": "Поставлен", "en": "Set"},
    "keys.tile.db": {"ru": "Задан", "en": "Set"},
    "keys.tile.env": {"ru": "Из окружения", "en": "From environment"},
    "keys.tile.unset": {"ru": "Не задан", "en": "Not set"},
    "keys.tile.partial": {"ru": "Частично", "en": "Partly"},
    "keys.unknown": {
        "ru": "Не удалось прочитать, что задано. Повторите чуть позже.",
        "en": "Could not read what is set. Try again shortly.",
    },
    "keys.replace_title": {"ru": "Заменить", "en": "Replace"},
    "keys.new_hint": {
        "ru": "Вставьте значение целиком: оно проверится у провайдера и нигде не показывается.",
        "en": "Paste the whole value: it is checked with the provider and never shown.",
    },
    "keys.save": {"ru": "Заменить", "en": "Replace"},
    "keys.check": {"ru": "Проверить", "en": "Check"},
    "keys.delete": {"ru": "Удалить", "en": "Remove"},
    "keys.delete_hint": {
        "ru": "После удаления снова работает значение из окружения сервера, если оно задано.",
        "en": "After removal the server environment value is used again, if it is set.",
    },
    "keys.ok.saved": {
        "ru": "Проверено у провайдера и сохранено. Заработает во всех процессах в течение минуты.",
        "en": (
            "Checked with the provider and saved. It takes effect in every process within a minute."
        ),
    },
    "keys.ok.checked": {
        "ru": "Провайдер принял значение. Ничего не сохранено.",
        "en": "The provider accepted the value. Nothing was saved.",
    },
    "keys.ok.removed": {
        "ru": "Удалено: работает значение из окружения сервера, если оно задано.",
        "en": "Removed: the server environment value is in use, if it is set.",
    },
    "keys.err.empty": {"ru": "Заполните все поля.", "en": "Fill in all the fields."},
    "keys.err.shape": {
        "ru": "Это не похоже на ключ: без пробелов и переносов, не длиннее 400 знаков.",
        "en": "This does not look like a key: no spaces or line breaks, at most 400 characters.",
    },
    "keys.err.rejected": {
        "ru": "Провайдер не принял значение (ответ {status}). Ничего не сохранено.",
        "en": "The provider did not accept the value (response {status}). Nothing was saved.",
    },
    "keys.err.rejected_nostatus": {
        "ru": "Провайдер не принял значение. Ничего не сохранено.",
        "en": "The provider did not accept the value. Nothing was saved.",
    },
    "keys.err.unverified": {
        "ru": "Провайдер не ответил, значение не проверено и не сохранено. Повторите чуть позже.",
        "en": "The provider did not answer; the value is not checked or saved. Try again shortly.",
    },
    "keys.err.unverified_status": {
        "ru": "Провайдер ответил {status}, значение не проверено и не сохранено.",
        "en": "The provider answered {status}; the value is not checked or saved.",
    },
    "keys.err.no_secrets_key": {
        "ru": (
            "На сервере не задан ключ шифрования (SECRETS_KEY): хранить ключи нечем. "
            "Ничего не сохранено."
        ),
        "en": (
            "The server has no encryption key (SECRETS_KEY): nowhere to store keys. "
            "Nothing was saved."
        ),
    },
    "keys.err.db": {
        "ru": "База не ответила, ничего не записано. Повторите чуть позже.",
        "en": "The database did not answer, nothing was saved. Try again shortly.",
    },
    "keys.err.none": {
        "ru": "В админке ничего не задано: работает значение из окружения сервера.",
        "en": "Nothing is set in the admin: the server environment value is in use.",
    },
    "keys.err.no_factor": {
        "ru": "Включите второй шаг входа в Настройки → Безопасность. Без него ключи не меняются.",
        "en": (
            "Turn on the second sign-in step in Settings → Security. "
            "Keys cannot be changed without it."
        ),
    },
    "keys.err.prove_step": {
        "ru": (
            "Подтвердите второй шаг входа: Настройки → Безопасность → «Подтвердите, что это "
            "вы», затем вернитесь сюда (в течение 10 минут)."
        ),
        "en": (
            "Confirm the second sign-in step: Settings → Security → “Confirm it is you”, then "
            "come back here (within 10 minutes)."
        ),
    },
    "keys.err.rate": {
        "ru": "Слишком много попыток подряд. Повторите через {minutes} мин.",
        "en": "Too many attempts in a row. Try again in {minutes} min.",
    },
}
