"""Пункт чек-листа для человека: «Порядок 13», а не `CLN13` (решение владельца 20.10.2026).

Код пункта — связь между данными (D###: сущности связываются кодами, формулировки
переводятся и правятся). Человеку он ничего не говорит, поэтому на экран, в бота,
в отчёт и в письмо уходит метка: название процесса (раздела) чек-листа на языке
экрана плюс номер пункта внутри кода без ведущих нулей — `CLN13` → «Порядок 13»,
`MGM08` → «Documents 8». Где есть место, метка идёт с формулировкой пункта
(`full`): «Порядок 13 — мебель загрязнена».

Название процесса и формулировка берутся из строк чек-листа ТОЙ версии, по которой
идёт проверка: их правит управляющая компания, и подпись под прошлогодней записью
по сегодняшнему тексту — другой пункт. Откуда взять строки — забота вызывающего
(`from_items` для прочитанных пунктов, `from_csv` для сырых строк файла); здесь —
только правило показа, одно на все поверхности.

Откат при пустом тексте на нужном языке — на другой язык методики, а не на код:
непереведённое название читается, код — нет. Код остаётся лишь там, где ни одного
текста нет вовсе (пункта нет в методике этой версии): так сбой виден, а не
подменён выдуманным словом.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from .models import LangTexts, fallback_chain, lang_texts

#: Служебные коды без номера: их показывают человеческим названием, не кодом.
#: `NOTE` — общая заметка (в оценке не участвует), `LEGACY` — запись исторической
#: проверки, у которой пункта в старом отчёте не было (D332). Слова те же, что
#: уже стоят в карточке проверки (`card.findings.note`, `card.findings.no_item`).
SPECIAL_TITLES: dict[str, dict[str, str]] = {
    "NOTE": {"ru": "Общая заметка", "en": "General note", "tr": "Genel not"},
    "LEGACY": {"ru": "Пункт не назван", "en": "Item not given", "tr": "Madde belirtilmedi"},
}

_TRAILING_NUMBER = re.compile(r"(\d+)$")


@dataclass(frozen=True)
class ItemTexts:
    """Тексты одного пункта чек-листа — всё, что нужно метке."""

    process_texts: LangTexts = field(default_factory=LangTexts)
    question_texts: LangTexts = field(default_factory=LangTexts)


#: Код пункта (верхним регистром) → его тексты.
Texts = Mapping[str, ItemTexts]


def _key(code: str) -> str:
    return code.strip().upper()


def from_items(items: Iterable[object]) -> dict[str, ItemTexts]:
    """Тексты по кодам из прочитанных пунктов (`domain.list_items`). Первое вхождение кода."""
    out: dict[str, ItemTexts] = {}
    for item in items:
        code = _key(str(getattr(item, "code", "")))
        if not code or code.startswith("#"):
            continue
        out.setdefault(
            code,
            ItemTexts(
                process_texts=LangTexts(getattr(item, "process_texts", {})),
                question_texts=LangTexts(getattr(item, "question_texts", {})),
            ),
        )
    return out


def from_csv(rows: Iterable[Mapping[str, str | None]]) -> dict[str, ItemTexts]:
    """Тексты по кодам из сырых строк `checklist.csv` (колонки `id`, `process_*`, `question_*`)."""
    out: dict[str, ItemTexts] = {}
    for row in rows:
        code = _key(row.get("id") or "")
        if not code or code.startswith("#"):
            continue
        out.setdefault(
            code,
            ItemTexts(
                process_texts=lang_texts(row, "process"),
                question_texts=lang_texts(row, "question"),
            ),
        )
    return out


def _pick(own: ItemTexts, field: str, lang: str) -> str:
    """Текст на языке; пусто — на другом языке методики, а не пустота и не код."""
    texts: LangTexts = getattr(own, f"{field}_texts")
    return next((texts[code] for code in fallback_chain(lang) if texts.get(code)), "")


def number(code: str) -> str | None:
    """Номер пункта в коде без ведущих нулей: `CLN13` → «13», `MGM08` → «8»; цифр нет — None."""
    found = _TRAILING_NUMBER.search(code.strip())
    return None if found is None else str(int(found.group(1)))


def label(code: str, texts: Texts | None, lang: str) -> str:
    """Короткая метка пункта: «Порядок 13».

    Служебный код без номера — его название. Пункта нет в переданных текстах или у
    него нет названия процесса ни на одном языке — сам код: это честный признак
    того, что методику этой версии не удалось прочитать.
    """
    key = _key(code)
    if not key:
        return ""
    special = SPECIAL_TITLES.get(key)
    if special is not None:
        return special.get(lang) or special["en"]
    n = number(key)
    own = None if texts is None else texts.get(key)
    if n is None or own is None:
        return code.strip()
    process = _pick(own, "process", lang)
    return f"{process} {n}" if process else code.strip()


def full(code: str, texts: Texts | None, lang: str) -> str:
    """Метка с формулировкой: «Порядок 13 — мебель загрязнена». Формулировки нет — одна метка."""
    short = label(code, texts, lang)
    own = None if texts is None else texts.get(_key(code))
    if own is None or _key(code) in SPECIAL_TITLES:
        return short
    wording = _pick(own, "question", lang)
    return f"{short} — {wording}" if wording else short


def wording(code: str, texts: Texts | None, lang: str) -> str:
    """Формулировка пункта на языке (откат — на другой язык методики); нет — пустая строка."""
    own = None if texts is None else texts.get(_key(code))
    return "" if own is None else _pick(own, "question", lang)
