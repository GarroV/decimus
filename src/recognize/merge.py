"""Свести комментарий записи, к которой лёг ещё один кадр (#443, решение D247).

Нарушение уникально по паре «пункт + зона» (`docs/02-domain.md`): несколько
однотипных объектов в одной зоне — одна запись с несколькими фотографиями.
Аудитор при этом шлёт кадры по одному и к каждому говорит своё: «соус без
маркировки», через полчаса — «и майонез тоже». Кадр ложится в уже занятую
запись, а её текст должен назвать оба объекта — одной фразой, а не склейкой
двух реплик.

Сводит дешёвая текстовая модель (`RecognizeSettings.merge_model`): картинок
здесь нет, решения о пункте, классе и зоне тоже — только формулировка.
Правила фиксации в силе полностью: назвать только то, что прозвучало (правило
2 — никаких «в нескольких местах», если аудитор этого не сказал), и выдать
факт, а не реплику о нём (правило 13). Второй слой — тот же сторож
формулировок, что стоит после основной модели (`rules_check`): ответ, который
приносит пометку, которой не было ни в прежнем тексте, ни в словах аудитора,
отвергается целиком.

Любой отказ — сеть, ключ, пустой или подозрительный ответ — это
`ModelUnavailable`. Вызывающий обязан пережить его: кадр прикрепляется всегда,
а текст записи тогда остаётся прежним.
"""

from __future__ import annotations

from typing import Any

from .client import ask_model
from .config import DEFAULT_LANG, RecognizeSettings, load_recognize_settings
from .errors import ModelUnavailable
from .rules_check import check_wording

#: Схема ответа: одна строка, ничего сверх неё.
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"text": {"type": "string"}},
    "required": ["text"],
    "additionalProperties": False,
}

#: Имя языка в инструкции. Незнакомый код передаётся как есть — модель его
#: поймёт, а язык остаётся параметром, а не константой.
_LANG_NAMES = {"ru": "Russian", "en": "English"}

INSTRUCTIONS = (
    "You maintain the wording of one finding in a restaurant inspection report. "
    "The same violation (same checklist item, same zone) was photographed again, "
    "and the inspector said new words about it. Merge the current wording and the "
    "inspector's new words into ONE sentence that states the fact.\n"
    "Rules:\n"
    "- Name only objects and details present in the current wording or in the "
    "inspector's words. Invent nothing.\n"
    "- Never add scale that was not said: no 'in several places', 'everywhere', "
    "'throughout', 'over several metres', counts or durations of your own.\n"
    "- Do not guess the nature of damage (corrosion, cracks, mould) unless it was said.\n"
    "- Output the finding itself: no questions, no remarks to the inspector, no "
    "'suggested wording', no quotes around it.\n"
    "- Keep it short. If the new words add nothing, return the current wording unchanged.\n"
    "- Write in {lang}."
)


def merge_wording(
    previous: str,
    words: str,
    *,
    lang: str = DEFAULT_LANG,
    settings: RecognizeSettings | None = None,
) -> str:
    """Одна фраза-факт из прежнего текста записи и новых слов аудитора.

    Пустые новые слова — сводить нечего, модель не зовётся и возвращается
    прежний текст: платить за вопрос без материала незачем.
    """
    was = previous.strip()
    said = words.strip()
    if not said:
        return was
    cfg = settings or load_recognize_settings()
    answer = ask_model(
        instructions=INSTRUCTIONS.format(lang=_LANG_NAMES.get(lang, lang)),
        question=f"Current wording: {was or '(empty)'}\nInspector's new words: {said}",
        schema=SCHEMA,
        photo=None,
        settings=cfg,
        model=cfg.merge_model,
    )
    raw = answer.payload.get("text")
    if not isinstance(raw, str):
        raise ModelUnavailable("Сведение комментария: в ответе модели нет строки text")
    text = " ".join(raw.split())
    if not text:
        raise ModelUnavailable("Сведение комментария: модель вернула пустую строку")
    brought = set(check_wording(text, "")) - set(check_wording(f"{was} {said}", ""))
    if brought:
        raise ModelUnavailable(
            f"Сведение комментария: ответ модели принёс пометки {sorted(brought)}, "
            f"которых не было ни в записи, ни в словах аудитора: «{text}»"
        )
    return text
