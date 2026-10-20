"""Класс нарушения по критериям пункта: второй, узкий вопрос к модели (#1033).

Первый вопрос (`classify`) выбирает пункт по ПОЛНОМУ перечню, и критерии каждого
из сотен пунктов в него не влезают: туда идут только пороги классов из карты
слов. Когда пункт выбран, у него есть полный текст критериев (`criteria.md`), и
класс определяется по ним — по факту, а не «по похожести»: одного выполненного
условия класса достаточно, а там, где фактов не хватает, спрашивается один факт.

Запрос собирается тем же `AskArgs`, что и у `classify`: вызов и учёт расхода идут
одной дорогой (`recognize.client`), а пакетом их шлёт вызывающий.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from src.domain.model_usage import KIND_RECOGNIZE

from .classify import AskArgs
from .client import ModelAnswer
from .config import RecognizeSettings
from .guard import MAX_QUESTION_CHARS, clean_text
from .prompt import DATA_BLOCKS_LINE, TAG_NOTE, data_block

#: Критерии длинные, но обрезать их нельзя: недостающий кусок — это пропавшее
#: условие класса. Потолок защищает только от мусора.
MAX_CRITERIA_CHARS = 8000

TAG_CRITERIA = "checklist_criteria"

_INSTRUCTIONS = (
    "Ты помощник аудитора выездной проверки пиццерии. Пункт методики уже выбран. "
    "Твоя задача одна: определить КЛАСС нарушения по критериям этого пункта и "
    "фактам из слов аудитора.\n\n"
    f"{DATA_BLOCKS_LINE}\n\n"
    "Правила:\n"
    "- Класс определяется фактом. Факты подпадают под условие класса — этот класс, "
    "не мягче и не жёстче «на всякий случай».\n"
    "- Критерии класса часто перечисляют альтернативы («или», разные условия): "
    "достаточно ОДНОГО выполненного условия. Не требуй выполнения остальных.\n"
    "- Если фактам отвечают условия нескольких классов — бери старший из них.\n"
    "- Числа, названные аудитором, — истина: не перепроверяй их.\n"
    "- Ничего не додумывай. Если факта, нужного для различия классов, в словах нет — "
    "поставь самый мягкий класс, который подтверждён фактами, а в `need_fact` задай "
    "ОДИН короткий вопрос о недостающем факте. Фактов хватает — `need_fact` пустая "
    "строка."
)


@dataclass(frozen=True)
class LevelAnswer:
    """Класс по критериям и недостающий факт, если он есть."""

    level: str
    need_fact: str
    reason: str


def _schema(levels: Sequence[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["level", "need_fact", "reason"],
        "properties": {
            "level": {"type": "string", "enum": list(levels)},
            "need_fact": {
                "type": "string",
                "description": "Один вопрос о недостающем факте; пустая строка — фактов хватает.",
            },
            "reason": {
                "type": "string",
                "description": "Какое условие каких критериев выполнено фактом.",
            },
        },
    }


def level_request(
    note: str,
    *,
    code: str,
    levels: Sequence[str],
    criteria: str,
    lang: str,
    settings: RecognizeSettings,
    model: str | None = None,
) -> AskArgs:
    """Запрос на класс: слова аудитора, допустимые классы пункта и его критерии."""
    question = (
        f"ПУНКТ: {code}\n"
        f"ДОПУСТИМЫЕ КЛАССЫ: {', '.join(levels)}\n"
        f"ЯЗЫК ВОПРОСА need_fact: {lang}\n\n"
        f"КРИТЕРИИ ПУНКТА:\n{data_block(TAG_CRITERIA, criteria[:MAX_CRITERIA_CHARS])}\n\n"
        f"КОММЕНТАРИЙ АУДИТОРА: {data_block(TAG_NOTE, note.strip() or '(пусто)')}"
    )
    return AskArgs(
        kind=KIND_RECOGNIZE,
        instructions=_INSTRUCTIONS,
        question=question,
        schema=_schema(levels),
        photo=None,
        photos=(),
        settings=settings,
        model=model,
    )


def level_from(answer: ModelAnswer, levels: Sequence[str]) -> LevelAnswer | None:
    """Разобрать ответ. Класс вне допустимых (схема это запрещает) — `None`, а не догадка."""
    payload = answer.payload
    level = str(payload.get("level", "")).strip()
    if level not in levels:
        return None
    return LevelAnswer(
        level=level,
        need_fact=clean_text(str(payload.get("need_fact", "")), MAX_QUESTION_CHARS),
        reason=clean_text(str(payload.get("reason", "")), MAX_QUESTION_CHARS),
    )
