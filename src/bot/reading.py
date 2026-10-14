"""Показание термометра: разбор ответа аудитора и подпись числа (#836).

Модель путает цифры на дисплее (6 °C читается как 26 °C), поэтому прочитанное
число показывается отдельной строкой, а аудитор вводит верное. Здесь только
разбор и форма записи числа: пересчёт предложения — в `routers/record.py`.
"""

from __future__ import annotations

import re

from src.domain.models import READING_MAX_C, READING_MIN_C

#: Число с необязательным знаком и запятой или точкой; «°C» и пробелы вокруг
#: допустимы, больше ничего: «около 6» — не ответ, а рассуждение.
_NUMBER = re.compile(r"^\s*([+\-−]?\d{1,3}(?:[.,]\d{1,2})?)\s*(?:°\s*[CcСс]?|градус\w*)?\s*$")


def parse_reading(text: str) -> float | None:
    """Температура из ответа аудитора, °C. Не число или вне пределов термометра — `None`."""
    found = _NUMBER.match(text or "")
    if found is None:
        return None
    value = float(found.group(1).replace(",", ".").replace("−", "-"))
    return value if READING_MIN_C <= value <= READING_MAX_C else None


def reading_text(value: float) -> str:
    """Число как на дисплее: `6`, `-18`, `4.5` — без хвоста `.0`."""
    return f"{value:g}"
