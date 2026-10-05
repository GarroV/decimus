"""Тексты заведения пиццерии из веб-админки (#437, D233, D240).

Отдельным модулем, а не строками в `texts.py`: тот уже длиннее предела файла.
Сливаются в общий каталог (`texts.TEXTS`) — `t()` знает один словарь. Коды
отказов — из `src/domain/unit_new.py`: экран переводит код, а не текст домена.
"""

from __future__ import annotations

UNIT_TEXTS: dict[str, dict[str, str]] = {
    "unitnew.open": {"ru": "Добавить пиццерию", "en": "Add a pizzeria"},
    "unitnew.title": {"ru": "Новая пиццерия", "en": "New pizzeria"},
    "unitnew.back": {"ru": "К стране", "en": "Back to the country"},
    "unitnew.name": {"ru": "Город и номер", "en": "City and number"},
    "unitnew.name_hint": {
        "ru": "Как называют внутри компании: город и номер. Можно на любом языке — "
        "имя сведётся к английскому, например «Белград 6» станет Belgrade-6.",
        "en": "The way the company names it: city and number. Any language works — "
        "the name is brought to English, e.g. «Белград 6» becomes Belgrade-6.",
    },
    "unitnew.submit": {"ru": "Добавить", "en": "Add"},
    "unitnew.confirm.title": {
        "ru": "Города «{city}» нет в словаре сети",
        "en": "The city «{city}» is not in the network's dictionary",
    },
    "unitnew.confirm.text": {
        "ru": "Пиццерия заведётся как {name} в стране {country}. Если это район или "
        "адрес, а не город, исправьте название.",
        "en": "The pizzeria will be added as {name} in {country}. If this is a district "
        "or an address rather than a city, correct the name.",
    },
    "unitnew.confirm.submit": {
        "ru": "Да, новая пиццерия {name}",
        "en": "Yes, new pizzeria {name}",
    },
    "unitnew.exists": {
        "ru": "Пиццерия {name} в справочнике уже есть.",
        "en": "The pizzeria {name} is already in the directory.",
    },
    "unitnew.exists.open": {"ru": "Открыть её карточку", "en": "Open its card"},
    "unitnew.failed": {
        "ru": "Справочник не ответил, пиццерия не заведена. Попробуйте ещё раз.",
        "en": "The directory did not respond; the pizzeria was not added. Try again.",
    },
    "unitnew.refused.empty": {
        "ru": "Напишите город и номер пиццерии.",
        "en": "Enter the city and the pizzeria's number.",
    },
    "unitnew.refused.too_long": {
        "ru": "Название длиннее {limit} знаков.",
        "en": "The name is longer than {limit} characters.",
    },
    "unitnew.refused.need_number": {
        "ru": "В «{typed}» нет номера. Пиццерия называется городом и номером: Belgrade-6.",
        "en": "«{typed}» has no number. A pizzeria is named by city and number: Belgrade-6.",
    },
    "unitnew.refused.other_country": {
        "ru": "{name} — пиццерия другой страны ({country}). Заведите её на экране своей страны.",
        "en": "{name} belongs to another country ({country}). Add it from that country's screen.",
    },
    "unitnew.refused.unknown_country": {
        "ru": "Такой страны в словаре сети нет.",
        "en": "This country is not in the network's dictionary.",
    },
    "unitnew.added": {
        "ru": "Пиццерия {name} добавлена в справочник. Проверок у неё пока нет.",
        "en": "The pizzeria {name} was added to the directory. It has no inspections yet.",
    },
}
