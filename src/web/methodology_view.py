"""Экран чек-листа в три колонки (D197): отбор, группировка и соседи пункта.

Здесь нет ни одного правила методики — только то, как её состав показать:
какие пункты попали под отбор, как их сложить в группы и какой пункт стоит
до и после выбранного (для листания стрелками). Состав приходит из хранилища
версий (`methodology.load_composition`) как лежит в файлах; коды классов и зон
берутся из самого состава, а не из списка экрана — свой список однажды
разошёлся бы с тем, что примет движок.

Формат ячеек тот же, что читает движок (`engine/audit.py`): классы через `;`
или `,`, зоны через `,`, `*` или пусто — все зоны.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

#: Как сложить пункты. Первое — умолчание: так пункты стоят и в файле методики.
GROUPINGS = ("process", "zone", "level")

#: Все зоны — так их пишет методика.
ALL_ZONES = "*"

#: Пункт выключен (`disable_item`) — вид строки `off`.
KIND_OFF = "off"

_SPLIT = re.compile(r"[;,]")

Item = Mapping[str, str]


@dataclass(frozen=True)
class ItemFilter:
    """Что человек сузил в списке. Пустое поле — «не сужать»."""

    q: str = ""
    level: str = ""
    zone: str = ""
    #: Показывать выключенные пункты. По умолчанию их нет: они не участвуют в
    #: проверке, и в рабочем списке это шум.
    off: bool = False
    group: str = GROUPINGS[0]

    @property
    def narrowed(self) -> bool:
        """Сужен ли список чем-то, кроме группировки."""
        return bool(self.q or self.level or self.zone)


@dataclass(frozen=True)
class Group:
    """Группа списка: подпись и пункты в порядке файла."""

    key: str
    items: tuple[Item, ...]


def parse_filter(args: Mapping[str, str]) -> ItemFilter:
    """Отбор из адреса. Незнакомая группировка — умолчание, а не отказ."""
    group = (args.get("group") or "").strip()
    return ItemFilter(
        q=(args.get("q") or "").strip()[:80],
        level=(args.get("level") or "").strip().upper()[:8],
        zone=(args.get("zone") or "").strip()[:40],
        off=(args.get("off") or "") == "1",
        group=group if group in GROUPINGS else GROUPINGS[0],
    )


def levels_of(item: Item) -> tuple[str, ...]:
    """Допустимые классы пункта: `D1;D3` → `("D1", "D3")`."""
    return tuple(x.strip().upper() for x in _SPLIT.split(item.get("levels") or "") if x.strip())


def zones_of(item: Item) -> tuple[str, ...]:
    """Зоны пункта; «все зоны» — `("*",)`, как и пустая ячейка."""
    zones = tuple(x.strip() for x in (item.get("zones") or "").split(",") if x.strip())
    return zones or (ALL_ZONES,)


def is_off(item: Item) -> bool:
    return (item.get("kind") or "") == KIND_OFF


def _matches(item: Item, needle: str) -> bool:
    поля = ("id", "question_ru", "question_en", "process_ru", "process_en")
    return any(needle in (item.get(поле) or "").casefold() for поле in поля)


def select(items: Sequence[Item], f: ItemFilter) -> tuple[Item, ...]:
    """Пункты под отбором, в порядке файла."""
    needle = f.q.casefold()
    return tuple(
        item
        for item in items
        if (f.off or not is_off(item))
        and (not needle or _matches(item, needle))
        and (not f.level or f.level in levels_of(item))
        # Пункт «все зоны» проверяется и в выбранной зоне — прятать его при
        # отборе по зоне значило бы показать зону беднее, чем её проверяют.
        and (not f.zone or f.zone in zones_of(item) or ALL_ZONES in zones_of(item))
    )


def _keys(item: Item, by: str) -> tuple[str, ...]:
    if by == "zone":
        return zones_of(item)
    if by == "level":
        return levels_of(item) or ("",)
    return (item.get("process_ru") or item.get("process_en") or "",)


def group(items: Sequence[Item], by: str) -> tuple[Group, ...]:
    """Сложить пункты в группы в порядке первого появления.

    Пункт нескольких зон (или классов) стоит в каждой своей группе: вопрос
    «что проверяется в этой зоне» честнее отвечен полным списком, чем списком,
    где пункт отдан первой попавшейся зоне.
    """
    порядок: list[str] = []
    по_ключу: dict[str, list[Item]] = {}
    for item in items:
        for key in _keys(item, by):
            if key not in по_ключу:
                порядок.append(key)
                по_ключу[key] = []
            по_ключу[key].append(item)
    return tuple(Group(key=key, items=tuple(по_ключу[key])) for key in порядок)


def neighbours(items: Sequence[Item], code: str) -> tuple[str | None, str | None]:
    """Коды пунктов до и после выбранного — в том порядке, что видит человек."""
    коды = [item.get("id") or "" for item in items]
    if code not in коды:
        return None, None
    i = коды.index(code)
    return (коды[i - 1] if i > 0 else None), (коды[i + 1] if i + 1 < len(коды) else None)


def level_options(items: Sequence[Item]) -> tuple[tuple[str, int], ...]:
    """Классы, которые встречаются в составе, с числом пунктов — для чипа и плашек."""
    счёт: dict[str, int] = {}
    for item in items:
        for level in levels_of(item):
            счёт[level] = счёт.get(level, 0) + 1
    return tuple(sorted(счёт.items()))


def zone_options(
    items: Sequence[Item], zones: Sequence[Mapping[str, str]]
) -> tuple[tuple[str, int], ...]:
    """Зоны методики в её порядке, с числом пунктов, которые в зоне проверяются."""
    return tuple(
        (code, sum(1 for item in items if code in zones_of(item) or ALL_ZONES in zones_of(item)))
        for code in (z.get("code") or "" for z in zones)
        if code
    )


# --- разница версий: что изменится при публикации ---------------------------------

#: Поля пункта, которые сравниваются и называются человеку. Прочие колонки
#: (заведённые управляющей компанией, T109) сравниваются тоже — своим именем.
_FIELD_ORDER = (
    "question_ru",
    "question_en",
    "process_ru",
    "process_en",
    "levels",
    "zones",
    "days",
    "criteria",
)


@dataclass(frozen=True)
class Change:
    """Одно отличие между версиями.

    `kind`: `added`, `removed`, `disabled`, `restored`, `changed` — у пункта;
    `zone` — у зоны. `fields` — `(поле, было, стало)`.
    """

    code: str
    kind: str
    fields: tuple[tuple[str, str, str], ...] = ()


def _fields(old: Item, new: Item) -> tuple[tuple[str, str, str], ...]:
    имена = [f for f in _FIELD_ORDER if f in old or f in new]
    имена += sorted((set(old) | set(new)) - set(_FIELD_ORDER) - {"id", "kind"})
    return tuple(
        (f, old.get(f) or "", new.get(f) or "")
        for f in имена
        if (old.get(f) or "").strip() != (new.get(f) or "").strip()
    )


def diff_items(old: Sequence[Item], new: Sequence[Item]) -> tuple[Change, ...]:
    """Отличия пунктов, в порядке новой версии; удалённые — в конце."""
    было = {i.get("id") or "": i for i in old}
    стало = {i.get("id") or "": i for i in new}
    изменения: list[Change] = []
    for code, item in стало.items():
        прежний = было.get(code)
        if прежний is None:
            изменения.append(Change(code=code, kind="added"))
            continue
        if is_off(item) != is_off(прежний):
            изменения.append(Change(code=code, kind="disabled" if is_off(item) else "restored"))
        поля = _fields(прежний, item)
        if поля:
            изменения.append(Change(code=code, kind="changed", fields=поля))
    изменения += [Change(code=c, kind="removed") for c in было if c not in стало]
    return tuple(изменения)


def diff_zones(
    old: Sequence[Mapping[str, str]], new: Sequence[Mapping[str, str]]
) -> tuple[Change, ...]:
    """Отличия зон: доля, названия; зона появилась или пропала."""
    было = {z.get("code") or "": z for z in old}
    стало = {z.get("code") or "": z for z in new}
    изменения = [
        Change(code=c, kind="zone", fields=_fields(было.get(c, {}), z))
        for c, z in стало.items()
        if _fields(было.get(c, {}), z)
    ]
    пропавшие = [c for c in было if c not in стало]
    изменения += [Change(code=c, kind="zone", fields=_fields(было[c], {})) for c in пропавшие]
    return tuple(изменения)
