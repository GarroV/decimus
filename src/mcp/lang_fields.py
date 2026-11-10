"""Поля «<поле>_<язык>» инструментов правки методики: набор языков берётся из `REPORT_LANGS`.

База методики пишется на `BASE_LANG` (`process`/`question_ru`/`name_ru` — они в
сигнатуре и схеме инструмента названы явно), остальные языки отчёта идут
необязательными полями `process_en`, `question_en`, `name_en` и т. д. Третий язык
появляется в схеме и в обработчике сам — строкой в `REPORT_LANGS`, без правки
каждого инструмента.

Обработчик принимает такие поля как `**texts`, а сигнатуру для сверки со схемой
(`tests/test_mcp_catalogue.py`) показывает развёрнутой: `publishes_texts`.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from typing import Any

from ..domain.models import BASE_LANG, REPORT_LANGS
from .errors import ToolError

#: Название языка в описаниях инструментов (читает модель, поэтому по-английски).
#: Языка нет в словаре — его код: описание не пропадёт, просто будет суше.
LANG_TITLES = {"en": "English", "tr": "Turkish"}


def translated_langs() -> tuple[str, ...]:
    """Языки отчёта, кроме базового: у них поля необязательные."""
    return tuple(code for code in REPORT_LANGS if code != BASE_LANG)


def text_params(*fields: str) -> tuple[str, ...]:
    """Имена полей по языкам: `("process_en", "question_en")` для `("process", "question")`."""
    return tuple(f"{field}_{code}" for field in fields for code in translated_langs())


def text_properties(field: str, what: str, tail: str) -> dict[str, object]:
    """Свойства схемы инструмента для поля `field` на каждом не базовом языке.

    `tail` — вторая половина описания, `{title}` в ней — название языка:
    «Omit to leave the {title} text blank.».
    """
    out: dict[str, object] = {}
    for code in translated_langs():
        title = LANG_TITLES.get(code, code)
        out[f"{field}_{code}"] = {
            "type": "string",
            "description": f"{what} in {title}. {tail.format(title=title)}",
        }
    return out


def publishes_texts(*fields: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Показать `**texts` обработчика развёрнутыми именованными параметрами.

    Схема инструмента перечисляет `process_en`, `question_en` и так далее;
    сверка схемы с сигнатурой читает `inspect.signature`, а сам вызов идёт
    по-прежнему словарём — так список языков живёт в одном месте.
    """

    def decorate(handler: Callable[..., Any]) -> Callable[..., Any]:
        signature = inspect.signature(handler)
        kept = [p for p in signature.parameters.values() if p.kind is not p.VAR_KEYWORD]
        added = [
            inspect.Parameter(
                name, inspect.Parameter.KEYWORD_ONLY, default=None, annotation="str | None"
            )
            for name in text_params(*fields)
        ]
        handler.__dict__["__signature__"] = signature.replace(parameters=[*kept, *added])
        return handler

    return decorate


def cli_options(texts: Mapping[str, str | None], *fields: str) -> dict[str, str | None]:
    """Поля по языкам → опции команды движка (`question_en` → `question-en`).

    Поле, которого нет среди `text_params(*fields)`, — отказ: незнакомое имя
    молча ушло бы в движок и там либо упало, либо потерялось.
    """
    allowed = set(text_params(*fields))
    unknown = sorted(set(texts) - allowed)
    if unknown:
        raise ToolError(
            f"Неизвестные поля: {', '.join(unknown)}. Допустимы: {', '.join(sorted(allowed))}"
        )
    return {name.replace("_", "-"): value for name, value in texts.items()}
