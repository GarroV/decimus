"""Мини-апп обхода: зона записи после того, как пункт найден (D435).

Нарушение не зависит от зоны на экране: аудитор снимает кадр и говорит пару
слов, пункт ищет система, а зона — свойство найденного пункта и сказанного, а
не того, какая вкладка открыта. Зона на экране — лишь мягкая подсказка.

Ядро: ошибка здесь молчалива (запись встанет в правдоподобную, но не ту зону и
уйдёт в отчёт как факт), поэтому правило — одна чистая функция, а не условия
в обработчике и не копия на клиенте. Порядок источников:

1. зона названа словами аудитора (разбор слов — тот же, что у бота,
   `bot.zones.zone_from_words`) — она, даже вне списка пункта: зону, названную
   человеком, движок принимает с пометкой «зона нетипична» (D206, как в боте);
2. пункт бывает в одной зоне — она;
3. зона, которую вернула модель, если она есть в списке пункта;
4. зона с экрана, если она есть в списке пункта;
5. иначе — спросить пилюлями из зон пункта (`ask`).

Зону вне списка пункта даёт только человек — словами или пилюлей в форме;
машинные источники (модель, экран) ограничены списком пункта.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ZoneSource = Literal["single", "words", "model", "hint", "ask"]
SOURCES: tuple[ZoneSource, ...] = ("single", "words", "model", "hint", "ask")


@dataclass(frozen=True)
class ItemZone:
    """Зона записи для найденного пункта и чем она выведена."""

    #: Зона, если вывелась. `None` — её предстоит спросить у аудитора.
    zone: str | None
    source: ZoneSource
    #: Зоны, которые методика даёт пункту, в порядке методики: ими же спрашиваем.
    options: tuple[str, ...]


def resolve_item_zone(
    options: tuple[str, ...],
    *,
    spoken: str | None,
    model: str | None,
    hint: str | None,
) -> ItemZone:
    """Зона записи по порядку источников (см. модуль)."""
    if spoken:
        return ItemZone(spoken, "words", options)
    if len(options) == 1:
        return ItemZone(options[0], "single", options)
    for zone, source in ((model, "model"), (hint, "hint")):
        if zone and zone in options:
            return ItemZone(zone, source, options)  # type: ignore[arg-type]
    return ItemZone(None, "ask", options)
