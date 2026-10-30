"""История в Postgres: охват, импорт, приёмка, снятие, дата обхода и отсутствие лимита."""

from datetime import date

import psycopg
from conftest import requires_db

from src.db.inspection_timeline import months
from src.db.reach import Reach

pytestmark = requires_db


def test_history_is_complete_and_scoped(pg_dsn: str, db_env: str) -> None:
    with psycopg.connect(pg_dsn) as conn:
        conn.execute(
            "insert into units (tenant_code, name, name_normalized, country) "
            "values ('HQ', 'Baku-1', 'baku-1', 'AZ'), ('HQ', 'Belgrade-1', 'belgrade-1', 'RS')"
        )
        # Более лимита list_inspections; все загружены сейчас, обходы — в 2024.
        conn.execute("""
            insert into inspections
              (tenant_code, unit_id, chat_id, kind, inspection_date, report_lang,
               ui_lang, speech_lang, checklist_version, pct, grade, source_fingerprint,
               status, origin, reported_pct, retracted_at, retraction_reason)
            select 'HQ', u.id, 0, 'planned',
                   case when u.country = 'AZ' and g = 3 then '2099-01-01'::date
                        else '2024-01-10'::date end, 'ru', 'ru', 'ru', 'v1',
                   93.5, 'B', u.country || '-' || g,
                   case when u.country = 'AZ' and g = 1 then 'draft' else 'finalized' end,
                   'legacy', 93.5,
                   case when u.country = 'AZ' and g = 2 then now() end,
                   case when u.country = 'AZ' and g = 2 then 'test' end
            from units u cross join generate_series(1, 1001) g
            where u.country in ('AZ', 'RS')
        """)
    today = date(2026, 10, 30)
    hq = Reach("HQ", None, None)
    rows = months(reach=hq, countries=("AZ",), today=today)
    assert len(rows) == 1
    assert rows[0].start == date(2024, 1, 1)
    assert rows[0].count == 998
    assert rows[0].total == 998 * 93.5
    assert months(reach=hq, countries=("RS",), today=today)[0].count == 1001
    assert months(reach=Reach("HQ", None, ("AZ",)), countries=("RS",), today=today) == ()
    assert months(reach=hq, countries=(), today=today) == ()
    assert months(reach=Reach("HQ", (), None), countries=None, today=today) == ()
