"""Тексты метки «главный чек-лист» и шапки «Методики» (D440).

Отдельным модулем, а не строками в `texts.py`: тот длиннее предела файла.
Сливаются в общий каталог (`texts.TEXTS`) — `t()` знает один словарь.
"""

from __future__ import annotations

MASTER_TEXTS: dict[str, dict[str, str]] = {
    "methodology.master.badge": {"ru": "Главный", "en": "Master"},
    "methodology.master.hint": {
        "ru": (
            "Главный чек-лист правят только админы. Бизнес-девелопер видит его и "
            "проводит по нему проверки."
        ),
        "en": (
            "Only admins edit the master checklist. A business developer can view it "
            "and run inspections on it."
        ),
    },
    "methodology.master.set": {"ru": "Сделать главным", "en": "Mark as master"},
    "methodology.master.unset": {"ru": "Снять метку «Главный»", "en": "Remove “Master” mark"},
    "methodology.master.readonly.title": {
        "ru": "Главный чек-лист: только чтение",
        "en": "Master checklist: read-only",
    },
    "methodology.master_readonly": {
        "ru": "Главный чек-лист правят только админы. Здесь его можно смотреть, но не менять.",
        "en": "Only admins edit the master checklist. You can view it here but not change it.",
    },
    "methodology.apply_admins_only": {
        "ru": "Применять чек-лист к проду могут только админы.",
        "en": "Only admins can apply a checklist to production.",
    },
    "methodology.master_toggle_admins_only": {
        "ru": "Метку «Главный» ставят и снимают только админы.",
        "en": "Only admins can set or remove the “Master” mark.",
    },
    "methodology.pending.label": {
        "ru": "Есть неопубликованные правки",
        "en": "Unpublished edits",
    },
}
