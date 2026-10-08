"""Чтение рейтингов для сводки и экрана «Загрузки», правка справочников (0038).

Читают все роли приложения (D327, «рейтинги видят все»): заслона по охвату
здесь нет намеренно. Правка справочников — роль приложения; кто вправе её
звать, решает веб (`may_manage_ratings`).

Каждый SQL — полный текст с параметрами `%s`, строкой не собирается (S608).
Ключ `ratings.scores` — (пиццерия, период), а `units` и `periods` соединяются по
первичным ключам: соединение строк не множит.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import psycopg

from .config import check_environment
from .errors import RatingsError

#: Коды отказа правки справочников: веб показывает по ним текст на языке
#: интерфейса (P15), русский `str(exc)` остаётся журналу и MCP.
REFUSED_DEVELOPER = "developer_invalid"
REFUSED_RULE = "rule_invalid"
REFUSED_RULE_KEPT = "rule_kept"
REFUSED_SETTING = "setting_invalid"
REFUSED_SETTING_UNKNOWN = "setting_unknown"
REFUSED_DB = "db_failed"


class RatingsEditError(RatingsError):
    """Правка справочника не легла. `code` — причина для текста по языку."""

    def __init__(self, message: str, code: str, **params: str) -> None:
        super().__init__(message)
        self.code = code
        self.params: Mapping[str, str] = params


def _rows(sql: str, params: Sequence[Any] = ()) -> list[tuple[Any, ...]]:
    try:
        with psycopg.connect(check_environment().dsn) as conn:
            return conn.execute(sql, params).fetchall()
    except psycopg.Error as exc:
        raise RatingsError(
            f"Рейтинги не прочитались: база отказала ({exc.__class__.__name__})"
        ) from exc


def _write(sql: str, params: Sequence[Any], refusal: str, code: str) -> int:
    try:
        with psycopg.connect(check_environment().dsn) as conn:
            return conn.execute(sql, params).rowcount
    except psycopg.errors.IntegrityError as exc:
        raise RatingsEditError(refusal, code) from exc
    except psycopg.Error as exc:
        raise RatingsEditError(
            f"Правка не легла: база отказала ({exc.__class__.__name__})", REFUSED_DB
        ) from exc


@dataclass(frozen=True)
class CountryRow:
    code: str
    name_ru: str
    name_en: str
    developer: str | None
    is_imf: bool


def countries() -> tuple[CountryRow, ...]:
    return tuple(
        CountryRow(*r)
        for r in _rows(
            "select code, name_ru, name_en, developer, is_imf from ratings.countries "
            "order by name_en, code"
        )
    )


def rs_periods() -> tuple[tuple[int, date, date, str, str], ...]:
    """Периоды РС, новые первыми: `(id, begin_on, end_on, title_ru, title_en)`."""
    return tuple(
        (int(r[0]), r[1], r[2], r[3], r[4])
        for r in _rows(
            "select id, begin_on, end_on, title_ru, title_en from ratings.periods "
            "where rating_type = 'rs' order by begin_on desc"
        )
    )


def last_period_ids(rating_type: str, *, until: date, n: int) -> tuple[int, ...]:
    """Последние `n` периодов типа, начавшихся не позже `until`, старые первыми."""
    rows = _rows(
        "select id from ratings.periods where rating_type = %s and begin_on <= %s "
        "order by begin_on desc limit %s",
        (rating_type, until, n),
    )
    return tuple(int(r[0]) for r in reversed(rows))


_SCORES_BY_DATES = (
    "select s.unit_dodo_id, u.name, u.country_code, p.rating_type, p.id, p.begin_on, "
    "s.score::float "
    "from ratings.scores s join ratings.units u on u.dodo_id = s.unit_dodo_id "
    "join ratings.periods p on p.id = s.period_id "
    "where u.country_code = any(%s) and p.begin_on between %s and %s "
    "order by p.begin_on, s.unit_dodo_id"
)
_SCORES_BY_IDS = (
    "select s.unit_dodo_id, u.name, u.country_code, p.rating_type, p.id, p.begin_on, "
    "s.score::float "
    "from ratings.scores s join ratings.units u on u.dodo_id = s.unit_dodo_id "
    "join ratings.periods p on p.id = s.period_id "
    "where u.country_code = any(%s) and p.id = any(%s) "
    "order by p.begin_on, s.unit_dodo_id"
)


def score_facts(
    *, countries: Sequence[str], begin: date, end: date, period_ids: Sequence[int] = ()
) -> list[tuple[Any, ...]]:
    """`(unit, unit_name, country, rating_type, period_id, begin_on, score)`.

    Периоды, начавшиеся в `[begin, end]`, или ровно `period_ids`, если даны.
    """
    if period_ids:
        return _rows(_SCORES_BY_IDS, (list(countries), list(period_ids)))
    return _rows(_SCORES_BY_DATES, (list(countries), begin, end))


#: Проверки РКО среза: дата заказа внутри периода, отклонённые на приёмке — вне
#: счёта (решение плана 8).
_RKO_FACTS = (
    "select v.unit_dodo_id, u.name, u.country_code, v.text, v.parent_name, v.category, v.amount "
    "from ratings.checkups c join ratings.units u on u.dodo_id = c.unit_dodo_id "
    "join ratings.violations v on v.rating_type = c.rating_type and v.checkup_dodo_id = c.dodo_id "
    "where c.rating_type = 'rko' and u.country_code = any(%s) "
    "and c.occurred_at >= %s and c.occurred_at < %s::date + 1 "
    "and c.acceptance is distinct from 'rejected' "
    "order by v.id"
)
_RKO_COUNTS = (
    "select u.country_code, count(*) "
    "from ratings.checkups c join ratings.units u on u.dodo_id = c.unit_dodo_id "
    "where c.rating_type = 'rko' and u.country_code = any(%s) "
    "and c.occurred_at >= %s and c.occurred_at < %s::date + 1 "
    "and c.acceptance is distinct from 'rejected' group by 1"
)


def rko_violation_facts(
    *, countries: Sequence[str], begin: date, end: date
) -> tuple[list[tuple[Any, ...]], dict[str, int]]:
    """Нарушения проверок РКО с датой в `[begin, end]` и число проверок по стране."""
    params = (list(countries), begin, end)
    counts = {r[0]: int(r[1]) for r in _rows(_RKO_COUNTS, params)}
    return _rows(_RKO_FACTS, params), counts


#: Замечания снимка висят на периоде; периоды РКО тоже несут замечания, но в
#: кластер РС они не входят.
_RS_REMARKS = (
    "select v.unit_dodo_id, u.name, u.country_code, v.text, v.parent_name, v.category, v.amount "
    "from ratings.violations v join ratings.units u on u.dodo_id = v.unit_dodo_id "
    "join ratings.periods p on p.id = v.period_id "
    "where v.category = 'remark' and p.rating_type = 'rs' "
    "and u.country_code = any(%s) and p.begin_on between %s and %s "
    "order by v.id"
)
_RS_CHECKUPS = (
    "select u.country_code, sum(s.checkups_count) from ratings.scores s "
    "join ratings.units u on u.dodo_id = s.unit_dodo_id "
    "join ratings.periods p on p.id = s.period_id "
    "where p.rating_type = 'rs' and u.country_code = any(%s) "
    "and p.begin_on between %s and %s group by 1"
)


def rs_remark_facts(
    *, countries: Sequence[str], begin: date, end: date
) -> tuple[list[tuple[Any, ...]], dict[str, int]]:
    """Замечания периодов РС, начавшихся в `[begin, end]`, и сумма проверок по стране."""
    params = (list(countries), begin, end)
    counts = {r[0]: int(r[1] or 0) for r in _rows(_RS_CHECKUPS, params)}
    return _rows(_RS_REMARKS, params), counts


def hard_rules() -> tuple[tuple[int, str, str, str], ...]:
    """`(id, rating_type, match, pattern)`."""
    return tuple(
        (int(r[0]), r[1], r[2], r[3])
        for r in _rows(
            "select id, rating_type, match, pattern from ratings.hard_rules "
            "order by rating_type, pattern, id"
        )
    )


def settings() -> dict[str, float]:
    return {r[0]: float(r[1]) for r in _rows("select key, value from ratings.settings")}


@dataclass(frozen=True)
class ImportRow:
    id: int
    at: datetime
    actor: str
    channel: str
    format: str | None
    file_name: str | None
    outcome: str
    accepted: int
    updated: int
    skipped: int
    unmatched: int
    note: str | None
    duplicate_of: int | None


def imports(limit: int = 50) -> tuple[ImportRow, ...]:
    """Журнал загрузок, новые первыми."""
    return tuple(
        ImportRow(*r)
        for r in _rows(
            "select id, at, actor, channel, format, file_name, outcome, accepted, updated, "
            "skipped, unmatched, note, duplicate_of from ratings.imports "
            "order by at desc, id desc limit %s",
            (limit,),
        )
    )


@dataclass(frozen=True)
class IssueRow:
    import_id: int
    at: datetime
    format: str | None
    row_no: int
    reason: str
    detail: dict[str, Any]


def open_issues(limit: int = 200) -> tuple[IssueRow, ...]:
    return tuple(
        IssueRow(*r)
        for r in _rows(
            "select i.import_id, m.at, m.format, i.row_no, i.reason, i.detail "
            "from ratings.import_issues i join ratings.imports m on m.id = i.import_id "
            "order by m.at desc, i.import_id desc, i.row_no, i.reason limit %s",
            (limit,),
        )
    )


def last_loaded() -> dict[str, datetime]:
    """Формат → время последней удачной загрузки."""
    return {
        r[0]: r[1]
        for r in _rows(
            "select format, max(at) from ratings.imports where outcome = 'loaded' group by format"
        )
    }


def set_developer(code: str, developer: str | None, *, actor: str) -> bool:
    value = (developer or "").strip() or None
    changed = _write(
        "update ratings.countries set developer = %s, updated_by = %s, updated_at = now() "
        "where code = %s",
        (value, actor, code),
        "Имя девелопера — до 120 знаков",
        REFUSED_DEVELOPER,
    )
    return changed > 0


def add_hard_rule(rating_type: str, match: str, pattern: str, *, actor: str) -> None:
    _write(
        "insert into ratings.hard_rules (rating_type, match, pattern, created_by) "
        "values (%s, %s, %s, %s)",
        (rating_type, match, pattern.strip(), actor),
        "Такое правило уже есть или оно пустое",
        REFUSED_RULE,
    )


def remove_hard_rule(rule_id: int) -> bool:
    changed = _write(
        "delete from ratings.hard_rules where id = %s",
        (rule_id,),
        "Правило не удалилось",
        REFUSED_RULE_KEPT,
    )
    return changed > 0


def set_setting(key: str, value: float, *, actor: str) -> None:
    changed = _write(
        "update ratings.settings set value = %s, updated_by = %s, updated_at = now() "
        "where key = %s",
        (value, actor, key),
        "Порог — от 0 до 100; число периодов — целое от 2 до 12",
        REFUSED_SETTING,
    )
    if changed == 0:
        raise RatingsEditError(f"Настройки «{key}» нет", REFUSED_SETTING_UNKNOWN, key=key)
