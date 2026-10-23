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
import logging
from collections.abc import Mapping
from datetime import date, timedelta

from .config import check_environment
from .errors import ConfigError

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
# Дни строки — НЕ отсюда: их считает движок (`engine/audit.py score`, поле `days`
# у записи: дни пункта, не больше потолка класса), и продукт берёт готовое
# (`src/report/plan_terms.py`). Здесь только сложение с началом отсчёта.


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


#: Срок, который партнёр ставит строке сам: позже положенного нельзя, раньше «сегодня» — тоже.
OWN_DUE_LATE = "late"
OWN_DUE_PAST = "past"


def own_due_problem(
    own_due: date | None,
    before: date | None,
    *,
    count_from: date,
    days: int,
    extended: date | None,
    today: date,
) -> tuple[str, date] | None:
    """Чем свой срок строки не годится: `(OWN_DUE_LATE | OWN_DUE_PAST, граница)` или `None`.

    Одно правило для формы на экране и для файла «туда и обратно»: позже положенного
    срока (дни пункта от начала отсчёта, либо перенос с согласием) партнёр срок не ставит,
    раньше сегодняшнего дня и начала отсчёта — тоже. Срок, который уже стоит (`before`), не
    проверяется заново: его не меняют.
    """
    if own_due is None or own_due == before:
        return None
    предел = extended or row_due_on(count_from, days)
    if own_due > предел:
        return OWN_DUE_LATE, предел
    нижняя = max(count_from, today)
    if own_due < нижняя:
        return OWN_DUE_PAST, нижняя
    return None
