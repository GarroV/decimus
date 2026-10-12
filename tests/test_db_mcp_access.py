"""T253: личный доступ к MCP (`src/db/mcp_access.py`) — тесты уровня базы.

Модуль хранит связь «эта учётка — этот токен» (D448: круга допущенных больше
нет, токен человек выпускает себе сам). Здесь проверяется поведение (выпуск,
замена, сверка) и — отдельно и обязательно ЗАПУСКОМ, а не
чтением схемы — заслоны, которые держит миграция `0011`: значения токена в
базе нет, колонка отпечатка не принимает ничего, кроме SHA-256, и живым у
учётки может быть только один токен разом (`0057`).

Идёт под `db_env` (роль приложения `dodo_audit_app`), а не под суперпользова-
телем: суперпользователь обходит и ограничения-заслоны в духе `CheckViolation`
ничем не иначе, но частичный уникальный индекс и проверка формы отпечатка —
это ограничения ТАБЛИЦЫ, а не построчные политики, и держат они одинаково при
любой роли. Роль приложения выбрана здесь не ради RLS, а потому что это та
роль, под которой модуль реально работает на площадке (T111).
"""

from __future__ import annotations

from typing import Any

import pytest
from conftest import requires_db
from db_harness import завести_пространства, привязать_бота

psycopg = pytest.importorskip("psycopg")

from src.db.mcp_access import (  # noqa: E402
    issue_token,
    new_token,
    resolve_token,
    token_fingerprint,
)

pytestmark = requires_db


#: Telegram ID тестов — не настоящие, просто различимые числа.
ОСНОВАТЕЛЬ = 100


@pytest.fixture(autouse=True)
def _пространства(request: pytest.FixtureRequest) -> None:
    """Пространство и учётки, на которые выпускаются токены тестов набора.

    Двери базы пространств сами не заводят (#481); токен выпускается только на
    учётку сайта, а дверь бота находит её по привязке (аудит 12.10). Фикстура с условием: тест
    без базы её не получает.
    """
    if "db_env" in request.fixturenames:
        request.getfixturevalue("db_env")  # учётку заводит дверь базы: ей нужна база
        pg_dsn = request.getfixturevalue("pg_dsn")
        monkeypatch = request.getfixturevalue("monkeypatch")
        завести_пространства(pg_dsn, "belgrade")
        привязать_бота(pg_dsn, monkeypatch, ОСНОВАТЕЛЬ, tenant="belgrade", role="admin")


#: Вставка живого токена в обход двери — с учёткой, ролью и сроком, как требует
#: `0057`; учётка — та, к которой привязан Telegram ID (параметр третий).
_ВСТАВКА_С_УЧЁТКОЙ = (
    "insert into mcp_tokens (telegram_id, tenant_code, fingerprint, user_id, role, expires_at) "
    "select %s, u.tenant_code, %s, u.id, u.role, now() + interval '1 day' "
    "from bot_bindings b join web_users u on u.id = b.user_id "
    "where b.telegram_id = %s and b.unbound_at is null"
)


def _строка(dsn: str, sql: str, params: tuple[Any, ...] = ()) -> tuple[Any, ...] | None:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def _выполнить(dsn: str, sql: str, params: tuple[Any, ...] = ()) -> int:
    """Выполнить запись и вернуть число затронутых строк."""
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        затронуто = cur.rowcount
        conn.commit()
    return затронуто


# --- выпуск и сверка -----------------------------------------------------------


def test_выпущенный_токен_сверяется_и_отдаёт_того_человека_и_арендатора(db_env: str) -> None:
    """`resolve_token` — то же самое, что спрашивает сервер MCP на каждый запрос."""

    выпуск = issue_token(ОСНОВАТЕЛЬ)

    assert выпуск.tenant == "belgrade"
    assert выпуск.replaced_previous is False
    владелец = resolve_token(выпуск.value)
    assert владелец is not None
    assert владелец.login == f"tg-{ОСНОВАТЕЛЬ}"
    assert владелец.tenant == "belgrade"
    assert владелец.role == "admin", "токен несёт роль учётки, а не только пространство"
    assert выпуск.role == "admin"


def test_повторный_выпуск_гасит_прежний_токен_и_ставит_replaced_previous(db_env: str) -> None:
    """У человека живым может быть только один токен — повторный выпуск это держит."""
    первый = issue_token(ОСНОВАТЕЛЬ)

    второй = issue_token(ОСНОВАТЕЛЬ)

    assert второй.replaced_previous is True
    assert второй.value != первый.value
    assert resolve_token(первый.value) is None, "прежний токен всё ещё сверяется"
    владелец = resolve_token(второй.value)
    assert владелец is not None and владелец.login == f"tg-{ОСНОВАТЕЛЬ}"


def test_незнакомый_токен_отвечает_ничем(db_env: str) -> None:
    assert resolve_token("совсем-незнакомое-значение-которого-не-выпускали") is None


# --- заслоны схемы: проверено запуском, а не рассуждением ----------------------


def test_значения_токена_в_базе_нет(db_env: str) -> None:
    """Заголовок модуля обещает: значение токена не хранится нигде.

    Обещание кода проверяется прямым запросом к базе — читать нужно
    отпечаток, а не сырое значение, и сырого значения не должно найтись ни
    в одном столбце строки.
    """
    выпуск = issue_token(ОСНОВАТЕЛЬ)

    строка = _строка(
        db_env,
        "select id, telegram_id, tenant_code, fingerprint, issued_at, revoked_at, revoked_by "
        "from mcp_tokens where telegram_id = %s",
        (ОСНОВАТЕЛЬ,),
    )
    assert строка is not None
    отпечаток = строка[3]
    assert отпечаток == token_fingerprint(выпуск.value)
    сериализовано = "|".join("" if поле is None else str(поле) for поле in строка)
    assert выпуск.value not in сериализовано, "сырое значение токена нашлось в строке таблицы"


def test_сырой_токен_в_колонку_отпечатка_не_записывается(db_env: str) -> None:
    """Заслон — ограничение схемы (миграция `0011`), а не аккуратность кода модуля."""
    похожий_на_сырой_токен = new_token()  # 43 знака, есть - и _ — не 64 hex-знака

    with pytest.raises(psycopg.errors.CheckViolation, match="fingerprint"):
        _выполнить(db_env, _ВСТАВКА_С_УЧЁТКОЙ, (ОСНОВАТЕЛЬ, похожий_на_сырой_токен, ОСНОВАТЕЛЬ))


def test_у_учётки_не_бывает_двух_живых_токенов_одновременно(db_env: str) -> None:
    """Заслон — частичный уникальный индекс `mcp_tokens_one_live_per_user_idx` (`0057`).

    Отпечатки у двух вставок РАЗНЫЕ, чтобы отказ был именно об индексе «один
    живой на учётку», а не о совпадении самого отпечатка.
    """
    _выполнить(
        db_env,
        _ВСТАВКА_С_УЧЁТКОЙ,
        (ОСНОВАТЕЛЬ, token_fingerprint("первый-фиктивный-токен-теста"), ОСНОВАТЕЛЬ),
    )

    with pytest.raises(psycopg.errors.UniqueViolation):
        _выполнить(
            db_env,
            _ВСТАВКА_С_УЧЁТКОЙ,
            (ОСНОВАТЕЛЬ, token_fingerprint("второй-фиктивный-токен-теста"), ОСНОВАТЕЛЬ),
        )


def test_живой_токен_без_учётки_и_срока_схема_не_принимает(db_env: str) -> None:
    """Заслон `mcp_tokens_live_has_identity` (`0057`): вечный ничей токен — отказ записи."""
    with pytest.raises(psycopg.errors.CheckViolation, match="live_has_identity"):
        _выполнить(
            db_env,
            "insert into mcp_tokens (telegram_id, tenant_code, fingerprint) "
            "values (%s, 'belgrade', %s)",
            (ОСНОВАТЕЛЬ, token_fingerprint("ничей-фиктивный-токен-теста")),
        )
