"""Шаблон письма партнёру: слоты, подстановки-блоки и проверка текста (D550, D608, #977, #1130).

Админка УК хранит свой текст письма на слот (вид письма) и язык; движок
(`engine/report.py`) подставляет в него блоки и собирает письмо. Перечень подстановок —
это то, что движок умеет; он живёт и в движке (`LETTER_FIELDS`), потому что движок
отдельный процесс и не импортирует `src`. Расхождение двух перечней ловит
`tests/test_letter_template.py`.

Оценку, проценты, сводку по зонам и критичное шаблон НЕ считает: он только ставит в текст
то, что дал движок. Неизвестная подстановка — отказ при сохранении, а не пустое место в
письме партнёру.
"""

from __future__ import annotations

import string

#: Слоты: план при D1/D2/D3, информационные/рекомендательные записи, без записей.
SLOT_PLAN = "plan"
SLOT_CLEAN = "clean"
SLOT_EMPTY = "empty"
SLOTS = (SLOT_PLAN, SLOT_CLEAN, SLOT_EMPTY)

#: Языки письма, на которых админка хранит текст.
LANGS = ("ru", "en")

#: Подстановки-блоки, которые умеет движок. Порядок — порядок показа в редакторе.
FIELDS = (
    "unit",
    "date",
    "city",
    "type",
    "grade",
    "pct",
    "grade_note",
    "summary_lines",
    "critical_block",
    "good_block",
    "end_block",
    "plan_due",
)

#: Предел длины текста: письмо читают глазами, а не выгрузкой.
BODY_MAX = 6000


#: Коды отказа `problem_of`: экран переводит их на язык интерфейса, не разбирая русский текст.
ERR_EMPTY = "empty"
ERR_LONG = "long"
ERR_CONTROL = "control"
ERR_MARKUP = "markup"
ERR_UNKNOWN = "unknown"
ERR_FORMAT = "format"

_PROBLEM_RU = {
    ERR_EMPTY: "Текст шаблона пуст",
    ERR_LONG: f"Текст шаблона длиннее {BODY_MAX} знаков",
    ERR_CONTROL: "В тексте шаблона есть недопустимые управляющие знаки",
    ERR_MARKUP: "Разметка подстановок нарушена; одиночную скобку пишут двойной",
    ERR_UNKNOWN: "Неизвестная подстановка {arg}. Доступны: " + ", ".join(FIELDS),
    ERR_FORMAT: "У подстановки {arg} не бывает формата",
}


def problem_of(body: str) -> tuple[str, str] | None:
    """Почему текст не годится как шаблон: `(код, аргумент)`; `None` — годится.

    Одиночная фигурная скобка, подстановка с форматом (`{pct:.1f}`) и неизвестное имя —
    отказ: движок такой текст не соберёт. Аргумент — подстановка из текста, если код о ней.
    """
    if not body.strip():
        return ERR_EMPTY, ""
    if len(body) > BODY_MAX:
        return ERR_LONG, ""
    if any(ord(ch) < 32 and ch not in "\n\r\t" for ch in body):
        return ERR_CONTROL, ""
    try:
        parsed = list(string.Formatter().parse(body))
    except ValueError:
        return ERR_MARKUP, ""
    for _, name, spec, conv in parsed:
        if name is None:
            continue
        if name not in FIELDS:
            return ERR_UNKNOWN, "{" + name + "}"
        if spec or conv:
            return ERR_FORMAT, "{" + name + "}"
    return None


def problem(body: str) -> str:
    """То же, что `problem_of`, но словами по-русски; пусто — годится."""
    найдено = problem_of(body)
    if найдено is None:
        return ""
    код, аргумент = найдено
    return _PROBLEM_RU[код].replace("{arg}", аргумент)
