"""Журналы входов и действий (D462, миграция `0067`) — уровень базы.

Ядро доступа: кому чьи записи видны. Ошибка здесь тихая — человек видит чужие входы
или не главный админ читает журнал действий. Всё идёт под ролью приложения
(`db_env`), как на площадке: читать можно только функциями, прав на таблицы нет.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from conftest import requires_db
from db_harness import завести_пространства

psycopg = pytest.importorskip("psycopg")

from src.db import journals  # noqa: E402
from src.db.web_access import (  # noqa: E402
    authenticate,
    create_account,
    freeze_account,
    open_session,
    resolve_session,
)
from src.domain.journal import (  # noqa: E402
    METHOD_BOT_LINK,
    METHOD_GOOGLE,
    METHOD_PASSWORD,
    RESULT_BAD_PASSWORD,
    RESULT_FROZEN,
    RESULT_OK,
    RESULT_RATE_LIMITED,
    RESULT_UNKNOWN,
)

pytestmark = requires_db

ПАРОЛЬ = "пароль-учётки-теста-d462-журналы"


class Люди:
    """Три человека: главный админ, админ и девелопер; у каждого живая сессия."""

    def __init__(self) -> None:
        self.токены: dict[str, str] = {}
        self.ид: dict[str, str] = {}

    def завести(self, логин: str, роль: str) -> None:
        create_account(логин, tenant="HQ", password=ПАРОЛЬ, role=роль)
        учётка = authenticate(логин, ПАРОЛЬ)
        assert учётка is not None
        self.ид[логин] = учётка.id
        self.токены[логин] = open_session(
            учётка, ip=f"198.51.100.{len(self.ид)}", user_agent="Mozilla/5.0 test"
        ).token


@pytest.fixture
def люди(pg_dsn: str, db_env: str, monkeypatch: pytest.MonkeyPatch) -> Люди:
    monkeypatch.setenv("DATABASE_ADMIN_URL", pg_dsn)
    завести_пространства(pg_dsn, "HQ")
    группа = Люди()
    группа.завести("sofia", "superadmin")
    группа.завести("anna", "admin")
    группа.завести("dev", "developer")
    return группа


def _вход(кто: Люди, логин: str, **kw: object) -> None:
    journals.record_login(
        method=METHOD_PASSWORD,
        result=RESULT_OK,
        user_id=кто.ид[логин],
        ip="203.0.113.7",
        user_agent="UA",
        **kw,  # type: ignore[arg-type]
    )


def _действие(кто: Люди, логин: str, действие: str = "freeze_person") -> None:
    journals.record_action(
        user_id=кто.ид[логин],
        role="admin",
        tenant="HQ",
        action=действие,
        target="login=x",
        outcome="302",
        ip="203.0.113.7",
        credential="s1",
    )


# --- журнал входов: кому чьи записи ----------------------------------------


def test_человек_видит_в_журнале_входов_только_свои(люди: Люди) -> None:
    _вход(люди, "anna")
    _вход(люди, "dev")

    видно = journals.read_logins(люди.токены["dev"])

    assert {e.login for e in видно} == {"dev"}


def test_фильтр_по_чужому_человеку_не_расширяет_права(люди: Люди) -> None:
    _вход(люди, "anna")
    _вход(люди, "dev")

    видно = journals.read_logins(люди.токены["dev"], person=люди.ид["anna"])

    assert видно == (), "обычный человек увидел вход другого, назвав его в фильтре"


def test_главный_админ_видит_входы_всех_и_фильтрует_по_человеку(люди: Люди) -> None:
    _вход(люди, "anna")
    _вход(люди, "dev")

    все = journals.read_logins(люди.токены["sofia"])
    одного = journals.read_logins(люди.токены["sofia"], person=люди.ид["anna"])

    assert {e.login for e in все} >= {"anna", "dev"}
    assert {e.login for e in одного} == {"anna"}


def test_админ_не_видит_входов_других(люди: Люди) -> None:
    _вход(люди, "dev")

    assert journals.read_logins(люди.токены["anna"]) == ()


def test_без_живой_сессии_журнал_пуст(люди: Люди) -> None:
    _вход(люди, "anna")

    assert journals.read_logins("не-токен-сессии") == ()
    freeze_account("anna", tenant="HQ")
    assert journals.read_logins(люди.токены["anna"]) == ()


def test_вход_с_неизвестным_логином_виден_только_главному_админу(люди: Люди) -> None:
    journals.record_failed_login(
        login="nobody", method=METHOD_PASSWORD, ip="10.1.2.3", user_agent=""
    )

    assert [e.result for e in journals.read_logins(люди.токены["sofia"])] == [RESULT_UNKNOWN]
    assert journals.read_logins(люди.токены["dev"]) == ()


def test_исход_неудачи_различает_пароль_и_заморозку(люди: Люди) -> None:
    journals.record_failed_login(login="dev", method=METHOD_PASSWORD, ip=None, user_agent=None)
    freeze_account("dev", tenant="HQ")
    journals.record_failed_login(login="DEV", method=METHOD_PASSWORD, ip=None, user_agent=None)

    исходы = [e.result for e in journals.read_logins(люди.токены["sofia"])]

    assert исходы == [RESULT_FROZEN, RESULT_BAD_PASSWORD]


def test_запись_входа_несёт_адрес_браузер_способ_и_сессию(люди: Люди) -> None:
    учётка = authenticate("dev", ПАРОЛЬ)
    assert учётка is not None
    сессия = open_session(учётка, ip="203.0.113.9", user_agent="Я" * 500)
    journals.record_login(
        method=METHOD_GOOGLE,
        result=RESULT_OK,
        user_id=учётка.id,
        ip="203.0.113.9",
        user_agent="Я" * 500,
        session_id=сессия.session_id,
    )

    (запись,) = journals.read_logins(люди.токены["dev"])

    assert (запись.method, запись.result, запись.ip) == (METHOD_GOOGLE, RESULT_OK, "203.0.113.9")
    assert запись.session_id == сессия.session_id
    assert запись.user_agent is not None and len(запись.user_agent) == 200


def test_сессия_хранит_адрес_и_браузер(люди: Люди, pg_dsn: str) -> None:
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "select ip, user_agent from web_sessions where user_id = %s", (люди.ид["anna"],)
        )
        assert cur.fetchone() == ("198.51.100.2", "Mozilla/5.0 test")
    assert resolve_session(люди.токены["anna"]) is not None


def test_бот_ссылка_пишется_без_адреса(люди: Люди) -> None:
    journals.record_login(method=METHOD_BOT_LINK, result=RESULT_OK, user_id=люди.ид["dev"])

    (запись,) = journals.read_logins(люди.токены["dev"])

    assert (запись.method, запись.ip) == (METHOD_BOT_LINK, None)


def test_период_включает_начало_и_не_включает_конец(люди: Люди, pg_dsn: str) -> None:
    _вход(люди, "dev")
    с_датой = datetime(2026, 1, 15, 12, tzinfo=timezone.utc)
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute("update login_journal set occurred_at = %s", (с_датой,))
    токен = люди.токены["dev"]

    assert len(journals.read_logins(токен, start=с_датой, end=с_датой + timedelta(days=1))) == 1
    assert journals.read_logins(токен, start=с_датой + timedelta(days=1)) == ()
    assert journals.read_logins(токен, end=с_датой) == ()


# --- журнал действий: только главный админ ---------------------------------


def test_журнал_действий_читает_только_главный_админ(люди: Люди) -> None:
    _действие(люди, "anna")

    assert [e.action for e in journals.read_actions(люди.токены["sofia"])] == ["freeze_person"]
    assert journals.read_actions(люди.токены["anna"]) == (), "админ прочитал журнал действий"
    assert journals.read_actions(люди.токены["dev"]) == ()
    assert journals.read_actions("не-токен") == ()


def test_журнал_действий_фильтруется_по_человеку_и_периоду(люди: Люди) -> None:
    _действие(люди, "anna", "a")
    _действие(люди, "sofia", "b")

    токен = люди.токены["sofia"]
    assert [e.action for e in journals.read_actions(токен, person=люди.ид["anna"])] == ["a"]
    будущее = datetime.now(timezone.utc) + timedelta(days=1)
    assert journals.read_actions(токен, start=будущее) == ()


def test_люди_для_фильтра_видны_только_главному_админу(люди: Люди) -> None:
    assert {л for _, л, _имя in journals.journal_people(люди.токены["sofia"])} >= {"sofia", "anna"}
    assert journals.journal_people(люди.токены["anna"]) == ()


def test_имя_из_google_приходит_с_записями_и_в_списке_людей(люди: Люди, pg_dsn: str) -> None:
    with psycopg.connect(pg_dsn, autocommit=True) as conn:
        conn.execute(
            "update web_users set display_name = 'Анна Админова' where id = %s",
            (люди.ид["anna"],),
        )
    _вход(люди, "anna")
    _вход(люди, "dev")
    _действие(люди, "anna")

    входы = {e.login: e.name for e in journals.read_logins(люди.токены["sofia"])}
    действия = journals.read_actions(люди.токены["sofia"])
    человек = {л: имя for _, л, имя in journals.journal_people(люди.токены["sofia"])}

    assert входы["anna"] == "Анна Админова" and входы["dev"] is None
    assert {e.name for e in действия} == {"Анна Админова"}
    assert человек["anna"] == "Анна Админова" and человек["dev"] is None


# --- права и срок хранения -------------------------------------------------


def test_роль_приложения_не_читает_и_не_правит_таблицы_напрямую(люди: Люди, db_env: str) -> None:
    _вход(люди, "anna")
    _действие(люди, "anna")
    from src.db.config import check_environment

    with psycopg.connect(check_environment().dsn) as conn, conn.cursor() as cur:
        # Оба журнала — одной матрицей (сверка 16.10.2026): защита одного не должна
        # молча отсутствовать у соседа, заведённого той же миграцией `0067`.
        for sql in (
            *(
                f"{действие} {таблица}"
                for таблица in ("login_journal", "action_journal")
                for действие in ("select * from", "delete from", "truncate")
            ),
            "update login_journal set result = 'ok'",
            "update action_journal set outcome = 'ok'",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cur.execute(sql)
            conn.rollback()


def test_уборка_убирает_входы_старше_180_и_действия_старше_365_дней(
    люди: Люди, pg_dsn: str
) -> None:
    _вход(люди, "anna")
    _вход(люди, "anna")
    _действие(люди, "anna")
    _действие(люди, "anna")
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "update login_journal set occurred_at = now() - interval '181 days' "
            "where id = (select min(id) from login_journal)"
        )
        cur.execute(
            "update action_journal set occurred_at = now() - interval '366 days' "
            "where id = (select min(id) from action_journal)"
        )
        # Рядом со сроком: 179 и 364 дня остаются.
        cur.execute(
            "update login_journal set occurred_at = now() - interval '179 days' "
            "where id = (select max(id) from login_journal)"
        )
        cur.execute(
            "update action_journal set occurred_at = now() - interval '364 days' "
            "where id = (select max(id) from action_journal)"
        )

    убрано = journals.purge()

    assert убрано == 2
    assert len(journals.read_logins(люди.токены["sofia"])) == 1
    assert len(journals.read_actions(люди.токены["sofia"])) == 1


def test_отказы_по_частоте_с_одного_адреса_схлопываются_в_одну_строку(люди: Люди) -> None:
    """Запертый адрес не раздувает журнал: строка на адрес, способ и учётку за 10 минут."""
    for _ in range(50):
        journals.record_failed_login(
            login="anna", method=METHOD_PASSWORD, ip="10.8.8.8", user_agent="UA",
            result=RESULT_RATE_LIMITED,
        )  # fmt: skip
    for n in range(50):  # перебор логинов с одного адреса: учётки нет, строка одна
        journals.record_failed_login(
            login=f"нет-такого-{n}", method=METHOD_PASSWORD, ip="10.8.8.9", user_agent="UA",
            result=RESULT_RATE_LIMITED,
        )  # fmt: skip
    journals.record_failed_login(  # другой адрес — своя строка
        login="anna", method=METHOD_PASSWORD, ip="10.8.8.10", user_agent="UA",
        result=RESULT_RATE_LIMITED,
    )  # fmt: skip

    видно = journals.read_logins(люди.токены["sofia"])

    assert len([e for e in видно if e.result == RESULT_RATE_LIMITED]) == 3
    assert {e.ip for e in видно} == {"10.8.8.8", "10.8.8.9", "10.8.8.10"}
    assert next(e for e in видно if e.ip == "10.8.8.8").login == "anna", "учётка не определена"
    assert all("нет-такого" not in repr(e) for e in видно), "введённый логин попал в журнал"


def test_отказ_по_частоте_пишется_снова_после_окна(люди: Люди, pg_dsn: str) -> None:
    запись = dict(login="anna", method=METHOD_PASSWORD, ip="10.8.8.8", user_agent="UA",
                  result=RESULT_RATE_LIMITED)  # fmt: skip
    journals.record_failed_login(**запись)
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute("update login_journal set occurred_at = now() - interval '11 minutes'")

    journals.record_failed_login(**запись)

    assert len(journals.read_logins(люди.токены["sofia"])) == 2
