"""Мгновенная подсказка: 2–3 пункта по карте слов, без модели (#1267, D646 п. 3).

Пока модель думает 6–10 с, аудитор видит предварительные карточки и может
нажать одну сразу. Подсказка ничего не решает и ничего не пишет: она ставит
вперёд то, что карта слов (`data/photo-cues.md`) уже называет, и снимается,
когда приходит ответ модели.

**Нового словаря нет.** Совпадение строк — `cues.matched_cues`, тот же, что
собирает перечень для модели; выбор «грязь или поломка» — слова колонок быстрого
пути (`fastpath.column_resolver`). Здесь только порядок и отбор.

**Чем подсказка строже перечня для модели.** Перечню хватает «задели»: лишний
код стоит копейки. Подсказку человек видит и может нажать, поэтому:

* служебное не показывается (правило 8): `kind != violation`, `MANUAL_ONLY`;
* **название зоны из слов вычитается** до сопоставления: «грязный пол в горячем
  цехе» — это пол, а строку про термометр с названием цеха названное место
  поднимало первой (замер на боевой карте);
* пункты зоны, названной в словах или на экране, идут первыми;
* совпадения нет — пусто, и экран ждёт модель как раньше.

Выученные фразы сюда не заходят: карта синонимов живёт в базе, а `recognize` и
`db` — пиры (`pyproject.toml`). Их подмешивает `bot.propose.hint`.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.domain import allowed_levels, list_items
from src.domain.errors import DomainError

from .cues import load_cues, matched_cues, stems, words_and_gaps
from .fastpath import column_resolver
from .shortlist import MANUAL_ONLY
from .zone_words import phrases, zone_from_words

#: Сколько карточек показывает подсказка. Больше трёх — это уже список, а не
#: «похоже на…», и читать его дольше, чем ждать модель.
HINT_MAX = 3


@dataclass(frozen=True)
class HintItem:
    """Пункт подсказки. Класс — только если методика даёт один, иначе пусто."""

    code: str
    level: str
    #: Строка карты, которая подняла пункт: по ней видно, откуда подсказка.
    cue: str


def _without_zone_name(note: str, zone: str | None, *, chat_id: int | None) -> str:
    """Слова без названия зоны, которую они сами и называют.

    Вычитаются только имена, произнесённые целиком (`name <= words`): так зону
    находит и `zone_from_words`. Слово, которое только похоже на часть имени,
    остаётся — оно может быть и словом о пункте.
    """
    if zone is None:
        return note
    spoken = stems(note)
    named = phrases(chat_id=chat_id).get(zone, ())
    covered = frozenset().union(*(name for name in named if name <= spoken))
    if not covered:
        return note
    words, _ = words_and_gaps(note)
    kept = [word for word in words if not (stems(word) and stems(word) <= covered)]
    return " ".join(kept)


def _level(code: str, *, chat_id: int | None) -> str:
    try:
        levels = allowed_levels(code, chat_id=chat_id)
    except DomainError:
        return ""
    return levels[0] if len(levels) == 1 else ""


def rank(
    note: str,
    zone_hint: str | None,
    *,
    chat_id: int | None,
    limit: int = HINT_MAX,
) -> tuple[HintItem, ...]:
    """Вероятные пункты по словам, лучший первым. Совпадения нет — пусто.

    `zone_hint` — зона на экране (подсказка, не ответ); зона, названная в
    словах, сильнее (D445). Служебные пункты и коды, которых нет в издании
    проверки, не показываются.
    """
    words = note.strip()
    if not words:
        return ()
    spoken_zone = zone_from_words(words, chat_id=chat_id)
    zone = spoken_zone or zone_hint
    rows = matched_cues(
        _without_zone_name(words, spoken_zone, chat_id=chat_id), load_cues(chat_id=chat_id)
    )
    if not rows:
        return ()
    items = {i.code: i for i in list_items(chat_id=chat_id)}
    resolve = column_resolver(words, chat_id=chat_id)
    found: dict[str, str] = {}
    for row in rows:
        for code in resolve(row) or row.codes:
            item = items.get(code)
            if item is None or item.kind != "violation" or code in MANUAL_ONLY:
                continue
            found.setdefault(code, row.phrase)
    # Устойчивая сортировка: внутри каждой половины порядок строк карты цел.
    codes = sorted(found, key=lambda code: zone is not None and not items[code].applies_to(zone))
    return tuple(
        HintItem(code=code, level=_level(code, chat_id=chat_id), cue=found[code])
        for code in codes[:limit]
    )
