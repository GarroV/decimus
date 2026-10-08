"""Схема `ratings` (спека «Рейтинги», D321, D327): что держит база, а не код.

Роль приложения пишет рейтинги; тот же файл дважды «загруженным» не ложится;
замечание периода без периода и дробное «число периодов» — отказ схемы.
"""

from __future__ import annotations

import pytest
from conftest import requires_db

psycopg = pytest.importorskip("psycopg")

pytestmark = requires_db

SHA = "a" * 64
UNIT = "aa000000000000000000000000000001"


def _журнал(cur: psycopg.Cursor, *, outcome: str = "loaded", sha: str = SHA) -> int:
    cur.execute(
        "insert into ratings.imports (actor, channel, format, sha256, outcome, note) "
        "values ('test', 'web', 'rs-checkups', %s, %s, %s) returning id",
        (sha, outcome, "тест" if outcome == "failed" else None),
    )
    строка = cur.fetchone()
    assert строка is not None
    return int(строка[0])


def test_роль_приложения_пишет_рейтинг(db_env: str) -> None:
    with psycopg.connect(db_env) as conn, conn.cursor() as cur:
        загрузка = _журнал(cur)
        cur.execute(
            "insert into ratings.countries (code, name_ru, name_en) "
            "values ('RS', 'Сербия', 'Serbia')"
        )
        cur.execute(
            "insert into ratings.units (dodo_id, name, name_normalized, country_code) "
            "values (%s, 'Beograd-1', 'beograd-1', 'RS')",
            (UNIT,),
        )
        cur.execute(
            "insert into ratings.periods (rating_type, begin_on, end_on, title_ru, title_en) "
            "values ('rs', '2026-09-16', '2026-09-30', 'Сентябрь 2 часть 2026', "
            "'September part 2 2026') "
            "returning id"
        )
        период = cur.fetchone()
        assert период is not None
        cur.execute(
            "insert into ratings.scores (unit_dodo_id, period_id, score, source, import_id) "
            "values (%s, %s, 97.5, 'snapshot', %s)",
            (UNIT, период[0], загрузка),
        )
        cur.execute("select score from ratings.scores")
        assert cur.fetchone() == (pytest.approx(97.5),)


def test_тот_же_sha_дважды_загруженным_не_ложится(db_env: str) -> None:
    with psycopg.connect(db_env) as conn, conn.cursor() as cur:
        _журнал(cur)
        _журнал(cur, outcome="failed")  # failed с тем же sha индекс не ограничивает
        with pytest.raises(psycopg.errors.UniqueViolation):
            _журнал(cur)


def test_замечание_без_периода_отказ(db_env: str) -> None:
    with psycopg.connect(db_env) as conn, conn.cursor() as cur:
        загрузка = _журнал(cur)
        cur.execute(
            "insert into ratings.units (dodo_id, name, name_normalized) values (%s, 'X-1', 'x-1')",
            (UNIT,),
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute(
                "insert into ratings.violations "
                "(row_key, rating_type, unit_dodo_id, text, category, import_id) "
                "values ('k', 'rs', %s, 'D3 что-то', 'remark', %s)",
                (UNIT, загрузка),
            )


def test_замечание_журнала_developer_conflict_ложится(db_env: str) -> None:
    with psycopg.connect(db_env) as conn, conn.cursor() as cur:
        загрузка = _журнал(cur)
        cur.execute(
            "insert into ratings.import_issues (import_id, row_no, reason, detail) "
            "values (%s, 3, 'developer_conflict', '{\"country\": \"RS\"}')",
            (загрузка,),
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute(
                "insert into ratings.import_issues (import_id, row_no, reason) "
                "values (%s, 4, 'выдуманная_причина')",
                (загрузка,),
            )


def test_число_периодов_зоны_риска_целое(db_env: str) -> None:
    with psycopg.connect(db_env) as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute("update ratings.settings set value = 2.5 where key = 'risk_periods'")


def test_стартовые_пороги_и_хард_правила_на_месте(db_env: str) -> None:
    with psycopg.connect(db_env) as conn, conn.cursor() as cur:
        cur.execute("select key, value from ratings.settings order by key")
        assert [(k, float(v)) for k, v in cur.fetchall()] == [
            ("risk_periods", 3.0),
            ("risk_threshold", 85.0),
            ("top_threshold", 85.0),
        ]
        cur.execute("select count(*) from ratings.hard_rules where rating_type = 'rko'")
        assert cur.fetchone() == (6,)


def test_журнал_загрузок_роль_приложения_правит_только_счётчики(db_env: str) -> None:
    with psycopg.connect(db_env, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("begin")
        загрузка = _журнал(cur)
        cur.execute("update ratings.imports set accepted = 5 where id = %s", (загрузка,))
        cur.execute("rollback")
    for sql in (
        "delete from ratings.imports",
        "update ratings.imports set actor = 'другой'",
        "update ratings.imports set outcome = 'failed'",
        "update ratings.imports set sha256 = repeat('b', 64)",
    ):
        with psycopg.connect(db_env) as conn, conn.cursor() as cur:
            _журнал(cur)
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cur.execute(sql)
