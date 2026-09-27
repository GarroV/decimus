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

import threading
from datetime import timedelta

import pytest
from conftest import requires_db

psycopg = pytest.importorskip("psycopg")

from src.db.web_throttle import (  # noqa: E402
    FAILURES_BEFORE_LOCK,
    FORGET_AFTER,
    SCOPE_ADDRESS,
    SCOPE_LOGIN,
    Attempt,
    admit_attempt,
    attempt_transaction,
    canonical_address,
    key_fingerprint,
    load_counter,
    note_success,
)
from src.db.web_throttle import _keys as ключи_попытки  # noqa: E402

pytestmark = requires_db

ТЕНАНТ = "rs"
ЧУЖОЙ = "me"
ЛОГИН = "director"
АДРЕС = "203.0.113.7"
ПОРОГ = FAILURES_BEFORE_LOCK[SCOPE_LOGIN]


def попытка(*, address: str = АДРЕС, login: str = ЛОГИН) -> Attempt:
    """Одна попытка входа так, как её делает форма."""
    return admit_attempt(tenant=ТЕНАНТ, address=address, login=login)


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
        заявка = попытка()
        assert заявка.admitted and not заявка.verdict.locked
    последняя = попытка()
    assert последняя.admitted, "порог сработал на попытку раньше — человека заперли не досчитав"
    assert последняя.verdict.locked, "порог пройден, а запрета нет"
    assert not попытка().admitted, "запертую попытку понесли к сверке пароля"


def test_удачный_вход_забывает_обе_строки(db_env: str) -> None:
    попытка()
    note_success(tenant=ТЕНАНТ, address=АДРЕС, login=ЛОГИН)
    строка = load_counter(tenant=ТЕНАНТ, scope=SCOPE_LOGIN, fingerprint=key_fingerprint(ЛОГИН))
    assert строка is None


def test_счётчик_соседнего_тенанта_не_запирается(db_env: str) -> None:
    """Границу арендаторов ограничитель не ослабляет и не переносит."""
    for _ in range(ПОРОГ + 1):
        admit_attempt(tenant=ЧУЖОЙ, address=АДРЕС, login=ЛОГИН)
    assert попытка().admitted, "перебор у соседнего арендатора запер вход в этом"


def test_после_забвения_счёт_начинается_заново(db_env: str, pg_dsn: str) -> None:
    """Иначе одна давняя опечатка складывалась бы с сегодняшней вечно."""
    for _ in range(ПОРОГ - 1):
        попытка()
    отмотать(pg_dsn, FORGET_AFTER + timedelta(minutes=1))
    assert попытка().verdict.retry_after == timedelta(0)


def test_старые_строки_убираются_попутно(db_env: str, pg_dsn: str) -> None:
    """Таблица растёт от того, что в неё пишет посторонний, и обязана усыхать сама."""
    admit_attempt(tenant=ТЕНАНТ, address=АДРЕС, login="кто-то-давний")
    отмотать(pg_dsn, FORGET_AFTER + timedelta(minutes=1))
    попытка()
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "select count(*) from web_login_attempts where key_fingerprint = %s",
            (key_fingerprint("кто-то-давний"),),
        )
        row = cur.fetchone()
    assert row is not None and row[0] == 0


def test_попутная_чистка_не_трогает_чужого_арендатора(db_env: str, pg_dsn: str) -> None:
    """Давние строки соседа убирает его собственный вход, а не наш (T331)."""
    admit_attempt(tenant=ЧУЖОЙ, address=АДРЕС, login="соседский")
    отмотать(pg_dsn, FORGET_AFTER + timedelta(minutes=1))
    попытка()
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "select count(*) from web_login_attempts"
            " where tenant_code = %s and key_fingerprint = %s",
            (ЧУЖОЙ, key_fingerprint("соседский")),
        )
        row = cur.fetchone()
    assert row is not None and row[0] == 1, "чистка одного арендатора сняла счётчик другого"


def test_встречные_попытки_по_давним_ключам_не_запирают_друг_друга(
    db_env: str, pg_dsn: str
) -> None:
    """Попутная чистка не ждёт строк, которые держит чужая попытка (T331, #300).

    Два человека возвращаются после перерыва: у обоих строки счётчика давние.
    Каждая попытка сначала записывает СВОЮ строку (та перестаёт быть давней, но
    запись ещё не видна соседу), а потом чистит давние — и видит давней чужую.
    Чистка без `skip locked` встаёт ждать соседа, сосед — её: взаимная
    блокировка, и один из двоих получает 500 на форме входа.

    Барьер стоит ровно между записью и чисткой: тело `with` и есть этот
    промежуток. Без барьера порядок случаен и тест зеленеет на сломанном коде.
    """
    for логин in ("первый", "второй"):
        admit_attempt(tenant=ТЕНАНТ, address=АДРЕС, login=логин)
    отмотать(pg_dsn, FORGET_AFTER + timedelta(minutes=1))

    записали = threading.Barrier(2)
    ошибки: list[BaseException] = []

    def войти(логин: str) -> None:
        try:
            with attempt_transaction(
                tenant=ТЕНАНТ, keys=ключи_попытки(АДРЕС + логин, логин)
            ) as rows:
                rows.bump(scope=SCOPE_LOGIN, fingerprint=key_fingerprint(логин))
                записали.wait(timeout=30)
        except BaseException as exc:  # поток иначе падает молча
            ошибки.append(exc)

    нити = [threading.Thread(target=войти, args=(л,)) for л in ("первый", "второй")]
    for нить in нити:
        нить.start()
    for нить in нити:
        нить.join(timeout=60)

    assert not any(нить.is_alive() for нить in нити), "попытки повисли друг на друге"
    assert not ошибки, f"встречные попытки заперли друг друга: {ошибки[0]!r}"


# --- в базу не уезжает ничего лишнего ---------------------------------------


def test_введённого_человеком_в_таблице_нет(db_env: str, pg_dsn: str) -> None:
    """В поле «логин» вводят и пароль от соседней системы — дословно он не хранится."""
    admit_attempt(tenant=ТЕНАНТ, address=АДРЕС, login="пароль-от-соседней-системы")
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
    попытка()
    with psycopg.connect(db_env) as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute(
                "update web_login_attempts set key_fingerprint = %s",
                (key_fingerprint("кто-то-другой"),),
            )


# --- порог держит и при одновременных попытках -------------------------------


def test_одновременные_попытки_не_проходят_мимо_порога(db_env: str) -> None:
    """Обещание «после пятой — сразу отказ» обязано держать и при залпе.

    До T328 «спросить» и «записать» были двумя походами в базу, а между ними
    стояла сверка пароля — самая долгая часть запроса. Попытки, пришедшие до
    записи первой неудачи, читали одно и то же число и проходили заслон все
    разом: мимо порога проезжало «порог + число потоков − 1» попыток.

    Циклом `for` это не ловится в принципе: в нём попытки идут ПОДРЯД, и каждая
    видит запись предыдущей. Поэтому здесь настоящие потоки и общий старт по
    барьеру — иначе проверка зелена и на сломанном ограничителе.
    """
    потоков = ПОРОГ * 3
    на_старте = threading.Barrier(потоков)
    допущено: list[bool] = []
    ошибки: list[BaseException] = []

    def гонец() -> None:
        try:
            на_старте.wait(timeout=30)
            допущено.append(попытка().admitted)
        except BaseException as exc:  # поток иначе падает молча, и счёт врёт
            ошибки.append(exc)

    нити = [threading.Thread(target=гонец) for _ in range(потоков)]
    for нить in нити:
        нить.start()
    for нить in нити:
        нить.join(timeout=60)

    assert not ошибки, f"попытки падали, а не отказывались: {ошибки[0]!r}"
    assert len(допущено) == потоков, "не все потоки дошли до конца — считать нечего"
    assert sum(допущено) == ПОРОГ, (
        f"к сверке пароля пустили {sum(допущено)} попыток вместо {ПОРОГ}: "
        f"параллельные попытки прошли мимо порога"
    )


# --- адрес приводится к канону до отпечатка ----------------------------------


def test_один_адрес_записанный_по_разному_даёт_один_счётчик(db_env: str) -> None:
    """Иначе порог по адресу обходится записью того же адреса в другом виде."""
    admit_attempt(tenant=ТЕНАНТ, address="2001:db8::1", login=ЛОГИН)
    admit_attempt(tenant=ТЕНАНТ, address="2001:db8:0:0:0:0:0:1", login=ЛОГИН)
    строка = load_counter(
        tenant=ТЕНАНТ,
        scope=SCOPE_ADDRESS,
        fingerprint=key_fingerprint(canonical_address("2001:db8::1")),
    )
    assert строка is not None and строка.failures == 2, (
        "две попытки с одного адреса легли в разные счётчики — порог по адресу обходится"
    )
