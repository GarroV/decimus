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

from src.report.letters import (
    BLANK_TEXT_FIELD,
    COVER_FIELDS,
    FINDING_TEXT_FIELD,
    FROM_LIVE,
    FROM_SHELF,
    FROM_SNAPSHOT,
    PLAN_DUE_FIELD,
)

from .errors import WebTextError
from .texts import UI_LANGS, t

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
    #: Насколько доля зоны сожжена, в процентах ШИРИНЫ ПОЛОСЫ. Это
    #: ОФОРМЛЕНИЕ, а не число оценки: на экран по-прежнему печатаются
    #: записанные `loss` и `share`, а это значение задаёт только длину
    #: заливки. Считается здесь, а не в шаблоне, потому что шаблон не
    #: считает ничего вовсе — иначе туда однажды переедет и арифметика
    #: оценки.
    fill: float = 0.0


def _fill(loss: Any, share: Any) -> float:
    """Какую часть доли зоны сожгли — в процентах ширины полосы.

    Ноль на любом непонятном входе, а не отказ: полоса — оформление, и
    сломанная ширина не повод не показать человеку записанные числа. Доля
    зоны нулевой быть не может по построению методики, но пришедший ноль
    здесь означает «нечем делить», а не «ничего не потеряно».
    """
    try:
        потеря, доля = float(loss), float(share)
    except (TypeError, ValueError):
        return 0.0
    if доля <= 0:
        return 0.0
    return round(min(потеря / доля, 1.0) * 100, 1)


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
                fill=_fill(zone.get("loss"), zone.get("share")),
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


#: Что сборщик письма не восстановил → ключ подписи в словаре интерфейса.
#:
#: Ключи словаря берутся ИЗ САМИХ констант сборщика, а не переписаны строками:
#: перечень невосстановленного — его язык, и переписанная копия разошлась бы с
#: ним при первом же переименовании, оставив экран молчать ровно о том, о чём
#: он обязан говорить.
_LETTER_CAVEATS = {
    **{поле: f"letter.caveat.cover.{поле}" for поле in COVER_FIELDS},
    PLAN_DUE_FIELD: "letter.caveat.plan_due",
    FINDING_TEXT_FIELD: "letter.caveat.speech_lang",
    BLANK_TEXT_FIELD: "letter.caveat.blank",
}

#: Откуда взята методика письма → ключ подписи. Сборщик отвечает на это
#: по-английски (строка написана для инструмента модели), а на экране рядом с
#: русскими подписями это был бы чужой язык посреди страницы.
_LETTER_SOURCES = {
    FROM_SNAPSHOT: "letter.source.snapshot",
    FROM_LIVE: "letter.source.live",
    FROM_SHELF: "letter.source.shelf",
}


def letter_caveats(codes: tuple[str, ...], lang: str) -> tuple[str, ...]:
    """Перечень невосстановленного — словами языка интерфейса.

    Незнакомый код показывается как есть, а не пропадает. Пропажа здесь стоит
    дороже некрасивой строки: каждый такой код — причина, по которой письмо
    нельзя отправлять, и молчание о ней вернуло бы экран к виду «всё хорошо».
    """
    return tuple(_letter_word(код, lang) for код in codes)


def _letter_word(code: str, lang: str) -> str:
    ключ = _LETTER_CAVEATS.get(code)
    return code if ключ is None else t(ключ, lang)


def letter_source(source: str, lang: str) -> str:
    """Откуда взята методика письма — словами. Незнакомое — как есть."""
    ключ = _LETTER_SOURCES.get(source)
    return source if ключ is None else t(ключ, lang)
