"""T328: снятие запрета на вход (`src/db/web_unlock.py`, решение D158).

Проверяется запуском и на настоящей базе, потому что всё содержание задачи —
это ПРАВА двух ролей и то, что запертый вход после команды действительно
открывается. «В миграции написано» и «база так делает» — разные утверждения, и
расходятся они молча.

Здесь же стоят обе половины гранта из `0016`: что администратору истории
хватает прав снять запрет, и что ему НЕ хватает прав его повесить.
"""

from __future__ import annotations

import pytest
from conftest import requires_db
from db_harness import set_retraction_env

psycopg = pytest.importorskip("psycopg")

from src.db.web_access import create_account  # noqa: E402
from src.db.web_throttle import (  # noqa: E402
    FAILURES_BEFORE_LOCK,
    SCOPE_LOGIN,
    admit_attempt,
    key_fingerprint,
)
from src.db.web_unlock import counters, unlock_address, unlock_login  # noqa: E402

pytestmark = requires_db

ТЕНАНТ = "rs"
ЧУЖОЙ = "me"
ЛОГИН = "director"
АДРЕС = "203.0.113.7"
ПОРОГ = FAILURES_BEFORE_LOCK[SCOPE_LOGIN]
#: Пароль учётки набора. Строкой с именем, а не значением по месту: значение в
#: вызове линтер справедливо принимает за зашитый пароль.
ПАРОЛЬ = "пароль-учётки-этого-набора"


@pytest.fixture
def обе_роли(pg_dsn: str, db_env: str, monkeypatch: pytest.MonkeyPatch) -> str:
    """Подключение приложения (`db_env`) плюс подключение администратора истории.

    Так устроен продукт: попытки считает роль приложения, снимает запрет роль
    администратора. Проверять снятие под одной ролью значило бы проверять код в
    отрыве от того, чем он на площадке ограничен.
    """
    return set_retraction_env(db_env, monkeypatch)


def запереть(*, login: str = ЛОГИН, address: str = АДРЕС) -> None:
    """Перебрать пароль до запрета — так, как это делает посторонний."""
    for _ in range(ПОРОГ):
        admit_attempt(tenant=ТЕНАНТ, address=address, login=login)
    assert not admit_attempt(tenant=ТЕНАНТ, address=address, login=login).admitted, (
        "вход не заперся — проверять снятие не на чем"
    )


# --- запертый вход открывается командой --------------------------------------


def test_снятие_запрета_открывает_вход_сразу(обе_роли: str) -> None:
    """Главная проверка задачи: заперли — сняли — снова пускает.

    Без неё вся задача держится на том, что строка удалена; а человеку нужно не
    удаление строки, а открытая дверь.
    """
    запереть()
    assert unlock_login(tenant=ТЕНАНТ, login=ЛОГИН), "команда сказала, что снимать было нечего"
    assert admit_attempt(tenant=ТЕНАНТ, address=АДРЕС, login=ЛОГИН).admitted, (
        "запрет сняли, а вход всё ещё закрыт"
    )


def test_снятие_по_логину_не_трогает_запрет_адреса(обе_роли: str) -> None:
    """Два счётчика — два запрета, и снимаются они раздельно.

    Иначе снятие по логину молча открывало бы и адрес, с которого шёл перебор
    по ДРУГИМ логинам, — то есть команда делала бы больше, чем сказано.
    """
    for n in range(FAILURES_BEFORE_LOCK["address"] + 1):
        admit_attempt(tenant=ТЕНАНТ, address=АДРЕС, login=f"логин{n}")
    unlock_login(tenant=ТЕНАНТ, login="логин0")
    assert not admit_attempt(tenant=ТЕНАНТ, address=АДРЕС, login="логин0").admitted, (
        "запрет по адресу исчез вместе с запретом по логину"
    )


def test_снятие_по_адресу_понимает_другую_запись_того_же_адреса(обе_роли: str) -> None:
    """Заперлись с `::ffff:203.0.113.7` — снимается по `203.0.113.7`.

    Иначе человек снимает запрет, команда отвечает «снято», а вход остаётся
    закрытым: отпечаток считался от другой записи того же адреса.
    """
    for n in range(FAILURES_BEFORE_LOCK["address"] + 1):
        admit_attempt(tenant=ТЕНАНТ, address="::ffff:203.0.113.7", login=f"логин{n}")
    assert unlock_address(tenant=ТЕНАНТ, address=АДРЕС), "адрес не узнан в другой записи"
    assert admit_attempt(tenant=ТЕНАНТ, address=АДРЕС, login="кто-то").admitted


def test_снимать_нечего_это_не_успех(обе_роли: str) -> None:
    """Ошибся арендатором или логином — обязан узнать об этом, а не уйти ждать."""
    assert not unlock_login(tenant=ТЕНАНТ, login="никогда-не-пробовавший")


def test_чужой_арендатор_остаётся_запертым(обе_роли: str) -> None:
    """Границу арендаторов снятие не переносит."""
    for _ in range(ПОРОГ + 1):
        admit_attempt(tenant=ЧУЖОЙ, address=АДРЕС, login=ЛОГИН)
    assert not unlock_login(tenant=ТЕНАНТ, login=ЛОГИН)
    assert not admit_attempt(tenant=ЧУЖОЙ, address=АДРЕС, login=ЛОГИН).admitted


# --- что видит человек из команды --------------------------------------------


def test_список_называет_заведённый_логин_и_срок(
    обе_роли: str, pg_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Иначе список — это столбец отпечатков, по которому не понять, кто заперт."""
    # Учётку заводит владелец схемы: роли приложения этого права не выдано
    # (`0014`), и подставить его сюда — значит проверять не тот продукт.
    monkeypatch.setenv("DATABASE_ADMIN_URL", pg_dsn)
    create_account(ЛОГИН, tenant=ТЕНАНТ, password=ПАРОЛЬ)
    запереть()
    ключи = counters(tenant=ТЕНАНТ)
    логины = [ключ for ключ in ключи if ключ.scope == SCOPE_LOGIN]
    assert len(логины) == 1
    assert логины[0].login == ЛОГИН, "заведённая учётка не узнана среди отпечатков"
    assert логины[0].locked and логины[0].verdict.retry_after_minutes >= 1


def test_незаведённый_логин_не_выдумывается(обе_роли: str) -> None:
    """Перебирают и несуществующие логины; их отпечаток остаётся отпечатком."""
    запереть(login="кого-нет")
    логины = [ключ for ключ in counters(tenant=ТЕНАНТ) if ключ.scope == SCOPE_LOGIN]
    assert логины and логины[0].login is None
    assert логины[0].fingerprint == key_fingerprint("кого-нет")


# --- права администратора истории: хватает снять, не хватает повесить --------


def test_администратор_не_может_повесить_запрет(обе_роли: str) -> None:
    """Права ДОБАВИТЬ неудачи нет, и это не оговорка в коде, а отказ базы.

    Роль, которая умеет вписать чужому логину полсотни неудач, умеет запирать
    вход человеку — то есть делать ровно то, от чего заведена команда снятия.
    """
    with psycopg.connect(обе_роли) as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute(
                "insert into web_login_attempts (tenant_code, scope, key_fingerprint, failures) "
                "values (%s, 'login', %s, 99)",
                (ТЕНАНТ, key_fingerprint(ЛОГИН)),
            )


def test_администратор_не_видит_свёртку_пароля(обе_роли: str) -> None:
    """Логины ему выданы, пароли — нет: грант колоночный, а не табличный."""
    with psycopg.connect(обе_роли) as conn, conn.cursor() as cur:
        cur.execute("select login from web_users")  # эта колонка выдана
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute("select password_hash from web_users")
