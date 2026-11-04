"""Где источник данных рейтингов Додо не обслуживает — и потому его пустота не дыра (D704, D706).

Проверка покрытия (`src/health/coverage_check.py`) без этого списка шумела бы вечно: площадка
или карты по странам и пиццериям просто не работают, и ждать оттуда оценок бессмысленно.
Один список на всё: каждая запись — источник, страна, дата проверки и причина; без `units` запись
про всю страну (пара «страна × источник» не ждётся и не попадает в таблицу), с `units` — про
перечисленные пиццерии (они вычитаются из базы страны при подсчёте доли, остальные ждутся).

Почему не `agg.unit_absent`. Таблица есть, и для пиццерий агрегаторов она по смыслу подходит, но
это ручные отметки людей с экрана охвата, привязанные к `dodo_id`; сюда нужны пары «страна ×
источник» (таблица их не выражает) и список с датой и причиной в репозитории, который видно в
дифе. Два места для одного вопроса хуже одного; поэтому всё здесь, а отметки `agg.unit_absent`
проверка по-прежнему вычитает сама.

Не сюда: устаревшие или неполные данные при живых карточках (Яндекс Карты в Болгарии, Литве и
Нигерии — Pointer их не обновляет) — это дыра, и она должна оповещать.

Запись устаревает, если площадка пришла в страну: сверять при каждом обновлении охвата
(`docs/17-aggregators.md`, «Охват на 04.11.2026»).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .coverage_rules import SRC_YANDEX, agg_source

CHECKED = date(2026, 11, 4)


@dataclass(frozen=True)
class NotServed:
    source: str
    country: str
    checked_on: date
    reason: str
    #: Имена пиццерий реестра; пусто — вся страна.
    units: tuple[str, ...] = ()


NOT_SERVED: tuple[NotServed, ...] = (
    NotServed(
        agg_source("wolt"), "RS", CHECKED,
        "в Белграде и Нови-Саде Wolt есть, Додо на нём нет (поиск у координат всех пиццерий)",
    ),
    NotServed(
        agg_source("wolt"), "GE", CHECKED,
        "карточки Тбилиси привязаны, но площадка не отдаёт оценку (`rating: null`, D700)",
    ),
    NotServed(
        agg_source("bolt_food"), "GE", CHECKED,
        "Bolt в Тбилиси и Батуми работает, Додо на нём нет",
    ),
    NotServed(
        agg_source("yandex_eda"), "KG", CHECKED,
        "Яндекс Еда не обслуживает Бишкек и Балыкчи",
    ),
    NotServed(
        agg_source("bolt_food"), "BG", CHECKED,
        "в этих городах Bolt нет (код 5812)",
        units=("Pleven-1", "Stara Zagora-1"),
    ),
    NotServed(
        agg_source("yandex_eda"), "BY", CHECKED,
        "Яндекс Еда не обслуживает точку вовсе; Минск-6, Минск-15 и Гродно-3 обслуживает, "
        "они остаются дырой",
        units=(
            "Борисов-1", "Жлобин-1", "Жодино-1", "Лида-1", "Мозырь-1", "Молодечно-1",
            "Новополоцк-1", "Орша-1", "Пинск-1", "Полоцк-1", "Речица-1", "Солигорск-1",
        ),
    ),
    *(
        NotServed(
            SRC_YANDEX, country, CHECKED,
            "в Pointer нет карточки Яндекса у пиццерий страны, Яндекс Картами там не пользуются",
        )
        for country in ("EE", "ES", "ME", "PL", "RO", "SI", "NG", "HR")
    ),
)  # fmt: skip


def country_pairs() -> frozenset[tuple[str, str]]:
    """Пары (источник, страна), которые не обслуживаются целиком."""
    return frozenset((n.source, n.country) for n in NOT_SERVED if not n.units)


def unit_pairs() -> tuple[tuple[str, str], ...]:
    """Пары (источник, имя пиццерии), которые не обслуживаются поштучно."""
    return tuple((n.source, name) for n in NOT_SERVED for name in n.units)
