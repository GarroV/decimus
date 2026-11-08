"""Тексты переключателя пространств главного админа (D726)."""

from __future__ import annotations

PEEK_TEXTS: dict[str, dict[str, str]] = {
    "peek.switch.label": {"ru": "Пространство", "en": "Space"},
    "peek.home": {"ru": "УК", "en": "HQ"},
    "peek.bar": {
        "ru": "Вы смотрите как партнёр «{name}» · только просмотр",
        "en": "You are viewing as partner “{name}” · view only",
    },
    "peek.bar.back": {"ru": "Вернуться в УК →", "en": "Back to HQ →"},
    "peek.refused.title": {"ru": "Только просмотр", "en": "View only"},
    "peek.refused.note": {
        "ru": (
            "Вы смотрите как партнёр, поэтому изменения отключены. Вернитесь в УК, чтобы работать."
        ),
        "en": (
            "You are viewing as a partner, so changes are turned off. "
            "Go back to HQ to make changes."
        ),
    },
}
