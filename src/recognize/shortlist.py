"""T030: перечень кандидатов, который уходит в запрос к модели.

Порядок сборки один и тот же всегда:

1. **База — ВЕСЬ перечень нарушений, а не зональный** (T265, #218). Резать его
   нельзя ничем, включая зону: разведка показала, что при отсутствии правильного
   кода среди кандидатов модель не молчит, а уверенно предлагает похожий пункт с
   осмысленной формулировкой. Такая ошибка не выглядит как ошибка. До T265 базу
   резала зона — и пункт про печь исчезал из перечня, как только зона оказывалась
   холодным цехом, то есть ровно в том случае, ради которого перечень и собирают.
   Зона осталась **порядком**: её пункты стоят впереди остальных.
   С #1267 (D646) этот порядок живёт в `codes` и в тексте запроса отдельными
   строками («пункты зоны», «пункты, поднятые словами»), а перечень значений в
   запросе и в схеме идёт в `canonical` — постоянном порядке чек-листа: общий
   префикс запроса кэшируется провайдером, и перечень, переставленный под зону,
   кэш обнулял.
2. **Карта кадров — сверху.** Коды, поднятые словами комментария, идут первыми и
   добавляются, даже если в зоне такого пункта нет: слова аудитора важнее вида
   зоны, а окончательное решение всё равно за ним.
3. **Служебное отсекается.** `kind=aggregate` и `kind=info` не предлагаются
   (правило 8), `MGM22`/`MGM23` — ручное решение аудитора.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.domain import list_items

from .cues import load_cues, matched_cues

#: Пункты, которые ставит только человек: «другое критическое нарушение» и
#: «массовость нарушений D1». Модель их не предлагает — так велит последний
#: раздел `data/photo-cues.md`. В ручном перечне кнопок они остаются.
MANUAL_ONLY = ("MGM22", "MGM23")


@dataclass(frozen=True)
class Shortlist:
    """Кандидаты для запроса: коды в порядке показа модели."""

    codes: tuple[str, ...]
    cue_hits: tuple[str, ...]
    zone: str | None
    #: Те же подсказки по строкам карты, в порядке показа (D597): строка — это
    #: один объект («Туалет: интерьер» — грязь и поломка), и запас к вопросу
    #: модели берётся по одному пункту из строки, а не подряд по кодам.
    cue_rows: tuple[tuple[str, ...], ...] = ()
    #: Те же коды, что в `codes`, но в порядке чек-листа — одинаковом для любой зоны и
    #: любых слов (#1267): так перечень в запросе и схеме не мешает кэшу провайдера.
    canonical: tuple[str, ...] = ()
    #: Пункты названной зоны, в порядке чек-листа. Пусто, если зона не названа.
    zone_codes: tuple[str, ...] = ()

    def __len__(self) -> int:
        return len(self.codes)


def _offered(kind: str, code: str, *, with_manual: bool) -> bool:
    if kind != "violation":
        return False
    return with_manual or code not in MANUAL_ONLY


def shortlist(
    note: str,
    zone_hint: str | None = None,
    *,
    with_manual: bool = False,
    chat_id: int | None,
) -> Shortlist:
    """Собрать перечень кандидатов. Неизвестная зона — отказ от `domain`.

    `with_manual` включает пункты ручного решения аудитора: он нужен ручному
    выбору кнопками, где решает человек, и выключен для запроса к модели.

    `chat_id` обязателен и умолчания не имеет (T226): и пункты, и карта слов
    берутся из издания ТОЙ проверки (T169). Перечень, собранный по действующей
    методике, — худший из случаев разведки: снятый переизданием пункт из него
    исчезает, и модель уверенно предлагает соседний. Пустой чат
    (`config.NO_CHAT`) — законное «проверки нет», а не забытый параметр.
    """
    rows = matched_cues(note, load_cues(chat_id=chat_id))
    hits = tuple(dict.fromkeys(code for cue in rows for code in cue.codes))
    everything = list_items(chat_id=chat_id)
    offered = {i.code for i in everything if _offered(i.kind, i.code, with_manual=with_manual)}
    # Зона проверяется, даже когда перечень ею не режется: неизвестный код зоны
    # — опечатка вызывающего, и молчаливое «ну и ладно» пряталось бы до первого
    # разбора, который её касается. Отказ приходит из `domain`.
    in_zone = (
        set()
        if zone_hint is None
        else {i.code for i in list_items(zone=zone_hint, chat_id=chat_id)}
    )
    base = [i.code for i in everything if i.code in offered]
    canonical = tuple(base)
    zone_codes = tuple(code for code in canonical if code in in_zone)
    # Ранжирование, а не отсечка: пункты названной зоны идут первыми, пункты
    # остальных зон остаются в перечне и достижимы. Сортировка устойчива,
    # поэтому внутри каждой половины сохраняется порядок чек-листа.
    base.sort(key=lambda code: code not in in_zone)
    front = tuple(code for code in hits if code in offered)
    codes = list(front) + [code for code in base if code not in front]
    cue_rows = tuple(
        row for row in (tuple(c for c in cue.codes if c in offered) for cue in rows) if row
    )
    return Shortlist(
        codes=tuple(codes),
        cue_hits=front,
        zone=zone_hint,
        cue_rows=cue_rows,
        canonical=canonical,
        zone_codes=zone_codes,
    )
