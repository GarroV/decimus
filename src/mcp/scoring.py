"""Ставки вычетов и начальный процент версии методики — чтение (T348).

Читается ФАЙЛ `scoring.json` выбранной версии, и ничего не пересчитывается:
второй экземпляр арифметики в продукте запрещён под любым видом — проценты,
буква и разбивка приходят только из `audit.py score` (конституция, принцип 2).

Отдаётся ровно то, что правится дверью `set_scoring`: начальный процент, ставки
классов и множитель повтора. Пороги букв и режим D3 живут в том же файле, но
сюда не попадают намеренно — показать их рядом с правимыми полями значило бы
пообещать, что и они правятся отсюда.
"""

from __future__ import annotations

import json
from typing import Any

from .checklist import Store, _ensure, _version_dir


def read(store: Store, *, version: str | None = None) -> dict[str, Any]:
    """Ставки этой версии. Файла нет — пустой ответ, а не выдуманные нули."""
    каталог = _version_dir(store, _ensure(store) if version is None else version)
    путь = каталог / "scoring.json"
    if not путь.is_file():
        return {"start_pct": None, "penalty": {}, "repeat_multiplier": None}
    тело = json.loads(путь.read_text(encoding="utf-8"))
    ставки = тело.get("penalty") or {}
    return {
        "start_pct": тело.get("start_pct"),
        "penalty": {str(класс): значение for класс, значение in sorted(ставки.items())},
        "repeat_multiplier": тело.get("repeat_multiplier"),
    }
