"""Чек-лист той версии, по которой считали проверку, — для правки записей на вычитке (D535).

Вычитывающий правит запись на месте и добавляет нарушение: пункт он выбирает из
пунктов нарушений ЭТОЙ версии, а класс и зону сужает по тому, что версия даёт
пункту. Блок «Весь чек-лист» (D199) с карточки снят (D535): он повторял записи,
а все записи — и те, что в версии без пары «пункт + зона», — показаны списком.

Арифметики здесь нет: оценка, вычеты и разбивка приходят из базы такими, какими
их посчитал движок. Допустимость пункта, класса и зоны решает сервер при
сохранении (`revision._checked_entry`); здесь — только то, что показать в выборе.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from src.db.models import InspectionRow

from . import methodology as method
from .errors import MethodologyRefused

logger = logging.getLogger(__name__)

#: Пункт чек-листа, нарушение которого пишется записью. Остальные виды —
#: вопросы информационной части, у них свой раздел карточки.
VIOLATION = "violation"

#: «Во всех зонах» в колонке `zones` чек-листа — так же, как читает движок.
ALL_ZONES = "*"


@dataclass(frozen=True)
class SheetZone:
    code: str
    name: str


@dataclass(frozen=True)
class Pick:
    """Пункт нарушения версии для выбора в правке записи (D535).

    Классы и зоны — те, что чек-лист версии даёт пункту: форма сужает по ним
    выбор, а допустимость всё равно решает сверка на сервере (`revision`).
    """

    code: str
    question: str
    levels: tuple[str, ...]
    zones: tuple[str, ...]


@dataclass(frozen=True)
class Sheet:
    #: Зоны версии в её порядке — выбор зоны записи.
    zones: tuple[SheetZone, ...]
    #: Пункты нарушений версии в порядке её таблицы — выбор пункта.
    picks: tuple[Pick, ...]


def _zones_of(item: Mapping[str, str], all_zones: Iterable[str]) -> tuple[str, ...]:
    записанные = tuple(z.strip() for z in (item.get("zones") or "").split(",") if z.strip())
    if not записанные or записанные == (ALL_ZONES,):
        return tuple(all_zones)
    return записанные


def build_sheet(
    *,
    items: Iterable[Mapping[str, str]],
    zones: Iterable[Mapping[str, str]],
    lang: str,
) -> Sheet:
    """Пункты нарушений и зоны версии для выбора. Порядок — как в чек-листе версии.

    Язык — интерфейса вычитывающего; формулировки записей остаются на языке
    речи проверки, как их и записали.
    """
    зоны = tuple(zones)
    коды_зон = tuple(str(z.get("code", "")) for z in зоны)
    выбор: list[Pick] = []
    for item in items:
        if (item.get("kind") or VIOLATION).strip() != VIOLATION:
            continue
        код = str(item.get("id", ""))
        классы = tuple(
            x.strip().upper()
            for x in (item.get("levels") or "").replace(";", ",").split(",")
            if x.strip()
        )
        выбор.append(
            Pick(
                code=код,
                question=str(item.get(f"question_{lang}") or item.get("question_ru") or код),
                levels=классы,
                zones=_zones_of(item, коды_зон),
            )
        )
    return Sheet(
        zones=tuple(
            SheetZone(code=код, name=str(z.get(f"name_{lang}") or z.get("name_ru") or код))
            for код, z in zip(коды_зон, зоны, strict=True)
        ),
        picks=tuple(выбор),
    )


def checklist_of(head: InspectionRow, *, lang: str) -> method.Composition:
    """Состав чек-листа той версии, по которой проверку считали.

    Чек-лист ищется так, как его нашёл бот того пространства, ЧЬЯ проверка
    (`head.tenant_code`, без названного пространства): у партнёра — свой или
    эталонный (D285). Вошедший читает его только на чтение, правка чек-листа
    отсюда не идёт; читать проверку он уже вправе — иначе карточки бы не было.

    Отказ — `MethodologyRefused`, в том числе когда хранилище методики не
    задано: «чек-листа нет» и «не прочитали» снаружи различать незачем, а
    чинить — да, и поимённо названная переменная уходит в текст отказа. Этот
    текст — для журнала сервера: на экран его не выводят (`load_sheet`,
    `revision.revise_card`).
    """
    state = method.load_store()
    if state.store is None:
        raise MethodologyRefused(f"хранилище методики не задано: {', '.join(state.missing)}")
    store = method.store_for(
        state.store,
        head.checklist_code,
        tenant=head.tenant_code,
        space=None,
        write=False,
        lang=lang,
        role=None,
    )
    return method.load_composition(store, tenant=head.tenant_code, version=head.checklist_version)


def load_sheet(head: InspectionRow, *, lang: str) -> Sheet | None:
    """Выбор пунктов и зон по чек-листу проверки. `None` — чек-лист прочитать не удалось.

    Без него карточка остаётся карточкой: записи показаны списком, но править
    их и добавлять нарушения не из чего — причина уходит в лог.
    """
    try:
        состав = checklist_of(head, lang=lang)
    except MethodologyRefused as exc:
        logger.warning(
            "вычитка: чек-лист %s версии %s не прочитан: %s",
            head.checklist_code,
            head.checklist_version,
            exc,
        )
        return None
    return build_sheet(items=состав.items, zones=состав.zones, lang=lang)
