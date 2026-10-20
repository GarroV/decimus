"""Разбор даты из живой фразы аудитора (задача #220).

Вынесено из `src/bot/info.py`: разбор даты — своя тема со своим набором правил,
а информационная часть про то, какие вопросы задаются и в каком порядке.
`info.py` продолжает отдавать `parse_date` наружу, так что зовущий код и тесты
о переносе не знают.

**Что здесь стережётся, и это две половины одного правила.**

Дату, которая в сообщении ЕСТЬ, надо находить: аудитор пишет «до 15.09.2026»,
«созвон 15 сентября», «September 15, 2026» — и до задачи #220 всё это получало
отказ, потому что разбор требовал дату в самом начале строки и только числами.
Владелец на живом прогоне: вычленить дату из сообщения — здесь даже модель не
нужна.

То, что датой НЕ является, датой стать не имеет права. Поле уезжает партнёру
как срок плана действий, и «15 упаковок» в нём хуже отказа. Поэтому число
считается датой только вместе с месяцем — числовым или названным словом, — а
неразобранное возвращает `None`, и вызывающий отказывает вслух.
"""

from __future__ import annotations

import re
from datetime import date

#: Как дата уезжает в отчёт партнёру. Совпадает с тем, как её печатает движок
#: (`engine/report.py: fmt_date`), и письмо такую строку пропускает как есть —
#: то есть срок плана действий читается человеком, а не машиной.
DATE_FORMAT = "%d.%m.%Y"

#: Год-месяц-день числами: единственная форма, где год стоит первым.
_ISO = re.compile(r"(?<!\d)(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})(?!\d)")

#: День-месяц-год числами. Разделители — те, которыми дату пишут в чате.
_DMY = re.compile(r"(?<!\d)(\d{1,2})\s*[.\-/]\s*(\d{1,2})\s*[.\-/]\s*(\d{2,4})(?!\d)")

#: День и месяц без года: «15.09». Год достраивается (см. `_year_ahead`).
#: Двоеточия в разделителях нет намеренно — иначе «18:30» стало бы 18 днём
#: 30-го месяца, а время перестало бы быть временем.
_DM = re.compile(r"(?<!\d)(\d{1,2})\s*[.\-/]\s*(\d{1,2})(?!\s*[.\-/]?\s*\d)")

#: Время рядом с датой: «18:30», «18 30», «в 18:30». Ищется в ОСТАТКЕ строки,
#: из которого вырезана сама дата, — поэтому «15.09» её цифрами не притворяется.
_TIME = re.compile(r"(?<!\d)([01]?\d|2[0-3])\s*[:.\s]\s*([0-5]\d)(?!\d)")

#: Месяц словом: основа и номер. Оба языка продукта сразу — язык ответа аудитора
#: параметром сюда не приходит, а живая фраза бывает и смешанной.
#:
#: Формы «мая/май/мае» выписаны целиком, а не основой `ма`: основа из двух букв
#: поймала бы «маркировку» и превратила бы её в срок. Остальные месяцы
#: однозначны своей основой, поэтому у них `\w*`.
_MONTHS: tuple[tuple[int, str], ...] = (
    (1, r"(?:январ\w*|jan(?:uary)?)"),
    (2, r"(?:феврал\w*|feb(?:ruary)?)"),
    (3, r"(?:март\w*|mar(?:ch)?)"),
    (4, r"(?:апрел\w*|apr(?:il)?)"),
    (5, r"(?:мая|май|мае|may)"),
    (6, r"(?:июн\w*|jun(?:e)?)"),
    (7, r"(?:июл\w*|jul(?:y)?)"),
    (8, r"(?:август\w*|aug(?:ust)?)"),
    (9, r"(?:сентябр\w*|sep(?:t|tember)?)"),
    (10, r"(?:октябр\w*|oct(?:ober)?)"),
    (11, r"(?:ноябр\w*|nov(?:ember)?)"),
    (12, r"(?:декабр\w*|dec(?:ember)?)"),
)

#: «15 сентября 2026», «15 September 2026», «3 марта».
_DAY_MONTH = tuple(
    (number, re.compile(rf"(?<!\d)(\d{{1,2}})\s+{name}\b(?:\s*,?\s*(\d{{4}})\b)?", re.IGNORECASE))
    for number, name in _MONTHS
)

#: «September 15, 2026», «сентября 15» — форма, которой пишут по-английски.
_MONTH_DAY = tuple(
    (number, re.compile(rf"\b{name}\s+(\d{{1,2}})(?:\s*,?\s*(\d{{4}})\b)?", re.IGNORECASE))
    for number, name in _MONTHS
)


def _year_ahead(day: int, month: int, today: date) -> int | None:
    """Год, не названный аудитором: ближайший, при котором дата не в прошлом.

    Оба поля, где спрашивается дата, смотрят вперёд — созвон с партнёром и срок
    плана действий. «3 марта», сказанное в сентябре, — это март следующего года,
    а не прошедший: срок в прошлом партнёру отправлять незачем.
    """
    for year in (today.year, today.year + 1):
        try:
            if date(year, month, day) >= today:
                return year
        except ValueError:
            return None  # такого дня в этом месяце нет — не дата
    return None


def _numeric(text: str, today: date) -> tuple[date, int, int] | None:
    """Дата числами: значение и границы занятого ею куска строки."""
    hit = _ISO.search(text)
    if hit is not None:
        year, month, day = (int(part) for part in hit.groups())
        return _made(year, month, day, hit)

    hit = _DMY.search(text)
    if hit is not None:
        day, month, year = (int(part) for part in hit.groups())
        if year < 100:
            year += today.year // 100 * 100
        return _made(year, month, day, hit)

    hit = _DM.search(text)
    if hit is not None:
        day, month = int(hit.group(1)), int(hit.group(2))
        if not 1 <= month <= 12:
            return None
        достроенный = _year_ahead(day, month, today)
        return None if достроенный is None else _made(достроенный, month, day, hit)
    return None


def _by_month_name(text: str, today: date) -> tuple[date, int, int] | None:
    """Дата с названным месяцем — в обеих формах: «15 сентября» и «September 15».

    Месяц без числа сюда не попадает вовсе: в «в сентябре» дня нет, а выдумать
    его значило бы отправить партнёру срок, которого никто не называл.
    """
    for формы in (_DAY_MONTH, _MONTH_DAY):
        for month, pattern in формы:
            hit = pattern.search(text)
            if hit is None:
                continue
            day = int(hit.group(1))
            named = hit.group(2)
            year = int(named) if named else _year_ahead(day, month, today)
            if year is None:
                return None
            return _made(year, month, day, hit)
    return None


def _made(year: int, month: int, day: int, hit: re.Match[str]) -> tuple[date, int, int] | None:
    """Собрать дату и запомнить, какой кусок строки она заняла.

    Разобрали числа, но такой даты нет (31.02, 45-й месяц) — это не дата, и
    записывать её нельзя ровно так же, как неразобранный текст.
    """
    try:
        parsed = date(year, month, day)
    except ValueError:
        return None
    return parsed, hit.start(), hit.end()


def parse_date(text: str, *, today: date | None = None) -> str | None:
    """Разобрать дату в записываемый вид — или ничего, если это не дата.

    Дата ищется в любом месте фразы: «до 15.09.2026», «созвон 15 сентября»,
    «September 15, 2026». Год, если не назван, достраивается вперёд.

    Время, если оно названо, остаётся рядом с датой — и до неё, и после:
    поле спрашивает дату **и время** созвона, и терять половину ответа нельзя.
    Ищется оно в остатке строки без самой даты, иначе «15.09» превратилось бы
    в 15:09.
    """
    сейчас = today or date.today()
    found = _numeric(text, сейчас) or _by_month_name(text, сейчас)
    if found is None:
        return None
    parsed, начало, конец = found
    stamp = parsed.strftime(DATE_FORMAT)
    clock = _TIME.search(text[:начало] + " " + text[конец:])
    if clock is None:
        return stamp
    return f"{stamp} {int(clock.group(1)):02d}:{clock.group(2)}"
