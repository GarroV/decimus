"""Bounded human answers paired with untrusted clarification questions."""

from __future__ import annotations

from typing import Any

from .errors import ValidationError

MAX_LEVEL_WORDS = 1000
MAX_CLARIFICATIONS = 6


def clarification_chain(
    value: Any, *, words: str = "", answers_in_words: bool = False
) -> list[dict[str, str]]:
    if not isinstance(value, list) or len(value) > MAX_CLARIFICATIONS:
        raise ValidationError("Недопустимая цепочка уточнений")
    result = []
    for pair in value:
        if not isinstance(pair, dict) or set(pair) != {"question", "answer"}:
            raise ValidationError("Нужны отдельные вопрос и человеческий ответ")
        question, answer = pair["question"], pair["answer"]
        if not isinstance(question, str) or not isinstance(answer, str):
            raise ValidationError("Вопрос и ответ должны быть текстом")
        question, answer = question.strip(), answer.strip()
        if not question or not answer or len(question) > 500 or len(answer) > 1000:
            raise ValidationError("Уточнение пусто или превышает предел")
        result.append({"question": question, "answer": answer})
    total = len(words) + sum(
        len(p["question"]) + (0 if answers_in_words else len(p["answer"])) for p in result
    )
    if total > MAX_LEVEL_WORDS:
        raise ValidationError("Слова и уточнения превышают предел запроса")
    return result


def bound_class_context(
    value: Any,
    *,
    run_id: str,
    checklist_version: str | None,
    code: str,
    zone: str,
    photos: list[str],
    words: str,
) -> list[dict[str, str]]:
    if not isinstance(value, dict) or set(value) != {
        "clarifications",
        "run_id",
        "checklist_version",
        "code",
        "zone",
        "photo_refs",
    }:
        raise ValidationError("Недопустимый контекст уточнений")
    expected = {
        "run_id": run_id,
        "checklist_version": checklist_version,
        "code": code,
        "zone": zone,
        "photo_refs": photos,
    }
    if any(value.get(key) != expected[key] for key in expected):
        raise ValidationError("Контекст уточнений относится к другой записи")
    chain = clarification_chain(value["clarifications"], words=words, answers_in_words=True)
    if not chain or any(pair["answer"] not in words for pair in chain):
        raise ValidationError("Человеческие ответы должны сохраняться в исходных словах")
    return chain
