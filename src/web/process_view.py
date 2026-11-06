"""Итог по процессам на карточке проверки (D714, прототип).

В режиме процессов движок отдаёт разбивку `by_process` со свёрнутыми
нарушениями: пункт, старший класс, зоны-адреса и номера записей. Здесь она
только раскладывается для показа: процессы по тяжести, записи под своим
пунктом, зоны — словами. Ни одного числа оценки этот модуль не считает:
потеря процесса и пункта приходят из базы такими, какими их положил движок.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .view import level_tone, pick

#: Метка режима в разбивке движка (`engine/audit.py`, `compute_by_process`).
PROCESS_MODEL = "process"

_LEVEL_ORDER = {"D3": 0, "D2": 1, "D1": 2}


@dataclass(frozen=True)
class ProcessItem:
    """Одно свёрнутое нарушение: пункт процесса и все записи, где его нашли."""

    code: str
    level: str
    tone: str
    repeat: bool
    zones: tuple[str, ...]
    counted: bool
    cost: str
    findings: tuple[Any, ...]


@dataclass(frozen=True)
class ProcessLine:
    """Процесс: статус, потеря и свёрнутые нарушения."""

    code: str
    name: str
    scored: bool
    zeroed: bool
    loss: str
    has_loss: bool
    counts: tuple[tuple[str, int, str], ...]
    items: tuple[ProcessItem, ...]


@dataclass(frozen=True)
class ZoneCount:
    """Зона обхода — только адрес: сколько записей каких классов там найдено."""

    code: str
    name: str
    counts: tuple[tuple[str, int, str], ...]


def is_process_model(by_process: Mapping[str, Any] | None) -> bool:
    """Посчитана ли проверка в режиме процессов — по метке движка в разбивке."""
    return any(
        isinstance(p, Mapping) and p.get("model") == PROCESS_MODEL
        for p in (by_process or {}).values()
    )


def _as_float(value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _text(value: object) -> str:
    return "—" if value is None else f"{_as_float(value):g}"


def _counts(raw: Mapping[str, Any]) -> tuple[tuple[str, int, str], ...]:
    out = []
    for level in ("D3", "D2", "D1"):
        n = int(raw.get(level) or 0)
        if n:
            out.append((level, n, level_tone(level)))
    return tuple(out)


def _item(
    raw: Mapping[str, Any], by_n: Mapping[int, Any], zone_names: Mapping[str, str]
) -> ProcessItem:
    level = str(raw.get("level") or "")
    numbers = [int(n) for n in raw.get("findings") or ()]
    return ProcessItem(
        code=str(raw.get("qid") or ""),
        level=level,
        tone=level_tone(level),
        repeat=bool(raw.get("repeat")),
        zones=tuple(zone_names.get(str(z), str(z)) for z in raw.get("zones") or ()),
        counted=bool(raw.get("counted")),
        cost=_text(raw.get("cost")),
        findings=tuple(by_n[n] for n in numbers if n in by_n),
    )


def process_lines(
    by_process: Mapping[str, Any],
    findings: Sequence[Any],
    zone_names: Mapping[str, str],
    lang: str,
) -> tuple[ProcessLine, ...]:
    """Процессы проверки: обнулённые сверху, дальше по потере, чистые — внизу.

    Неоцениваемые процессы (информационная часть) не показываются: в них
    нечему быть нарушением, а строка «OK» там читалась бы как проверенная.
    """
    by_n = {int(f.n): f for f in findings}
    lines = []
    for key, raw in by_process.items():
        if not isinstance(raw, Mapping) or not raw.get("scored"):
            continue
        items = sorted(
            (_item(i, by_n, zone_names) for i in raw.get("items") or ()),
            key=lambda i: (_LEVEL_ORDER.get(i.level, 9), i.code),
        )
        loss = _as_float(raw.get("loss"))
        lines.append(
            ProcessLine(
                code=str(raw.get("code") or key),
                name=pick(raw.get("name_ru") or key, raw.get("name_en") or key, lang),
                scored=True,
                zeroed=bool(raw.get("zeroed")),
                loss=_text(raw.get("loss")),
                has_loss=loss > 0,
                counts=_counts(raw),
                items=tuple(items),
            )
        )
    return tuple(
        sorted(lines, key=lambda p: (not p.zeroed, -_as_float(p.loss), not p.items, p.name))
    )


def zone_counts(by_zone: Mapping[str, Any], lang: str) -> tuple[ZoneCount, ...]:
    """Зоны, где что-то нашли, — со счётчиками записей; потери у зоны в этом режиме нет."""
    out = []
    for code in sorted(by_zone):
        raw = by_zone[code]
        counts = _counts(raw.get("counts") or raw)
        if counts:
            out.append(
                ZoneCount(
                    code=code,
                    name=pick(raw.get("name_ru") or code, raw.get("name_en") or code, lang),
                    counts=counts,
                )
            )
    return tuple(out)
