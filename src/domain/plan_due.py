"""Срок ответа партнёра планом исправлений — один на письмо, бот и веб (D617).

Раньше их было два: письмо и бот брали `plan_due_days` из `scoring.json`
(10 дней), а запрос плана в вебе — переменную окружения веба (7 дней). Партнёр
читал в письме одну дату, а на экране видел другую. Теперь число живёт только в
методике, рядом со ставками и порогами, и движок, и веб читают его оттуда.

Отсутствие или мусор в поле — отказ, а не подставленное число: срок, которого
нет в методике, это ошибка данных, и выдать за него «какое-нибудь» значит снова
развести письмо и экран.
"""

from __future__ import annotations

import csv
import json
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from . import edition, item_label
from .config import DATA_FILES, Settings, check_environment
from .errors import ConfigError
from .models import DEFAULT_CHECKLIST_CODE
from .version import compose

logger = logging.getLogger(__name__)

PLAN_DUE_KEY = "plan_due_days"
#: Ловушка на лишний ноль, а не предел методики.
MAX_PLAN_DUE_DAYS = 365


def plan_due_days(env: Mapping[str, str] | None = None) -> int:
    """Сколько дней у партнёра на ответ планом — из `scoring.json` методики."""
    файл = check_environment(env).data_dir / "scoring.json"
    try:
        значение: object = json.loads(файл.read_text(encoding="utf-8")).get(PLAN_DUE_KEY)
    except (OSError, ValueError) as exc:
        raise ConfigError(f"Срок плана не прочитан: {файл} не читается ({exc})") from exc
    if isinstance(значение, bool) or not isinstance(значение, int):
        raise ConfigError(f"В {файл.name} нет целого {PLAN_DUE_KEY}: срок плана неизвестен")
    if not 1 <= значение <= MAX_PLAN_DUE_DAYS:
        raise ConfigError(
            f"{PLAN_DUE_KEY}={значение} в {файл.name} непригоден: нужно от 1 до {MAX_PLAN_DUE_DAYS}"
        )
    return значение


# ── Срок строки плана (электронный план исправлений, D612, D613, D617) ─────
#
# Правило то же, что у движка при сборке отчёта (`engine/audit.py`, поле `due`
# у записи): дни пункта методики (`days` в `checklist.csv`), не больше
# `deadlines.max_days` по классу из `scoring.json`. D3 — немедленно: потолок
# класса там нуль. Считает только этот модуль и только из методики — ни веб,
# ни база чисел не держат. Расхождение с движком ловит
# `tests/test_domain_plan_deadlines.py`.

#: Классы в начале формулировки пункта — «(D1, D2) …»: в строке плана они лишние.
_LEVEL_PREFIX = re.compile(r"^\(\s*D\d(?:\s*,\s*D\d)*\s*\)\s*")

DEADLINES_KEY = "deadlines"
MAX_DAYS_KEY = "max_days"


@dataclass(frozen=True)
class Deadlines:
    """Сроки методики: потолок дней по классу и дни каждого пункта."""

    max_days: Mapping[str, int]
    item_days: Mapping[str, int]
    #: Формулировки пунктов той же методики — для снимка в строке плана.
    item_texts: Mapping[str, item_label.ItemTexts] = field(default_factory=dict)

    def wording_for(self, code: str) -> tuple[str, str]:
        """Формулировка пункта на ru и en без «(D1, D2)» в начале; пункта нет — пустые."""
        own = self.item_texts.get(code.strip().upper())
        if own is None:
            return "", ""
        return (
            _LEVEL_PREFIX.sub("", own.question_ru).strip(),
            _LEVEL_PREFIX.sub("", own.question_en).strip(),
        )

    def days_for(self, code: str, level: str) -> int:
        """Сколько дней на устранение: дни пункта, но не больше потолка класса.

        Пункта в методике нет (издание не найдено, пункт убран) — потолок класса:
        срок «сегодня» вместо него выдал бы партнёру просрочку, которой нет.
        Класса в потолках нет — дни самого пункта. Нет ни того ни другого — отказ.
        """
        потолок = self.max_days.get(level)
        дни = self.item_days.get(code)
        if дни is None:
            if потолок is None:
                raise ConfigError(
                    f"Срок строки плана не определить: пункта «{code}» нет в методике, "
                    f"а у класса «{level}» нет потолка в {DEADLINES_KEY}.{MAX_DAYS_KEY}"
                )
            return потолок
        return дни if потолок is None else min(дни, потолок)


def row_due_on(count_from: date, days: int) -> date:
    """Положенный срок строки: начало отсчёта плюс дни; нуль дней — «немедленно», сам день."""
    if days < 0:
        raise ConfigError(f"Дни строки плана отрицательные ({days}) — срок не определить")
    return count_from + timedelta(days=days)


def plan_due_on(count_from: date, env: Mapping[str, str] | None = None) -> date:
    """Срок ответа планом: начало отсчёта плюс `plan_due_days` методики (D613, D617)."""
    return count_from + timedelta(days=plan_due_days(env))


def effective_row_due(
    count_from: date, days: int, own_due: date | None, extended_due: date | None
) -> date:
    """Действующий срок строки.

    Перенос с согласием (`extended_due`) перекрывает всё. Иначе — срок партнёра,
    если он поставил его РАНЬШЕ положенного (позже положенного срок не ставится,
    только переносом с согласием); положенный, если не ставил или поставил позже
    после того, как отсчёт сдвинули.
    """
    if extended_due is not None:
        return extended_due
    положенный = row_due_on(count_from, days)
    if own_due is None:
        return положенный
    return min(own_due, положенный)


def load_deadlines(
    version: str, code: str = DEFAULT_CHECKLIST_CODE, env: Mapping[str, str] | None = None
) -> Deadlines:
    """Сроки той методики, по которой проведена проверка (версия и код чек-листа).

    Каталог — действующий, если проверка по нему; иначе снимок издания, если он
    есть. Снимка нет — действующая методика: срок строки приблизительный, но
    проверка не остаётся без плана. `scoring.json` без потолков — отказ:
    срока, которого нет в методике, не выдумываем.
    """
    settings = check_environment(env)
    каталог = _methodology_dir(settings, version, code)
    дни, тексты = _items(каталог)
    return Deadlines(max_days=_max_days(каталог), item_days=дни, item_texts=тексты)


def _methodology_dir(settings: Settings, version: str, code: str) -> Path:
    if code == DEFAULT_CHECKLIST_CODE and version == compose(settings.data_dir, DATA_FILES):
        return settings.data_dir
    kept = edition.snapshot(settings, version, code)
    if kept is not None:
        return kept
    logger.warning(
        "снимка издания %s (чек-лист %s) нет — срок строк плана по действующей методике",
        version,
        code,
    )
    return settings.data_dir


def _max_days(каталог: Path) -> dict[str, int]:
    файл = каталог / "scoring.json"
    try:
        сырое: object = json.loads(файл.read_text(encoding="utf-8")).get(DEADLINES_KEY)
    except (OSError, ValueError) as exc:
        raise ConfigError(f"Сроки методики не прочитаны: {файл} не читается ({exc})") from exc
    потолки = сырое.get(MAX_DAYS_KEY) if isinstance(сырое, dict) else None
    if not isinstance(потолки, dict) or not _ceilings_ok(потолки):
        raise ConfigError(
            f"В {файл.name} нет {DEADLINES_KEY}.{MAX_DAYS_KEY} с целыми неотрицательными "
            f"числами: срок строки плана неизвестен"
        )
    return {str(k): int(v) for k, v in потолки.items()}


def _ceilings_ok(потолки: Mapping[object, object]) -> bool:
    return all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in потолки.values())


def _items(каталог: Path) -> tuple[dict[str, int], dict[str, item_label.ItemTexts]]:
    файл = каталог / "checklist.csv"
    try:
        with файл.open(encoding="utf-8-sig", newline="") as f:
            строки = list(csv.DictReader(f))
    except OSError as exc:
        raise ConfigError(f"Дни пунктов не прочитаны: {файл} не читается ({exc})") from exc
    дни: dict[str, int] = {}
    for строка in строки:
        код = (строка.get("id") or "").strip()
        if not код or код.startswith("#"):
            continue
        сырое = (строка.get("days") or "").strip()
        try:
            # Пустая клетка — нуль, как у движка: пункт без дней не откладывается.
            дни[код] = int(float(сырое)) if сырое else 0
        except ValueError as exc:
            raise ConfigError(
                f"Срок устранения не число: у пункта «{код}» в колонке days стоит «{сырое}»"
            ) from exc
    return дни, item_label.from_csv(строки)
