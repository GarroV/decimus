"""Тексты блока «Ключ модели» на вкладке «Подключения» (D491).

Отдельным модулем по образцу `texts_connections.py`: сливаются в общий каталог
(`texts.TEXTS`). Ни один текст не принимает подстановок: ключ в страницу не попадает
ни частью, ни целиком (последние четыре знака рисует шаблон из записи, не из формы).
"""

from __future__ import annotations

MODEL_KEY_TEXTS: dict[str, dict[str, str]] = {
    "model_key.title": {"ru": "Ключ модели", "en": "Model key"},
    "model_key.sub": {
        "ru": (
            "Ключ провайдера нейросети, которым бот и веб разбирают комментарии и голосовые. "
            "Хранится зашифрованным и после сохранения нигде не показывается. "
            "Новый ключ начинает работать в течение минуты."
        ),
        "en": (
            "The AI provider key the bot and the web use to read comments and voice notes. "
            "It is stored encrypted and is never shown again after saving. "
            "A new key takes effect within a minute."
        ),
    },
    "model_key.provider": {"ru": "Провайдер", "en": "Provider"},
    "model_key.key": {"ru": "Ключ", "en": "Key"},
    "model_key.set": {"ru": "Поставлен", "en": "Set"},
    "model_key.from_env": {
        "ru": "Ключ на экране не задан: работает ключ из настроек сервера (запасной).",
        "en": "No key is set here: the key from the server settings (fallback) is in use.",
    },
    "model_key.unknown": {
        "ru": "Не удалось прочитать, что задано. Повторите чуть позже.",
        "en": "Could not read what is set. Try again shortly.",
    },
    "model_key.new": {"ru": "Новый ключ", "en": "New key"},
    "model_key.new_hint": {
        "ru": "Вставьте ключ целиком. Он не показывается ни до, ни после сохранения.",
        "en": "Paste the whole key. It is not shown before or after saving.",
    },
    "model_key.save": {"ru": "Сохранить", "en": "Save"},
    "model_key.check": {"ru": "Проверить", "en": "Check"},
    "model_key.delete": {"ru": "Удалить ключ", "en": "Remove key"},
    "model_key.delete_hint": {
        "ru": "После удаления снова работает ключ из настроек сервера.",
        "en": "After removal the key from the server settings is used again.",
    },
    "model_key.ok.saved": {
        "ru": "Ключ проверен и сохранён. Заработает во всех процессах в течение минуты.",
        "en": "The key was checked and saved. It takes effect in every process within a minute.",
    },
    "model_key.ok.checked": {
        "ru": "Провайдер принял ключ. Ничего не сохранено.",
        "en": "The provider accepted the key. Nothing was saved.",
    },
    "model_key.ok.removed": {
        "ru": "Ключ удалён: работает ключ из настроек сервера.",
        "en": "The key is removed: the key from the server settings is in use.",
    },
    "model_key.err.empty": {"ru": "Вставьте ключ.", "en": "Paste the key."},
    "model_key.err.shape": {
        "ru": "Это не похоже на ключ: он без пробелов и переносов, не длиннее 400 знаков.",
        "en": "This does not look like a key: no spaces or line breaks, at most 400 characters.",
    },
    "model_key.err.rejected": {
        "ru": "Ключ модели не принят провайдером. Ничего не сохранено.",
        "en": "The provider did not accept the model key. Nothing was saved.",
    },
    "model_key.err.unverified": {
        "ru": "Провайдер не ответил, ключ не проверен и не сохранён. Повторите чуть позже.",
        "en": "The provider did not answer; the key is not checked or saved. Try again shortly.",
    },
    "model_key.err.no_secrets_key": {
        "ru": (
            "На сервере не задан ключ шифрования (SECRETS_KEY): хранить ключ модели нечем. "
            "Ничего не сохранено."
        ),
        "en": (
            "The server has no encryption key (SECRETS_KEY): nowhere to store the model key. "
            "Nothing was saved."
        ),
    },
    "model_key.err.db": {
        "ru": "База не ответила, ничего не записано. Повторите чуть позже.",
        "en": "The database did not answer, nothing was saved. Try again shortly.",
    },
    "model_key.err.none": {
        "ru": "Ключа на экране и не было: работает ключ из настроек сервера.",
        "en": "There was no key set here: the key from the server settings is in use.",
    },
}
