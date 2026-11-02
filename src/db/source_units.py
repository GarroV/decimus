"""Официальный реестр для чтения метрик: первичен справочник рейтингов (#1391)."""

from __future__ import annotations

# Both source tables enforce lowercase 32-hex UUIDs. Resolve identity before any
# country filter: an official public-registry fallback never overrides a primary row.
_CTE = (
    "source_units as ("
    "select lower(replace(dodo_id,'-','')) dodo_id,country_code,name from ratings.units "
    "union all select lower(replace(a.dodo_id,'-','')),a.country_code,a.name from agg.units a "
    "where exists(select 1 from ratings.countries c where c.code=a.country_code) "
    "and not exists(select 1 from ratings.units r "
    "where lower(replace(r.dodo_id,'-',''))=lower(replace(a.dodo_id,'-',''))))"
)


def with_registry(sql: str) -> str:
    """Одно разрешение реестра в SQL; существующий WITH сохраняется."""
    return "with " + _CTE + ("," + sql[5:] if sql.startswith("with ") else " " + sql)
