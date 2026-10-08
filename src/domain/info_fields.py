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
