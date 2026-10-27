"""Чтение рейтингов для сводки и экрана «Загрузки», правка справочников (0039).

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
from .pool import connection
from .request_memo import memoized

#: Коды отказа правки справочников: веб показывает по ним текст на языке
#: интерфейса (P15), русский `str(exc)` остаётся журналу и MCP.
REFUSED_DEVELOPER = "developer_invalid"
REFUSED_RULE = "rule_invalid"
REFUSED_RULE_KIND = "rule_kind_invalid"
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
        with connection(check_environment().dsn) as conn:
            return conn.execute(sql, params).fetchall()
    except psycopg.Error as exc:
        raise RatingsError(
            f"Рейтинги не прочитались: база отказала ({exc.__class__.__name__})"
        ) from exc


def _write(sql: str, params: Sequence[Any], refusal: str, code: str) -> int:
    try:
        with connection(check_environment().dsn) as conn:
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
    cluster: str = "OTHER"


def countries() -> tuple[CountryRow, ...]:
    return memoized(("ratings.countries",), _read_countries)


def _read_countries() -> tuple[CountryRow, ...]:
    return tuple(
        CountryRow(*r)
        for r in _rows(
            "select code, name_ru, name_en, developer, is_imf, cluster from ratings.countries "
            "order by name_en, code"
        )
    )


def rs_periods() -> tuple[tuple[int, date, date, str, str], ...]:
    """Периоды РС, новые первыми: `(id, begin_on, end_on, title_ru, title_en)`."""
    return memoized(("ratings.rs_periods",), _read_rs_periods)


def _read_rs_periods() -> tuple[tuple[int, date, date, str, str], ...]:
    return tuple(
        (int(r[0]), r[1], r[2], r[3], r[4])
        for r in _rows(
            "select id, begin_on, end_on, title_ru, title_en from ratings.periods "
            "where rating_type = 'rs' order by begin_on desc"
        )
    )


def rko_periods() -> tuple[tuple[int, date, date, str, str], ...]:
    """Недели РКО с оценками, новые первыми: `(id, begin_on, end_on, title_ru, title_en)`.

    Пустую неделю (период заведён, оценок нет) выбирать незачем — список строится по оценкам.
    """
    return memoized(("ratings.rko_periods",), _read_rko_periods)


def _read_rko_periods() -> tuple[tuple[int, date, date, str, str], ...]:
    return tuple(
        (int(r[0]), r[1], r[2], r[3], r[4])
        for r in _rows(
            "select p.id, p.begin_on, p.end_on, p.title_ru, p.title_en from ratings.periods p "
            "where p.rating_type = 'rko' "
            "and exists (select 1 from ratings.scores s where s.period_id = p.id) "
            "order by p.begin_on desc"
        )
    )


def period_months() -> tuple[date, ...]:
    """Месяцы, в которых начался хоть один период рейтинга (любого типа), новые первыми.

    Из них экран строит выбор месяца и квартала: предлагать период без данных незачем.
    """
    return tuple(
        r[0]
        for r in _rows(
            "select distinct date_trunc('month', begin_on)::date from ratings.periods "
            "order by 1 desc"
        )
    )


def last_period_ids(rating_type: str, *, until: date, n: int) -> tuple[int, ...]:
    """Последние `n` периодов типа с оценками, начавшихся не позже `until`, старые первыми.

    Периоды без оценок не считаются: РКО идёт двумя рядами недель (пн–вс с оценками и
    вт–пн, где только сбор, #1305) — окно из последних по началу вперемешку никогда не
    набиралось из периодов с оценками, и зона риска РКО была пуста всегда.
    """
    rows = _rows(
        "select p.id from ratings.periods p where p.rating_type = %s and p.begin_on <= %s "
        "and exists (select 1 from ratings.scores s where s.period_id = p.id) "
        "order by p.begin_on desc limit %s",
        (rating_type, until, n),
    )
    return tuple(int(r[0]) for r in reversed(rows))


_SCORES_BY_DATES = (
    "select s.unit_dodo_id, u.name, u.country_code, p.rating_type, p.id, p.begin_on, "
    "s.score::float, p.end_on "
    "from ratings.scores s join ratings.units u on u.dodo_id = s.unit_dodo_id "
    "join ratings.periods p on p.id = s.period_id "
    "where u.country_code = any(%s) and p.end_on >= %s and p.begin_on <= %s "
    "order by p.begin_on, s.unit_dodo_id"
)
_SCORES_BY_IDS = (
    "select s.unit_dodo_id, u.name, u.country_code, p.rating_type, p.id, p.begin_on, "
    "s.score::float, p.end_on "
    "from ratings.scores s join ratings.units u on u.dodo_id = s.unit_dodo_id "
    "join ratings.periods p on p.id = s.period_id "
    "where u.country_code = any(%s) and p.id = any(%s) "
    "order by p.begin_on, s.unit_dodo_id"
)


def score_facts(
    *, countries: Sequence[str], begin: date, end: date, period_ids: Sequence[int] = ()
) -> list[tuple[Any, ...]]:
    """`(unit, unit_name, country, rating_type, period_id, begin_on, score, end_on)`.

    Периоды, задевающие `[begin, end]` (D396: выбранная рамка захватывает каждый
    период, попавший в неё хотя бы днём), или ровно `period_ids`, если даны.
    """
    if period_ids:
        return _rows(_SCORES_BY_IDS, (list(countries), list(period_ids)))
    return _rows(_SCORES_BY_DATES, (list(countries), begin, end))


#: Проверки РКО среза: дата заказа внутри периода, отклонённые на приёмке — вне
#: счёта (решение плана 8). Время заказа лежит в UTC (время файла), поэтому
#: границы суток — явно в UTC, а не в часовом поясе сессии (P34).
_RKO_FACTS = (
    "select v.unit_dodo_id, u.name, u.country_code, v.text, v.parent_name, v.category, v.amount "
    "from ratings.checkups c join ratings.units u on u.dodo_id = c.unit_dodo_id "
    "join ratings.violations v on v.rating_type = c.rating_type and v.checkup_dodo_id = c.dodo_id "
    "where c.rating_type = 'rko' and u.country_code = any(%s) "
    "and c.occurred_at >= (%s::date)::timestamp at time zone 'UTC' "
    "and c.occurred_at < ((%s::date) + 1)::timestamp at time zone 'UTC' "
    "and c.acceptance is distinct from 'rejected' "
    "order by v.id"
)
_RKO_COUNTS = (
    "select u.country_code, count(*) "
    "from ratings.checkups c join ratings.units u on u.dodo_id = c.unit_dodo_id "
    "where c.rating_type = 'rko' and u.country_code = any(%s) "
    "and c.occurred_at >= (%s::date)::timestamp at time zone 'UTC' "
    "and c.occurred_at < ((%s::date) + 1)::timestamp at time zone 'UTC' "
    "and c.acceptance is distinct from 'rejected' group by 1"
)


#: Число проверок РКО по собираемости базы рейтингов (D464): отчёты ресторана и
#: доставки за неделю — это и есть проверки недели. Недели, задевающие рамку, как у РС.
_RKO_COLLECTION_COUNTS = (
    "select u.country_code, sum(c.restaurant_reports + c.delivery_reports) "
    "from ratings.collection c join ratings.units u on u.dodo_id = c.unit_dodo_id "
    "join ratings.periods p on p.id = c.period_id "
    "where p.rating_type = 'rko' and u.country_code = any(%s) "
    "and p.end_on >= %s and p.begin_on <= %s group by 1"
)


def rko_violation_facts(
    *, countries: Sequence[str], begin: date, end: date
) -> tuple[list[tuple[Any, ...]], dict[str, int]]:
    """Нарушения проверок РКО с датой в `[begin, end]` и число проверок по стране.

    Выгрузка нарушений несёт только проверки с нарушениями, и счёт по ней занизил
    бы знаменатель «нарушений на проверку». Поэтому, где у недель РКО страны, задевших
    рамку, есть собираемость (D464), берётся её сумма; у страны без неё — счёт по
    проверкам. Неделя берётся целиком, как у РС (D396).
    """
    params = (list(countries), begin, end)
    counts = {r[0]: int(r[1]) for r in _rows(_RKO_COUNTS, params)}
    counts.update({r[0]: int(r[1]) for r in _rows(_RKO_COLLECTION_COUNTS, params)})
    return _rows(_RKO_FACTS, params), counts


#: Замечания снимка висят на периоде; периоды РКО тоже несут замечания, но в
#: кластер РС они не входят.
_RS_REMARKS = (
    "select v.unit_dodo_id, u.name, u.country_code, v.text, v.parent_name, v.category, v.amount "
    "from ratings.violations v join ratings.units u on u.dodo_id = v.unit_dodo_id "
    "join ratings.periods p on p.id = v.period_id "
    "where v.category = 'remark' and p.rating_type = 'rs' "
    "and u.country_code = any(%s) and p.end_on >= %s and p.begin_on <= %s "
    "order by v.id"
)
_RS_CHECKUPS = (
    "select u.country_code, sum(s.checkups_count) from ratings.scores s "
    "join ratings.units u on u.dodo_id = s.unit_dodo_id "
    "join ratings.periods p on p.id = s.period_id "
    "where p.rating_type = 'rs' and u.country_code = any(%s) "
    "and p.end_on >= %s and p.begin_on <= %s group by 1"
)


def rs_remark_facts(
    *, countries: Sequence[str], begin: date, end: date
) -> tuple[list[tuple[Any, ...]], dict[str, int]]:
    """Замечания периодов РС, задевающих `[begin, end]` (D396), и сумма проверок по стране."""
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
    """Одна проблема загрузки, свёрнутая по причине и месту (27.10.2026).

    Раньше — строка на строку файла: одна незаведённая пиццерия давала сотни
    одинаковых строк («Подгорица-2» — 221). Теперь — группа: сколько строк
    (`count`), первая из них (`row_no`) и последняя загрузка, где она была.
    """

    import_id: int
    at: datetime
    format: str | None
    row_no: int
    reason: str
    detail: dict[str, Any]
    count: int = 1


#: Группа по причине, месту и формату; «пиццерия не сопоставлена», которую с тех
#: пор завели в справочник (то же имя в той же стране), — уже не проблема.
_OPEN_ISSUES_SQL = """
    select max(i.import_id), max(m.at), m.format, min(i.row_no), i.reason, i.detail, count(*)
      from ratings.import_issues i join ratings.imports m on m.id = i.import_id
     where not (
           i.reason = 'unit_unmatched'
           and exists (
               select 1 from units u
                where lower(u.name) = lower(i.detail->>'unit')
                  and (i.detail->>'country' is null or u.country = i.detail->>'country')
           )
     )
     group by i.reason, i.detail, m.format
     order by max(m.at) desc, i.reason
     limit %s
"""


def open_issues(limit: int = 200) -> tuple[IssueRow, ...]:
    return tuple(IssueRow(*r) for r in _rows(_OPEN_ISSUES_SQL, (limit,)))


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


#: Допустимые тип и способ совпадения правила (CHECK 0039). Коды `src.ratings.model`
#: отсюда не видны — ярус ниже.
_RULE_TYPES = ("rs", "rko")
_RULE_MATCHES = ("text", "contains")


def add_hard_rule(rating_type: str, match: str, pattern: str, *, actor: str) -> None:
    if rating_type not in _RULE_TYPES or match not in _RULE_MATCHES:
        raise RatingsEditError(
            "Тип рейтинга — rs или rko; совпадение — text или contains", REFUSED_RULE_KIND
        )
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


def layout_rows() -> tuple[tuple[str, int, bool], ...]:
    """Компоновка страницы (D368): код блока, место, виден ли."""
    return tuple(
        (str(r[0]), int(r[1]), bool(r[2]))
        for r in _rows("select block, position, visible from ratings.layout")
    )


def save_layout(blocks: Sequence[tuple[str, bool]], *, actor: str) -> None:
    """Записать порядок и видимость одним заходом: половина порядка не ложится."""
    try:
        with connection(check_environment().dsn) as conn, conn.transaction():
            for position, (block, visible) in enumerate(blocks):
                conn.execute(
                    "update ratings.layout set position = %s, visible = %s, "
                    "updated_by = %s, updated_at = now() where block = %s",
                    (position, visible, actor, block),
                )
    except psycopg.Error as exc:
        raise RatingsEditError(
            f"Компоновка не легла: база отказала ({exc.__class__.__name__})", REFUSED_DB
        ) from exc


_UNITS_BY_NAME = (
    "select u.dodo_id, u.name, u.country_code from ratings.units u "
    "where (u.dodo_id = %s or position(%s in u.name_normalized) > 0) "
    "and (%s::text[] is null or u.country_code = any(%s)) "
    "order by u.country_code, u.name, u.dodo_id limit %s"
)


@dataclass(frozen=True)
class UnitRef:
    unit: str
    name: str
    country: str | None


def find_units(
    text: str, *, countries: Sequence[str] | None, normalized: str, limit: int
) -> tuple[UnitRef, ...]:
    """Пиццерии, подходящие под id или часть имени, в охвате `countries` (`None` — все).

    `normalized` — имя в нормализованном виде (как `name_normalized`): сравнение по нему
    не зависит от регистра и пробелов. Охват ставится в самом запросе: чужая пиццерия
    не попадает даже в список кандидатов.
    """
    scope = None if countries is None else list(countries)
    return tuple(
        UnitRef(r[0], r[1], r[2])
        for r in _rows(_UNITS_BY_NAME, (text.strip().lower(), normalized, scope, scope, limit))
    )


@dataclass(frozen=True)
class UnitPeriodRow:
    rating_type: str
    period_id: int
    begin_on: date
    end_on: date
    title_ru: str
    title_en: str
    score: float
    d3: bool
    d3_name: str | None
    critical: bool
    critical_name: str | None
    zeroing: bool
    zeroing_name: str | None
    checkups_count: int | None
    loaded_checkups: int
    accepted_checkups: int
    violations: int
    import_format: str | None
    import_at: datetime
    import_channel: str


_UNIT_PERIODS = (
    "select p.rating_type, p.id, p.begin_on, p.end_on, p.title_ru, p.title_en, s.score::float, "
    "s.d3, s.d3_name, s.critical, s.critical_name, s.zeroing, s.zeroing_name, s.checkups_count, "
    "(select count(*) from ratings.checkups c where c.unit_dodo_id = s.unit_dodo_id "
    " and c.rating_type = p.rating_type "
    " and c.occurred_at::date between p.begin_on and p.end_on), "
    "(select count(*) from ratings.checkups c where c.unit_dodo_id = s.unit_dodo_id "
    " and c.rating_type = p.rating_type and c.acceptance = 'accepted' "
    " and c.occurred_at::date between p.begin_on and p.end_on), "
    "(select count(*) from ratings.violations v where v.unit_dodo_id = s.unit_dodo_id "
    " and v.rating_type = p.rating_type and (v.period_id = p.id or exists ("
    "  select 1 from ratings.checkups c where c.rating_type = v.rating_type "
    "  and c.dodo_id = v.checkup_dodo_id "
    "  and c.occurred_at::date between p.begin_on and p.end_on))), "
    "m.format, m.at, m.channel "
    "from ratings.scores s join ratings.periods p on p.id = s.period_id "
    "join ratings.imports m on m.id = s.import_id "
    "where s.unit_dodo_id = %s and (%s::text is null or p.rating_type = %s) "
    "and p.end_on >= %s and p.begin_on <= %s "
    "order by p.begin_on desc, p.rating_type"
)


def unit_periods(
    unit: str, *, rating_type: str | None, begin: date, end: date
) -> tuple[UnitPeriodRow, ...]:
    """Разбивка пиццерии по периодам рейтинга, пересекающим `begin..end`, новые первыми.

    Проверки и нарушения — только загруженные у нас: `checkups_count` оценки может быть
    больше, чем строк в `ratings.checkups`. Проверка ложится в период по дате проведения.
    Охват здесь не проверяется: `unit` приходит из `find_units`, уже отобранный по охвату.
    """
    return tuple(
        UnitPeriodRow(*r)
        for r in _rows(_UNIT_PERIODS, (unit, rating_type, rating_type, begin, end))
    )
