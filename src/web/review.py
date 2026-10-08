"""Лист вычитки проверки на приёмке: весь чек-лист по пунктам (D199).

Вычитывающему мало записанных нарушений — он обязан видеть и то, что аудитор
счёл чистым. Поэтому лист собирается из ЧЕК-ЛИСТА той версии, по которой
проверку считали, а записи раскладываются по его пунктам. «Чисто» здесь — не
отдельная отметка аудитора (её в данных нет), а честное «по этому пункту в
этой зоне записи нет».

Арифметики у листа нет: оценка, вычеты и разбивка приходят из базы такими,
какими их посчитал движок. Лист только раскладывает.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from src.db.models import FindingRow, InspectionRow
from src.domain.models import NON_DEDUCTING

from . import methodology as method
from .errors import MethodologyRefused

logger = logging.getLogger(__name__)

#: Пункт чек-листа, нарушение которого пишется записью. Остальные виды —
#: вопросы информационной части, у них свой раздел карточки.
VIOLATION = "violation"

#: «Во всех зонах» в колонке `zones` чек-листа — так же, как читает движок.
ALL_ZONES = "*"


@dataclass(frozen=True)
class SheetItem:
    """Пункт чек-листа в одной зоне и записи по нему."""

    code: str
    question: str
    findings: tuple[FindingRow, ...]

    @property
    def clean(self) -> bool:
        # Замер и рекомендация нарушением пункт не делают (#444, D201).
        return not any(f.level not in NON_DEDUCTING for f in self.findings)


@dataclass(frozen=True)
class SheetZone:
    code: str
    name: str
    items: tuple[SheetItem, ...]

    @property
    def violations(self) -> int:
        return sum(1 for item in self.items for f in item.findings if f.level not in NON_DEDUCTING)


@dataclass(frozen=True)
class Sheet:
    zones: tuple[SheetZone, ...]
    #: Записи, которым в чек-листе версии не нашлось пары «пункт + зона»:
    #: пункт снят или записан в чужую для него зону. Их не прячут — вычитывающий
    #: должен увидеть их первыми.
    unplaced: tuple[FindingRow, ...]
    #: Пункты нарушений версии `(код, вопрос)` — выбор пункта в форме правки
    #: записи (D200). Тот же порядок, что в таблице чек-листа.
    catalogue: tuple[tuple[str, str], ...] = ()


def _zones_of(item: Mapping[str, str], all_zones: Iterable[str]) -> tuple[str, ...]:
    записанные = tuple(z.strip() for z in (item.get("zones") or "").split(",") if z.strip())
    if not записанные or записанные == (ALL_ZONES,):
        return tuple(all_zones)
    return записанные


def build_sheet(
    *,
    items: Iterable[Mapping[str, str]],
    zones: Iterable[Mapping[str, str]],
    findings: Iterable[FindingRow],
    lang: str,
) -> Sheet:
    """Разложить записи проверки по пунктам чек-листа, зона за зоной.

    Порядок зон — как в чек-листе версии, порядок пунктов — как в его таблице.
    Язык — интерфейса вычитывающего; формулировки записей остаются на языке
    речи проверки, как их и записали.
    """
    зоны = tuple(zones)
    коды_зон = tuple(str(z.get("code", "")) for z in зоны)
    записи = tuple(findings)
    размещённые: set[str] = set()
    по_зонам: dict[str, list[SheetItem]] = {код: [] for код in коды_зон}
    перечень: list[tuple[str, str]] = []
    for item in items:
        if (item.get("kind") or VIOLATION).strip() != VIOLATION:
            continue
        код = str(item.get("id", ""))
        вопрос = str(item.get(f"question_{lang}") or item.get("question_ru") or код)
        перечень.append((код, вопрос))
        for зона in _zones_of(item, коды_зон):
            if зона not in по_зонам:
                continue
            свои = tuple(f for f in записи if f.code == код and f.zone == зона)
            размещённые.update(f.id for f in свои)
            по_зонам[зона].append(SheetItem(code=код, question=вопрос, findings=свои))
    return Sheet(
        zones=tuple(
            SheetZone(
                code=код,
                name=str(z.get(f"name_{lang}") or z.get("name_ru") or код),
                items=tuple(по_зонам[код]),
            )
            for код, z in zip(коды_зон, зоны, strict=True)
        ),
        unplaced=tuple(f for f in записи if f.id not in размещённые),
        catalogue=tuple(перечень),
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
    )
    return method.load_composition(store, tenant=head.tenant_code, version=head.checklist_version)


def load_sheet(head: InspectionRow, findings: Iterable[FindingRow], *, lang: str) -> Sheet | None:
    """Лист вычитки по чек-листу проверки. `None` — чек-лист прочитать не удалось.

    Без листа карточка остаётся карточкой: записи показаны списком, как
    раньше, а причина уходит в лог. Выдумывать «всё чисто» при недоступном
    чек-листе нельзя — это выглядело бы как вычитанная проверка.
    """
    try:
        состав = checklist_of(head, lang=lang)
    except MethodologyRefused as exc:
        logger.warning(
            "лист вычитки: чек-лист %s версии %s не прочитан: %s",
            head.checklist_code,
            head.checklist_version,
            exc,
        )
        return None
    return build_sheet(items=состав.items, zones=состав.zones, findings=findings, lang=lang)
