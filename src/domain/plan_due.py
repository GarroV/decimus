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

import json
from collections.abc import Mapping

from .config import check_environment
from .errors import ConfigError

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
