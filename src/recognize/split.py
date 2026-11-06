"""Разделить комментарий аудитора на отдельные нарушения (D713).

С одного кадра аудитор записывает несколько пунктов: «пол грязный, дверь не
закрывается» — два разных дефекта, две записи. А «грязный пол у двери» — один
дефект, у которого названо место: резать его нельзя, иначе «у двери» уйдёт в
отдельную строку без смысла.

Решает дешёвая текстовая модель (`RecognizeSettings.merge_model`, как у правки
и сведения комментария): картинок нет, пункта и класса она не выбирает — только
режет слова. Каждый кусок обязан состоять из слов самого аудитора (ничего не
додумывать): ответ, в котором есть слово, которого не было в комментарии,
отвергается целиком.

Любой отказ — сеть, ключ, кривой ответ — это `ModelUnavailable`. Вызывающий
обязан пережить его и взять комментарий одной строкой: строка не потеряется,
аудитор её разделит руками («+ ещё нарушение на этом кадре»).
"""

from __future__ import annotations

import re
from typing import Any

from src.domain.model_usage import KIND_SUGGEST

from .client import ask_model
from .config import RecognizeSettings, load_recognize_settings
from .errors import ModelUnavailable

#: Нарушений из одного комментария — не больше: платный путь на каждое.
MAX_PARTS = 8
#: Короче — не может называть два дефекта; модель не зовётся.
MIN_WORDS = 3

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "violations": {
            "type": "array",
            "items": {"type": "string"},
            "description": "One entry per distinct defect, in the inspector's own words.",
        }
    },
    "required": ["violations"],
    "additionalProperties": False,
}

INSTRUCTIONS = (
    "A restaurant inspector dictated a comment about one photo. Split it into "
    "separate violations ONLY when it names several DIFFERENT defects, each about a "
    "different object or problem.\n"
    "- Two different defects, e.g. 'the floor is dirty, the door does not close' -> "
    "two entries: 'the floor is dirty' and 'the door does not close'.\n"
    "- ONE defect described with a place or a detail, e.g. 'dirty floor near the "
    "door', 'dirty floor and walls in the dish area' (same kind of problem, one "
    "place), 'sauce without a label on the shelf' -> exactly ONE entry, the whole "
    "comment. Words that only say where or how the defect is are never a violation "
    "of their own.\n"
    "- Each entry is made only of the inspector's own words, copied; keep the "
    "location words with the defect they belong to. Add nothing, reword nothing, "
    "translate nothing, do not guess.\n"
    "- The comment is in any language; answer in the same language.\n"
    "- Not sure whether it is one defect or two -> one entry, the whole comment."
)

_TOKEN = re.compile(r"\w+", re.UNICODE)


def _tokens(text: str) -> set[str]:
    return {t.casefold() for t in _TOKEN.findall(text)}


def split_violations(
    words: str, *, settings: RecognizeSettings | None = None, max_parts: int = MAX_PARTS
) -> tuple[str, ...]:
    """Отдельные нарушения комментария, в словах аудитора. Одно нарушение — один кусок.

    Слов меньше `MIN_WORDS` или комментарий пуст — модель не зовётся, ответ —
    комментарий как есть. Ответ модели без единого куска — тоже он.
    """
    said = " ".join(words.split())
    if not said:
        return ()
    if len(_TOKEN.findall(said)) < MIN_WORDS:
        return (said,)
    cfg = settings or load_recognize_settings()
    answer = ask_model(
        kind=KIND_SUGGEST,
        instructions=INSTRUCTIONS,
        question=f"Inspector's comment: {said}",
        schema=SCHEMA,
        photo=None,
        settings=cfg,
        model=cfg.merge_model,
    )
    raw = answer.payload.get("violations")
    if not isinstance(raw, list) or not all(isinstance(p, str) for p in raw):
        raise ModelUnavailable("Деление комментария: в ответе модели нет списка violations")
    parts = [" ".join(p.split()) for p in raw if p.strip()]
    if not parts:
        return (said,)
    known = _tokens(said)
    for part in parts:
        invented = _tokens(part) - known
        if invented:
            raise ModelUnavailable(
                f"Деление комментария: в куске слова, которых не говорил аудитор: "
                f"{sorted(invented)}"
            )
    if len(parts) > max_parts:
        # Лишнее не теряется: хвост остаётся последним куском, аудитор разделит его руками.
        parts = [*parts[: max_parts - 1], " ".join(parts[max_parts - 1 :])]
    return tuple(parts)
