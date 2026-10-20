"""Схема `learning` и её двери в настоящей базе (D574, D575, #906).

Главное, что держит этот набор: **в базе нет данных о сотрудниках** — колонки схемы
перечислены, и любая новая нечисловая (кроме названий подразделений и курсов) краснит
прогон. Остальное — запись и чтение снимка настоящей ролью приложения.
"""

from __future__ import annotations

from datetime import date

import pytest
from conftest import requires_db

psycopg = pytest.importorskip("psycopg")

from src.db import learning_store, training_read  # noqa: E402
from src.domain.training_metrics import COLUMNS, Counters  # noqa: E402

pytestmark = requires_db

DAY = date(2026, 10, 20)
UNIT = "aa000000000000000000000000000001"

#: Текстовые колонки схемы целиком: всё остальное — числа, даты и время. Новая колонка здесь —
#: решение о том, что в базе можно хранить текст; про человека её быть не может (D575).
TEXT_COLUMNS = {
    "departments": {"ispring_id", "title", "kind", "country_code", "parent_id", "unit_dodo_id"},
    "courses": {"course_id", "title"},
    "unit_totals": {"department_id"},
    "unit_courses": {"department_id", "course_id"},
    "loads": {"outcome", "error"},
}
PERSON_WORDS = ("user", "email", "name", "staff", "person", "employee", "login", "phone")


def _c(assigned: int, completed: int) -> Counters:
    return Counters(assigned=assigned, completed=completed, people_total=5, people_trained=2)


@pytest.fixture
def seeded(db_env: str) -> str:
    with psycopg.connect(db_env) as conn, conn.cursor() as cur:
        cur.execute(
            "insert into ratings.countries (code, name_ru, name_en) "
            "values ('RO', 'Румыния', 'Romania')"
        )
        cur.execute(
            "insert into ratings.units (dodo_id, name, name_normalized, country_code) "
            "values (%s, 'Brasov-1', 'brasov-1', 'RO')",
            (UNIT,),
        )
    return db_env


def _save(day: date = DAY, *, assigned: int = 100) -> None:
    learning_store.save_snapshot(
        day,
        [
            ("d-ro", "Dodo Pizza - Romania", "country", "RO", None, None),
            ("d-1", "Brasov-1", "pizzeria", "RO", "d-ro", UNIT),
            ("d-2", "Iasi-1", "pizzeria", "RO", "d-ro", None),
        ],
        {"d-1": _c(assigned, 40), "d-2": _c(10, 1)},
        {
            ("d-1", "k1"): Counters(assigned=assigned, completed=40),
            ("d-2", "k1"): Counters(assigned=10, completed=1),
        },
        {"k1": "Кассир"},
    )


def test_в_схеме_нет_колонок_про_людей(db_env: str) -> None:
    with psycopg.connect(db_env) as conn, conn.cursor() as cur:
        cur.execute(
            "select table_name, column_name, data_type from information_schema.columns "
            "where table_schema = 'learning'"
        )
        columns = cur.fetchall()
    assert columns
    for table, column, data_type in columns:
        assert not any(word in column for word in PERSON_WORDS), f"{table}.{column}"
        if data_type == "text":
            assert column in TEXT_COLUMNS[table], f"неожиданная текстовая колонка {table}.{column}"
        else:
            assert data_type in {
                "integer", "bigint", "double precision", "date", "timestamp with time zone"
            }, f"{table}.{column}: {data_type}"  # fmt: skip


def test_колонки_счётчиков_совпадают_со_столбцами_таблицы(db_env: str) -> None:
    with psycopg.connect(db_env) as conn, conn.cursor() as cur:
        cur.execute(
            "select column_name from information_schema.columns "
            "where table_schema = 'learning' and table_name = 'unit_totals'"
        )
        stored = {r[0] for r in cur.fetchall()} - {"sync_date", "department_id"}
    assert stored == set(COLUMNS)


def test_снимок_ложится_и_читается_ролью_приложения(seeded: str) -> None:
    _save()
    assert training_read.snapshot_date() == DAY
    units = {u.department_id: u for u in training_read.unit_totals(DAY, None)}
    assert set(units) == {"d-1", "d-2"}  # страна — не пиццерия
    assert units["d-1"].matched and not units["d-2"].matched
    assert (units["d-1"].counters.assigned, units["d-1"].counters.completed) == (100, 40)
    assert units["d-1"].counters.people_trained == 2


def test_охват_стран_ограничивает_чтение(seeded: str) -> None:
    _save()
    assert training_read.unit_totals(DAY, ["AM"]) == ()
    assert len(training_read.unit_totals(DAY, ["RO"])) == 2
    assert training_read.unit_totals(DAY, []) == ()


def test_курсы_суммируются_по_сопоставленным_и_по_одной_пиццерии(seeded: str) -> None:
    _save()
    network = training_read.course_totals(DAY, None)
    assert [(k.title, k.counters.assigned) for k in network] == [("Кассир", 100)]  # без Iasi-1
    one = training_read.course_totals(DAY, None, department="d-2")
    assert one[0].counters.assigned == 10  # выбранную несопоставленную читаем по подразделению
    assert training_read.course_totals(DAY, ["AM"]) == ()


def test_повторная_загрузка_того_же_дня_заменяет_снимок(seeded: str) -> None:
    _save(assigned=100)
    _save(assigned=120)
    units = {u.department_id: u for u in training_read.unit_totals(DAY, None)}
    assert units["d-1"].counters.assigned == 120
    assert len(training_read.course_totals(DAY, None)) == 1


def test_читается_последний_снимок(seeded: str) -> None:
    _save(date(2026, 10, 19))
    _save(DAY)
    assert training_read.snapshot_date() == DAY


def test_журнал_загрузок(seeded: str) -> None:
    assert learning_store.last_ok_load() is None
    learning_store.log_load(ok=False, error="iSpring ответил 500 на /learners/results")
    assert learning_store.last_ok_load() is None
    learning_store.log_load(ok=True, departments=10, results=100)
    assert learning_store.last_ok_load() is not None


def test_пиццерии_рейтингов_читаются_для_сопоставления(seeded: str) -> None:
    assert learning_store.known_units() == [(UNIT, "Brasov-1", "RO")]


def test_схема_отказывает_неправдоподобным_числам(seeded: str) -> None:
    with psycopg.connect(seeded) as conn, conn.cursor() as cur:
        cur.execute(
            "insert into learning.departments (ispring_id, title, kind) "
            "values ('x', 'X', 'pizzeria')"
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute(
                "insert into learning.unit_totals (sync_date, department_id, assigned, completed, "
                "in_progress, not_started, failed, passed, overdue, people_total, people_trained, "
                "time_sum, time_n, score_sum, score_n, days_sum, days_n) "
                "values (%s, 'x', 5, 9, 0, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0, 0, 0)",
                (DAY,),
            )
