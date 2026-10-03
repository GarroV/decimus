"""Правка записи ответом словами (#454, решения D294, D295).

Аудитор отвечает на сообщение бота о записи: «не ранч, а терияки». Раньше эти
слова уходили в разбор с нуля — модель не видела исходной записи и заводила
новую формулировку, а то и другой пункт. D294: бот знает, на какую запись
ответили, и правит её — меняет названное, остальное оставляет.

Решает дешёвая текстовая модель (`RecognizeSettings.merge_model`, та же, что
сводит комментарий в `merge.py`). Она получает запись целиком — пункт кодом и
вопросом, класс, зону, формулировку — и слова аудитора, и отвечает одним из
двух:

- `wording` — слова правят ФОРМУЛИРОВКУ той же находки (другой объект, деталь,
  уточнение). Модель возвращает новую фразу-факт; пункт, класс и зона не
  меняются — их в ответе нет вовсе.
- `other` — слова говорят о другом нарушении, другом пункте или другой зоне.
  Текста нет: такую правку разбирает прежний путь, заново (D295).

Правила фиксации в силе полностью, и второй слой тот же, что у сведения
комментария: сторож формулировок (`rules_check`). Ответ, который приносит
пометку, которой не было ни в прежнем тексте, ни в словах аудитора,
отвергается целиком.

Любой отказ — сеть, ключ, пустой, кривой или подозрительный ответ — это
`ModelUnavailable`. Вызывающий обязан пережить его, не меняя записи и не
уводя слова в разбор заново: иначе вместо правки молча завелась бы другая
запись (D295).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .client import ask_model
from .config import RecognizeSettings, load_recognize_settings
from .errors import ModelUnavailable
from .rules_check import check_wording

Kind = Literal["wording", "other"]

#: Схема ответа. `text` обязателен и при `other` — строгая схема провайдера не
#: знает необязательных полей; там он пустой и не читается.
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["wording", "other"]},
        "text": {"type": "string"},
    },
    "required": ["kind", "text"],
    "additionalProperties": False,
}

#: Имя языка в инструкции. Незнакомый код передаётся как есть — модель его
#: поймёт, а язык остаётся параметром, а не константой.
_LANG_NAMES = {"ru": "Russian", "en": "English"}

INSTRUCTIONS = (
    "You maintain one finding in a restaurant inspection report. The inspector "
    "replied to this finding with words. Decide what the words do.\n"
    "- kind 'wording': the words correct or refine the WORDING of this same "
    "finding — a different object or detail, a clarification, another object of "
    "the same kind added. The checklist item, class and zone stay as they are. "
    "Return in 'text' the corrected wording: ONE sentence that states the fact.\n"
    "- kind 'other': the words say it is a different violation, a different "
    "checklist item, a different class or a different zone. Return 'text' empty.\n"
    "Rules for the wording:\n"
    "- Keep what the current wording says and change only what the inspector "
    "named. Name only objects and details present in the current wording or in "
    "the inspector's words. Invent nothing.\n"
    "- Never add scale that was not said: no 'in several places', 'everywhere', "
    "'throughout', 'over several metres', counts or durations of your own.\n"
    "- Do not guess the nature of damage (corrosion, cracks, mould) unless it was said.\n"
    "- Output the finding itself: no questions, no remarks to the inspector, no "
    "'suggested wording', no quotes around it.\n"
    "- Write the wording in {lang}."
)


@dataclass(frozen=True)
class Revision:
    """Что слова аудитора делают с записью. `text` пуст при `other`."""

    kind: Kind
    text: str


def _question(
    *, item_code: str, item_text: str, level: str, zone: str, wording: str, words: str
) -> str:
    return (
        f"Checklist item: {item_code} — {item_text}\n"
        f"Class: {level}\n"
        f"Zone: {zone}\n"
        f"Current wording: {wording or '(empty)'}\n"
        f"Inspector's words: {words}"
    )


def revise_finding(
    *,
    item_code: str,
    item_text: str,
    level: str,
    zone: str,
    wording: str,
    words: str,
    lang: str,
    settings: RecognizeSettings | None = None,
) -> Revision:
    """Правка текста той же записи или «другое нарушение» — по записи и словам.

    `lang` — язык отчёта проверки: новая формулировка уходит в отчёт. Пустые
    слова — ошибка вызывающего (`ValueError`): модель без материала не зовётся.
    """
    was = wording.strip()
    said = words.strip()
    if not said:
        raise ValueError("Правка записи: слов аудитора нет")
    cfg = settings or load_recognize_settings()
    answer = ask_model(
        instructions=INSTRUCTIONS.format(lang=_LANG_NAMES.get(lang, lang)),
        question=_question(
            item_code=item_code,
            item_text=item_text,
            level=level,
            zone=zone,
            wording=was,
            words=said,
        ),
        schema=SCHEMA,
        photo=None,
        settings=cfg,
        model=cfg.merge_model,
    )
    kind = answer.payload.get("kind")
    if kind == "other":
        return Revision(kind="other", text="")
    if kind != "wording":
        raise ModelUnavailable(f"Правка записи: модель вернула неизвестный вид ответа {kind!r}")
    raw = answer.payload.get("text")
    if not isinstance(raw, str):
        raise ModelUnavailable("Правка записи: в ответе модели нет строки text")
    text = " ".join(raw.split())
    if not text:
        raise ModelUnavailable("Правка записи: модель вернула пустую формулировку")
    brought = set(check_wording(text, "")) - set(check_wording(f"{was} {said}", ""))
    if brought:
        raise ModelUnavailable(
            f"Правка записи: ответ модели принёс пометки {sorted(brought)}, "
            f"которых не было ни в записи, ни в словах аудитора: «{text}»"
        )
    return Revision(kind="wording", text=text)
