"""Два режима загрузки проверок задним числом (D332, D334): что каждый принимает.

`current` — недавняя проверка по ДЕЙСТВУЮЩЕЙ версии эталона УК: тот чек-лист,
что применён к проду, и его опубликованное издание. Выбрать другой чек-лист или
старую версию нельзя — отказ словами. Дальше всё как у обхода: записи сверяет и
оценку считает движок.

`history` — проверка по прежней методике из старого отчёта. Оценка переносится
как есть (D332): `reported_pct` обязателен и он же — оценка проверки. Версии
хранилища у неё нет: `legacy:<метка прежней методики>`. Записи описательные:
формулировка обязательна, код пункта, класс и зона — если отчёт их назвал. Код,
если назван, мягко сверяется с действующим чек-листом: незнакомый — предупреждение,
а не отказ (у старых чек-листов свои коды).

Здесь — разбор аргументов и вид ответа; запросов к базе и вызовов движка нет.
"""

from __future__ import annotations

import csv
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..db.models import LEGACY_VERSION_PREFIX
from .checklist import current_version
from .checklist_layout import Store, locate
from .errors import ChecklistError, ToolError

if TYPE_CHECKING:
    from ..db.models import FindingRow

#: Режимы, как их называет агент коллеги. Происхождение в базе — `ORIGIN_*`
#: в `src/db/models.py`.
MODE_CURRENT = "current"
MODE_HISTORY = "history"
MODES = (MODE_HISTORY, MODE_CURRENT)

#: Пределы полей шапки исторической — те же, что держит схема (0042).
MAX_REPORTED_STATUS = 60
MAX_LEGACY_METHOD = 100

#: Код пункта — буквы и цифры (`CLN05`, `INF10`); зона — код справочника зон
#: (`hot_kitchen`). Связь только кодами: формулировки переводятся, коды нет.
_CODE = re.compile(r"^[A-Z0-9]{2,16}$")
_ZONE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")

#: Знаки, которые не годятся в имени версии (`domain.version.check_version`):
#: метка прежней методики — свободный текст, а версия — имя.
_NOT_IN_VERSION = re.compile(r"[/\\\x00]")

#: Метка, когда старый отчёт методику не назвал.
UNLABELLED = "unlabelled"


@dataclass(frozen=True)
class Reference:
    """Действующий эталон УК: код чек-листа, применённого к проду, и его версия."""

    code: str
    version: str


def parse_mode(mode: str | None) -> str:
    """Режим черновика — обязательный и один из двух (D334)."""
    чистый = (mode or "").strip().lower()
    if чистый not in MODES:
        raise ToolError(
            "Назовите режим mode: history — проверка по прежней методике из старого отчёта, "
            "оценка переносится как в отчёте; current — недавняя проверка по нынешнему "
            "чек-листу, оценку считает движок. Режим задаётся при создании и потом не меняется"
        )
    return чистый


def _checked[T](call: Callable[[], T]) -> T:
    try:
        return call()
    except ChecklistError as отказ:
        raise ToolError(str(отказ)) from None


def reference(store: Store, *, tenant: str) -> Reference:
    """Действующий эталон: чек-лист, применённый к проду, и его опубликованное издание."""
    найден = _checked(lambda: locate(store, tenant=tenant, code=None))
    if найден is None:
        raise ToolError(
            "Действующий эталон УК не найден в хранилище методики — загрузка не может "
            "понять, по какому чек-листу идут проверки. Это отказ настройки"
        )
    return Reference(code=найден.code, version=_checked(lambda: current_version(найден)))


def current_only(store: Store, *, tenant: str, code: str | None, version: str | None) -> Reference:
    """Режим current: только действующий эталон и его действующая версия (D334)."""
    эталон = reference(store, tenant=tenant)
    названный_код = (code or "").strip()
    if названный_код and названный_код != эталон.code:
        raise ToolError(
            f"В режиме current проверка заводится только по действующему эталону УК "
            f"«{эталон.code}», а назван «{названный_код}». Проверку по другому или старому "
            f"чек-листу заводят в режиме history — с оценкой из её отчёта"
        )
    названная = (version or "").strip()
    if названная and названная != эталон.version:
        raise ToolError(
            f"В режиме current выбрать версию нельзя: действующая — «{эталон.version}», а "
            f"названа «{названная}». Проверку по прежней методике заводят в режиме history "
            f"— с оценкой из старого отчёта, без пересчёта (D332)"
        )
    return эталон


def legacy_version(label: str | None) -> str:
    """Версия исторической: `legacy:<метка>` — заведомо не версия хранилища."""
    метка = _NOT_IN_VERSION.sub("-", (label or "").strip()) or UNLABELLED
    return f"{LEGACY_VERSION_PREFIX}{метка}"


def refuse_history_choice(code: str | None, version: str | None) -> None:
    """В режиме history чек-лист и версию не выбирают — метка прежней методики вместо них."""
    if (code or "").strip() or (version or "").strip():
        raise ToolError(
            "В режиме history чек-лист и версию хранилища не называют: проверка остаётся "
            "в линии эталона УК, а прежнюю методику называют меткой legacy_method "
            "(например, «Qvalon 133», «старый чек-лист 253»). Оценка — из отчёта, как есть"
        )


def refuse_history_fields(status: str | None, method: str | None) -> None:
    """Статус старого отчёта и метка методики — только у исторической."""
    if status is not None or method is not None:
        raise ToolError(
            "reported_status и legacy_method — только для режима history: у текущей "
            "проверки статуса старого отчёта и прежней методики нет"
        )


# --- записи исторической ----------------------------------------------------


def legacy_code(value: str | None) -> str | None:
    """Код пункта из старого отчёта: `None` — не назван; кривой — отказ."""
    if value is None or not value.strip():
        return None
    код = value.strip().upper()
    if not _CODE.match(код):
        raise ToolError(
            f"Код пункта «{value.strip()}» — не код: ожидаются латинские буквы и цифры "
            f"(CLN05, PRD09). Если отчёт пункта не называет — не передавайте code"
        )
    return код


def legacy_level(value: str | None) -> str | None:
    """Класс из старого отчёта: D1, D2, D3 или не назван («без класса»)."""
    if value is None or not value.strip():
        return None
    класс = value.strip().upper()
    if класс not in {"D1", "D2", "D3"}:
        raise ToolError(
            f"Класс исторической записи — D1, D2 или D3, если отчёт его называет; иначе не "
            f"передавайте level — запись будет «без класса». «{value.strip()}» не принимается"
        )
    return класс


def legacy_zone(value: str | None) -> str | None:
    """Зона — код справочника зон, если отчёт место называет; иначе `None`."""
    if value is None or not value.strip():
        return None
    зона = value.strip().lower()
    if not _ZONE.match(зона):
        raise ToolError(
            f"Зона «{value.strip()}» — не код зоны (hot_kitchen, dining …). Если место в "
            f"отчёте не названо — не передавайте zone"
        )
    return зона


def _ids(path: Path, column: str) -> frozenset[str] | None:
    try:
        with path.open(encoding="utf-8", newline="") as f:
            return frozenset((r.get(column) or "").strip() for r in csv.DictReader(f))
    except OSError:
        return None


def soft_warnings(store: Store, *, code: str | None, zone: str | None) -> list[str]:
    """Мягкая сверка с действующей методикой: предупреждения, не отказ (D332).

    Старый Qvalon-чек-лист на 133 вопроса совпадает кодами с нынешним, старые на
    253/217/150 — нет. Незнакомый код не ошибка загрузки, но коллеге стоит
    глянуть, не опечатка ли это.
    """
    предупреждения: list[str] = []
    if code is not None:
        коды = _ids(store.live / "checklist.csv", "id")
        if коды is not None and code not in коды:
            предупреждения.append(
                f"code {code} is not in the current checklist — kept as given (old "
                f"checklists have their own codes); check it is not a typo"
            )
    if zone is not None:
        зоны = _ids(store.live / "zones.csv", "id")
        if зоны is not None and zone not in зоны:
            предупреждения.append(
                f"zone {zone} is not in the current zone directory — kept as given; check it "
                f"is not a typo"
            )
    return предупреждения


def merged(
    прежняя: FindingRow,
    *,
    code: str | None,
    level: str | None,
    zone: str | None,
    repeat: bool | None,
) -> dict[str, Any]:
    """Правка исторической записи поверх прежней: `None` — не трогать, `""` — снять."""
    from ..db.models import LEGACY_CODE, NO_CLASS, NO_ZONE

    def было(значение: str, маркер: str) -> str | None:
        return None if значение == маркер else значение

    return {
        "code": было(прежняя.code, LEGACY_CODE) if code is None else legacy_code(code),
        "level": было(прежняя.level, NO_CLASS) if level is None else legacy_level(level),
        "zone": было(прежняя.zone, NO_ZONE) if zone is None else legacy_zone(zone),
        "repeat": прежняя.repeat if repeat is None else bool(repeat),
    }


def legacy_finding_view(row: FindingRow) -> dict[str, object]:
    """Запись исторической для агента: маркеры — словами, а не кодами-заглушками."""
    from ..db.models import LEGACY_CODE, NO_CLASS, NO_ZONE

    return {
        "n": row.n,
        "code": None if row.code == LEGACY_CODE else row.code,
        "level": None if row.level == NO_CLASS else row.level,
        "level_note": "no class (the old report gives none)" if row.level == NO_CLASS else None,
        "zone": None if row.zone == NO_ZONE else row.zone,
        "repeat": row.repeat,
        "text": row.text,
        "comment": row.comment,
        "lang": row.lang,
    }
