"""Короткие ответы словами, которые правят запись без разбора (D254, D255).

Правка ответом на сообщение бота ищет пункт заново по словам (D081). Но
несколько ответов о пункте не говорят вовсе — «да», «не повтор», «класс D2», —
и отправь их в разбор, модель получила бы два слова без записи, о которой они,
и вернула бы не то или ничего. Такие ответы узнаются здесь, строго целиком:
фраза, в которой есть что-то ещё, уходит в разбор как раньше.

Слова приняты на обоих языках сразу, а не на языке интерфейса: проверяющий
говорит на языке речи, и тот не обязан совпадать с языком кнопок.
"""

from __future__ import annotations

import re

#: Знаки по краям ответа, которые смысла не меняют: «Да!», «нет.», «D2?».
_EDGES = " \t\n.,!?;:«»\"'()"

_YES = frozenset({"да", "ага", "угу", "yes", "yep", "y", "+"})
_NO = frozenset({"нет", "не", "no", "nope", "n", "-"})

#: «повтор», «это повтор», «повтор x2», «repeat» — поставить пометку.
_REPEAT_ON = re.compile(r"^(?:это\s+|it\s+is\s+a\s+|a\s+)?(?:повтор|repeat)(?:\s*[x×х]\s*2)?$")
#: «не повтор», «это не повтор», «not a repeat», «no repeat» — снять.
_REPEAT_OFF = re.compile(
    r"^(?:это\s+)?не\s+повтор$|^(?:it\s+is\s+)?not\s+(?:a\s+)?repeat$|^no\s+repeat$"
)
#: «D2», «класс D2», «это д2», «class D2» — сменить класс. Кириллическая «д»
#: наравне с латинской: расшифровка голоса и телефонная раскладка дают обе.
_LEVEL = re.compile(r"^(?:(?:это|класс|уровень|class|level|it\s+is)\s+)*[dд]\s*([1-3])$")


def _plain(text: str) -> str:
    return " ".join(text.strip(_EDGES).lower().split())


def yes_no(text: str) -> bool | None:
    """«Да» — `True`, «нет» — `False`, что-то другое — `None`."""
    слово = _plain(text)
    if слово in _YES:
        return True
    if слово in _NO:
        return False
    return None


def repeat_mark(text: str) -> bool | None:
    """«Повтор» — `True`, «не повтор» — `False`, что-то другое — `None`."""
    фраза = _plain(text)
    if _REPEAT_OFF.match(фраза):
        return False
    if _REPEAT_ON.match(фраза):
        return True
    return None


def spoken_level(text: str) -> str | None:
    """Класс, названный ответом целиком («класс D2» → `D2`), — или ничего."""
    найдено = _LEVEL.match(_plain(text))
    return None if найдено is None else f"D{найдено.group(1)}"
