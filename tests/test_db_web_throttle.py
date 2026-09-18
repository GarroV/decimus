"""T325: счётчик неудачных входов на уровне базы (`src/db/web_throttle.py`).

Правило проверяется арифметикой (`tests/test_web_throttle.py`), а форма входа —
отправками (`tests/test_web_login_limit.py`). Здесь остаётся то, что не
проверяется ни тем ни другим и при этом молчит: складываются ли неудачи в
настоящей таблице, хватает ли роли приложения прав на её работу и не хватает ли
ей лишних, не уезжает ли в базу дословно введённое человеком.

«В миграции написано» и «база так делает» — разные утверждения, и расходятся
они молча. Поэтому заслоны здесь проверяются запуском.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from conftest import requires_db

psycopg = pytest.importorskip("psycopg")

from src.db.web_throttle import (  # noqa: E402
    FAILURES_BEFORE_LOCK,
    FORGET_AFTER,
    SCOPE_LOGIN,
    check_attempt,
    key_fingerprint,
    load_counter,
    note_failure,
    note_success,
)

pytestmark = requires_db

ТЕНАНТ = "rs"
ЧУЖОЙ = "me"
ЛОГИН = "director"
АДРЕС = "203.0.113.7"
ПОРОГ = FAILURES_BEFORE_LOCK[SCOPE_LOGIN]


def отмотать(dsn: str, назад: timedelta) -> None:
    """«Прошло столько времени»: сдвинуть все строки счётчика в прошлое.

    Владельцем схемы, а не ролью приложения: у той нет права править время
    чужой строки задним числом, и это ровно то, что проверяет соседний тест.
    """
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("update web_login_attempts set updated_at = updated_at - %s", (назад,))


# --- неудачи складываются в настоящей таблице -------------------------------


def test_неудачи_складываются_и_запирают(db_env: str) -> None:
    for _ in range(ПОРОГ - 1):
        note_failure(tenant=ТЕНАНТ, address=АДРЕС, login=ЛОГИН)
    assert not check_attempt(tenant=ТЕНАНТ, address=АДРЕС, login=ЛОГИН).locked
    assert note_failure(tenant=ТЕНАНТ, address=АДРЕС, login=ЛОГИН).locked
    assert check_attempt(tenant=ТЕНАНТ, address=АДРЕС, login=ЛОГИН).locked


def test_удачный_вход_забывает_обе_строки(db_env: str) -> None:
    note_failure(tenant=ТЕНАНТ, address=АДРЕС, login=ЛОГИН)
    note_success(tenant=ТЕНАНТ, address=АДРЕС, login=ЛОГИН)
    строка = load_counter(tenant=ТЕНАНТ, scope=SCOPE_LOGIN, fingerprint=key_fingerprint(ЛОГИН))
    assert строка is None


def test_счётчик_соседнего_тенанта_не_запирается(db_env: str) -> None:
    """Границу арендаторов ограничитель не ослабляет и не переносит."""
    for _ in range(ПОРОГ):
        note_failure(tenant=ЧУЖОЙ, address=АДРЕС, login=ЛОГИН)
    assert not check_attempt(tenant=ТЕНАНТ, address=АДРЕС, login=ЛОГИН).locked


def test_после_забвения_счёт_начинается_заново(db_env: str, pg_dsn: str) -> None:
    """Иначе одна давняя опечатка складывалась бы с сегодняшней вечно."""
    for _ in range(ПОРОГ - 1):
        note_failure(tenant=ТЕНАНТ, address=АДРЕС, login=ЛОГИН)
    отмотать(pg_dsn, FORGET_AFTER + timedelta(minutes=1))
    assert note_failure(tenant=ТЕНАНТ, address=АДРЕС, login=ЛОГИН).retry_after == timedelta(0)


def test_старые_строки_убираются_попутно(db_env: str, pg_dsn: str) -> None:
    """Таблица растёт от того, что в неё пишет посторонний, и обязана усыхать сама."""
    note_failure(tenant=ТЕНАНТ, address=АДРЕС, login="кто-то-давний")
    отмотать(pg_dsn, FORGET_AFTER + timedelta(minutes=1))
    note_failure(tenant=ТЕНАНТ, address=АДРЕС, login=ЛОГИН)
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "select count(*) from web_login_attempts where key_fingerprint = %s",
            (key_fingerprint("кто-то-давний"),),
        )
        row = cur.fetchone()
    assert row is not None and row[0] == 0


# --- в базу не уезжает ничего лишнего ---------------------------------------


def test_введённого_человеком_в_таблице_нет(db_env: str, pg_dsn: str) -> None:
    """В поле «логин» вводят и пароль от соседней системы — дословно он не хранится."""
    note_failure(tenant=ТЕНАНТ, address=АДРЕС, login="пароль-от-соседней-системы")
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute("select key_fingerprint::text from web_login_attempts")
        всё = " ".join(str(строка[0]) for строка in cur.fetchall())
    assert "пароль-от-соседней-системы" not in всё
    assert АДРЕС not in всё


def test_схема_не_принимает_ключ_вместо_отпечатка(db_env: str, pg_dsn: str) -> None:
    """Ограничение схемы, а не договорённость в коде."""
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute(
                "insert into web_login_attempts (tenant_code, scope, key_fingerprint, failures) "
                "values (%s, 'login', %s, 1)",
                (ТЕНАНТ, ЛОГИН),
            )


def test_схема_не_знает_третьего_вида_счётчика(db_env: str, pg_dsn: str) -> None:
    """Опечатка в `scope` иначе завела бы счётчик, который никто не читает."""
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute(
                "insert into web_login_attempts (tenant_code, scope, key_fingerprint, failures) "
                "values (%s, 'адрес', %s, 1)",
                (ТЕНАНТ, key_fingerprint(АДРЕС)),
            )


# --- права роли приложения: хватает на работу, не хватает на подмену --------


def test_роль_приложения_не_переставляет_накопленные_неудачи(db_env: str) -> None:
    """Иначе запрет снимается с себя и вешается на чужой логин одним запросом."""
    note_failure(tenant=ТЕНАНТ, address=АДРЕС, login=ЛОГИН)
    with psycopg.connect(db_env) as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute(
                "update web_login_attempts set key_fingerprint = %s",
                (key_fingerprint("кто-то-другой"),),
            )
