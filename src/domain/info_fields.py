"""Состав информационной части проверки: какие поля и каким способом вводятся (T158, D312).

Живёт в домене, а не в боте: поля заполняют две поверхности — бот в конце
проверки и мини-апп обхода по ходу, — и список у них обязан быть один. Почему
полей семь и чем они разные — `src/bot/info.py`.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Свободный текст: пишется, наговаривается или приходит подписью к кадру.
KIND_TEXT = "text"
#: Да или нет — кнопками.
KIND_YES_NO = "yes_no"
#: Дата (у `INF05` — с временем): текстом или голосом, с разбором.
KIND_DATE = "date"


@dataclass(frozen=True)
class InfoField:
    """Одно поле информационной части: код пункта и способ ввода."""

    code: str
    kind: str


#: Порядок — порядок чек-листа, и он же порядок в отчёте: движок печатает поля
#: в том порядке, в каком их записали. Спрашивать вразнобой значило бы получить
#: вразнобой и в документе партнёру.
FIELDS: tuple[InfoField, ...] = (
    InfoField("INF01", KIND_TEXT),
    InfoField("INF03", KIND_YES_NO),
    InfoField("INF04", KIND_YES_NO),
    InfoField("INF05", KIND_DATE),
    InfoField("INF06", KIND_TEXT),
    InfoField("INF07", KIND_DATE),
    InfoField("INF08", KIND_TEXT),
)


#: Значения «да/нет» на языке ОТЧЁТА (их читает партнёр): те же слова, что бот
#: кладёт кнопками (`info.value_yes/no` в `src/bot/texts.py`).
_YES_NO_WORDS = {"ru": ("Да", "Нет"), "en": ("Yes", "No")}
_YES = frozenset({"да", "yes", "y", "true", "1", "д"})
_NO = frozenset({"нет", "no", "n", "false", "0", "н"})


def yes_no_value(answer: object, lang: str) -> str | None:
    """«Да»/«Нет» на языке отчёта — или `None`, если это не да/нет.

    Язык, которого нет в таблице, получает английские слова.
    """
    if isinstance(answer, bool):
        word = "yes" if answer else "no"
    elif isinstance(answer, str):
        word = answer.strip().lower()
    else:
        return None
    yes, no = _YES_NO_WORDS.get(lang, _YES_NO_WORDS["en"])
    if word in _YES:
        return yes
    if word in _NO:
        return no
    return None
