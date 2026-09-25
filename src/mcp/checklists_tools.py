"""Инструменты MCP уровня чек-листа: перечень, заведение, состояние, применение к проду.

Правило, по которому этот модуль существует: **ни одна возможность не
появляется только на экране**. Каждая операция хранилища получает и маршрут
веба, и инструмент MCP — в одном изменении. Иначе две двери к одной методике
расходятся молча, а это ровно то, чего вся конструкция избегает (D180).

Соседний модуль (`checklist_tools.py`) правит методику ВНУТРИ чек-листа. Здесь
работа уровнем выше — с чек-листом как сущностью, — и делает её
`src/mcp/checklists.py`: этот файл только переводит вызов агента в её вызов и
ответ в словарь, который агент увидит.
"""

from __future__ import annotations

from typing import Any

from . import checklists as api
from .checklist_layout import Store, read_meta
from .errors import ChecklistError


def _row(чеклист: api.Overview) -> dict[str, Any]:
    """Одна строка перечня — та же и в списке, и в ответе на правку."""
    return {
        "checklist": чеклист.code,
        "space": чеклист.space,
        "name_ru": чеклист.name_ru,
        "name_en": чеклист.name_en,
        "state": чеклист.state,
        "applied_to_production": чеклист.in_production,
        "version": чеклист.version,
    }


def checklists(*, tenant: str, store: Store) -> dict[str, Any]:
    """Все чек-листы хранилища: код, названия, состояние, применён ли к проду.

    Состояние и применение к проду — разные вещи, и перечень показывает оба.
    «В работе» говорит, что чек-лист годен к употреблению, и таких может быть
    несколько; «применён к проду» — указатель, и он ровно один, пока выбор
    чек-листа на старте проверки не спрашивают (D178).
    """
    найденные = api.overview(store)
    в_проде = next((c.code for c in найденные if c.in_production), None)
    return {
        "tenant": tenant,
        "count": len(найденные),
        "applied_to_production": в_проде,
        "status": (
            f"{len(найденные)} checklists stored; inspections are scored against "
            + (f"{в_проде}" if в_проде else "none of them — no checklist is applied to production")
        ),
        "checklists": [_row(c) for c in найденные],
    }


def checklist_meta(*, tenant: str, store: Store) -> dict[str, Any]:
    """Один чек-лист целиком. Незнакомый код — отказ, а не пустой ответ.

    Пустой ответ на незнакомый код агент однажды перескажет человеку как «такой
    чек-лист есть, но он пуст», и это будет неправдой.
    """
    карточка = read_meta(store)
    if карточка is None:
        raise ChecklistError(
            f"Чек-листа «{store.code}» в пространстве «{store.space}» нет. Перечень отдаёт "
            f"checklists, завести новый — create_checklist"
        )
    найденный = next(
        (c for c in api.overview(store) if (c.space, c.code) == (store.space, store.code)), None
    )
    if найденный is None:
        raise ChecklistError(f"Чек-листа «{store.code}» в хранилище нет")
    return {"tenant": tenant, "status": f"checklist {store.code}", **_row(найденный)}


def create_checklist(*, tenant: str, store: Store, name_ru: str, name_en: str) -> dict[str, Any]:
    """Завести чек-лист с нуля из бланка. Рождается черновиком.

    Код приходит тем же параметром `checklist`, что и у всех остальных
    инструментов, — своего имени у него здесь нет намеренно: один и тот же
    смысл, названный двумя словами, однажды разъедется.
    """
    заведён = api.create(store, tenant=tenant, name_ru=name_ru, name_en=name_en)
    return {
        "tenant": tenant,
        "status": (
            f"checklist {заведён.code} created from the blank as a draft with no items; it scores "
            f"nothing until items are added, and a checklist without items cannot be applied to "
            f"production"
        ),
        **_row(заведён),
    }


def rename_checklist(
    *, tenant: str, store: Store, name_ru: str | None = None, name_en: str | None = None
) -> dict[str, Any]:
    """Поменять названия чек-листа. Код не меняется ничем и никогда."""
    стало = api.rename(store, tenant=tenant, name_ru=name_ru, name_en=name_en)
    return {
        "tenant": tenant,
        "status": f"checklist {стало.code} renamed; the code itself never changes",
        **_row(стало),
    }


def set_checklist_state(*, tenant: str, store: Store, state: str) -> dict[str, Any]:
    """Черновик / в работе / снят."""
    стало = api.set_state(store, tenant=tenant, state=state)
    return {
        "tenant": tenant,
        "status": f"checklist {стало.code} is now {стало.state}",
        **_row(стало),
    }


def apply_checklist(*, tenant: str, store: Store) -> dict[str, Any]:
    """Применить чек-лист к проду: по нему пойдут проверки.

    Уже посчитанные проверки остаются на своём чек-листе и своём издании и не
    пересчитываются никогда — отчёт, ушедший партнёру, задним числом не
    меняется.
    """
    итог = api.apply_to_production(store, tenant=tenant)
    return {"tenant": tenant, **итог}
