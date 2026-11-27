"""Оснастка заслона «методика УК партнёру — только чтение» (D285, D761 п.4).

Хранилище из трёх чек-листов, собранное ОДИН раз на прогон и копируемое в каждый
тест (правка гоняет движок подпроцессом, сборка стоит секунды):

* `hq/bizdev` — эталон УК, применён к проду, с неопубликованной версией
  (CLN02 выключен) — чтобы у публикации и возврата пункта было что делать;
* `hq/spare` — второй чек-лист УК, черновик: на нём меняются состояние и метка;
* `am/rnd` — чек-лист партнёра AM с теми же кодами зон и пунктов, что у эталона:
  один и тот же запрос годен и для эталона, и для партнёрского чек-листа.

Одинаковые коды — не совпадение, а условие проверки: каждый запрос сначала
выполняется тем, кому правка ОТКРЫТА (УК на эталоне, AM на своём), и обязан
изменить хранилище. Только тогда отказ постороннему на том же запросе означает
границу пространства, а не неполную форму.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import replace
from datetime import date
from pathlib import Path

from mcp_checklist_harness import build_methodology

from src.mcp import checklist_tools as door
from src.mcp.checklist import Store, current_version, tip_version
from src.mcp.checklist_layout import ACTIVE
from src.mcp.checklists import create, set_state

СЕГОДНЯ = date(2026, 9, 30)
УК, ПАРТНЁР, ДРУГОЙ = "HQ", "AM", "GE"


def собрать_образец(корень: Path) -> Path:
    """Собрать хранилище в `корень` (`методика/`, `хранилище/`) и вернуть его.

    Зовётся фикстурой уровня модуля: один раз на файл тестов, дальше копии.
    """
    методика = build_methodology(корень / "методика")
    store = Store(root=корень / "хранилище", live=методика)
    current_version(store)
    эталон = replace(store, space="hq", code="bizdev")
    door.remove_checklist_item(tenant=УК, store=эталон, code="CLN02", version_name="imf")
    create(
        replace(store, space="hq", code="spare"),
        tenant=УК,
        name_ru="Запас",
        name_en="Spare",
        today=СЕГОДНЯ,
    )
    rnd = replace(store, space="am", code="rnd")
    create(rnd, tenant=ПАРТНЁР, name_ru="РНД", name_en="RnD", today=СЕГОДНЯ)
    door.add_zone(tenant=ПАРТНЁР, store=rnd, code="fridge", name_ru="Холод", equal_shares=True)
    door.add_zone(tenant=ПАРТНЁР, store=rnd, code="dough", name_ru="Тесто", equal_shares=True)
    door.remove_zone(tenant=ПАРТНЁР, store=rnd, code="all", equal_shares=True)
    for код, зона in (("CLN01", "fridge"), ("CLN02", "dough")):
        door.add_checklist_item(
            tenant=ПАРТНЁР,
            store=rnd,
            process="Чистота",
            question_ru=f"Вопрос {код}",
            levels="D1;D2",
            code=код,
            zones=зона,
            days="10",
            criteria="D1: проба\nD2: проба",
            kind="violation",
        )
    # Опубликован и «в работе» — как живой чек-лист партнёра: иначе бот его не откроет
    # и переключатель бота нечего было бы проверять. CLN02 выключен уже после
    # публикации: у публикации остаётся свежая версия.
    door.publish_checklist_version(tenant=ПАРТНЁР, store=rnd, version=tip_version(rnd))
    set_state(rnd, tenant=ПАРТНЁР, state=ACTIVE)
    door.remove_checklist_item(tenant=ПАРТНЁР, store=rnd, code="CLN02")
    # Ещё одна правка после выключения: иначе возврат CLN02 совпал бы с уже лежащей
    # версией, и хранилище по праву отказало бы — контролю возврата нечего было бы менять.
    door.edit_checklist_item(tenant=ПАРТНЁР, store=rnd, code="CLN01", question_ru="Пол сухой")
    return корень


def свежее_хранилище(образец: Path, куда: Path) -> Store:
    """Копия образца для одного теста. Указатели относительные — копия самостоятельна."""
    shutil.copytree(образец, куда, symlinks=True)
    return Store(root=куда / "хранилище", live=куда / "методика")


def снимок(корень: Path, *, кроме: str | None = None) -> dict[str, object]:
    """Всё хранилище байт в байт (и куда смотрит каждый указатель), кроме пространства `кроме`."""
    итог: dict[str, object] = {}
    for путь in sorted(корень.rglob("*")):
        часть = путь.relative_to(корень)
        if кроме is not None and часть.parts[0] == кроме:
            continue
        if путь.is_symlink():
            итог[str(часть)] = ("->", os.readlink(путь))
        elif путь.is_file():
            итог[str(часть)] = путь.read_bytes()
    return итог
