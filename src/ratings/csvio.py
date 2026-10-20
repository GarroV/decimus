"""Чтение CSV выгрузок: кодировка, разделитель, номера строк.

Dodo IS отдаёт UTF-8 с BOM и запятой; тот же файл, пересохранённый в Excel,
приходит с `;`. Не UTF-8 — отказ с подсказкой, а не названия кракозябрами.
"""

from __future__ import annotations

import csv
import io

from .model import ERR_BAD_CSV, ERR_EMPTY, ERR_NOT_UTF8, ERR_TOO_MANY_ROWS, RatingsFormatError

#: Потолок строк выгрузки (F-127). Файл ограничен 25 МиБ (`web/ratings.py`), но
#: короткие строки дают из него сотни тысяч записей, каждая — списком строк в
#: памяти. Настоящая выгрузка по сети — десятки тысяч строк; полмиллиона — с запасом.
MAX_ROWS = 500_000


def decode(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise RatingsFormatError(
            "Файл не в UTF-8. Выгрузите CSV заново из Dodo IS или сохраните его как «CSV UTF-8»",
            ERR_NOT_UTF8,
        ) from exc


def read_table(data: bytes) -> tuple[tuple[str, ...], list[tuple[int, list[str]]]]:
    """Заголовок и непустые строки с номером строки файла (заголовок — строка 1)."""
    text = decode(data)
    if not text.strip():
        raise RatingsFormatError("Файл пустой", ERR_EMPTY)
    first = text.split("\n", 1)[0]
    delimiter = ";" if first.count(";") > first.count(",") else ","
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    try:
        header = tuple(cell.strip() for cell in next(reader))
        rows: list[tuple[int, list[str]]] = []
        for row in reader:
            if not any(cell.strip() for cell in row):
                continue
            if len(rows) >= MAX_ROWS:
                raise RatingsFormatError(
                    f"В файле больше {MAX_ROWS} строк. Разделите выгрузку на части",
                    ERR_TOO_MANY_ROWS,
                    limit=str(MAX_ROWS),
                )
            rows.append((reader.line_num, [cell.strip() for cell in row]))
    except csv.Error as exc:  # ячейка длиннее лимита, NUL и т. п.
        raise RatingsFormatError(
            f"Файл CSV повреждён и не читается ({exc}). Выгрузите его заново из Dodo IS",
            ERR_BAD_CSV,
        ) from exc
    return header, rows
