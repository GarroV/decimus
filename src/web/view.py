"""Подготовка того, что уже посчитано, к показу.

Здесь разрешено только выбирать и раскладывать: взять формулировку на нужном
языке, назвать тон метки, разложить словарь в строки таблицы в устойчивом
порядке. Считать запрещено — ни процентов, ни сумм, ни долей. Всё, что похоже
на число, приходит из базы ровно таким, каким его положил движок.

Тон метки — это не цвет, а имя класса дизайн-системы (`forma`): буква оценки и
класс нарушения единственные два места, где продукт берёт сильный цвет
(`dodo/decimus/domain.css`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .errors import WebTextError
from .texts import UI_LANGS

#: Буква оценки → тон метки `forma`. Буквы приходят из движка (`data/scoring.json`),
#: и неизвестная буква получает нейтральный тон, а не пропадает с экрана:
#: «оценка есть, но я её не знаю» — это то, что человеку и надо увидеть.
_GRADE_TONES = {"A": "tag--ok", "B": "tag--neutral", "C": "tag--warn", "D": "tag--err"}

#: Класс нарушения → тон метки. D1 намеренно нейтрален: он снимает 0,5 %, и
#: если красить и его, тревожным станет весь отчёт, а D3 перестанет читаться
#: (`dodo/decimus/domain.css`).
_LEVEL_TONES = {"D1": "tag--neutral", "D2": "tag--warn", "D3": "tag--err"}


def grade_tone(grade: str) -> str:
    """Имя класса метки для буквы оценки."""
    return _GRADE_TONES.get(grade.strip().upper(), "tag--neutral")


def level_tone(level: str) -> str:
    """Имя класса метки для класса нарушения."""
    return _LEVEL_TONES.get(level.strip().upper(), "tag--neutral")


def pick(ru: object, en: object, lang: str) -> str:
    """Выбрать формулировку по языку интерфейса. Неизвестный язык — отказ.

    Правило то же, что в методике (`domain.models.pick_text`) и у бота: тихий
    откат на русский показал бы управляющей компании половину экрана не на её
    языке, и заметила бы это только она.
    """
    if lang not in UI_LANGS:
        raise WebTextError(f"Язык интерфейса «{lang}» не заведён. Доступны: {', '.join(UI_LANGS)}")
    return str(ru if lang == "ru" else en)


@dataclass(frozen=True)
class ZoneLine:
    """Строка разбивки по зонам — ровно то, что лежит в базе."""

    code: str
    name: str
    share: str
    loss: str
    left: str
    zeroed: bool


def zone_lines(by_zone: dict[str, Any], lang: str) -> tuple[ZoneLine, ...]:
    """Разбивка по зонам из `inspections.by_zone` в порядке кода зоны.

    Значения переносятся строками как есть. Ни сложения, ни округления: доля,
    потеря и остаток посчитаны движком, и любое действие над ними здесь было бы
    вторым расчётом оценки, пусть и незаметным.
    """
    lines = []
    for code in sorted(by_zone):
        zone = by_zone[code]
        lines.append(
            ZoneLine(
                code=str(zone.get("code", code)),
                name=pick(zone.get("name_ru", code), zone.get("name_en", code), lang),
                share=_as_text(zone.get("share")),
                loss=_as_text(zone.get("loss")),
                left=_as_text(zone.get("left")),
                zeroed=bool(zone.get("zeroed", False)),
            )
        )
    return tuple(lines)


@dataclass(frozen=True)
class CountLine:
    """Счётчик записей одного класса."""

    level: str
    count: str
    tone: str


def count_lines(counts: dict[str, Any]) -> tuple[CountLine, ...]:
    """Счётчики классов из `inspections.counts` в порядке класса.

    Классы приходят из методики (`D0`, `D1`, …), поэтому порядок — сортировка
    ключа, а не зашитый список: добавленный класс появится сам, а не пропадёт
    молча.
    """
    return tuple(
        CountLine(level=level, count=_as_text(counts[level]), tone=level_tone(level))
        for level in sorted(counts)
    )


def _as_text(value: object) -> str:
    """Число из базы → строка для экрана, без единого действия над значением.

    `Decimal`, `float` и `int` печатаются своим же `str`: формат чисел задаёт
    движок, а «причесать» его здесь означало бы показать не то, что записано.
    Прочерк — только когда значения нет вовсе.
    """
    if value is None:
        return "—"
    return str(value)
