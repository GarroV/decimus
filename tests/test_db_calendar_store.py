"""D741 (#1590): ключ продления в базе лежит зашифрованным; выборка проверок и событий.

Важное, что нельзя обойти: открытого ключа в базе нет; ключ одного человека не открывается
под именем другого; снятую (отклонённую) проверку роль приложения не видит — по этому и
снимается событие; в выборку попадают только полевые проверки УК людей с живой привязкой
бота и рабочим подключением.
"""

from __future__ import annotations

import base64
import os
from datetime import date

import psycopg
import pytest
from conftest import requires_db

from src.db import calendar_store, secret_crypto
from src.db.errors import DbError

pytestmark = requires_db

КЛЮЧ = "1//0g-очень-секретный-ключ-продления"
СЕГОДНЯ = date(2026, 11, 9)


@pytest.fixture(autouse=True)
def ключ_шифрования(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(secret_crypto.SECRETS_KEY_VAR, base64.b64encode(os.urandom(32)).decode())


def _человек(conn: psycopg.Connection, login: str, telegram_id: int | None = None) -> str:
    ид = str(
        conn.execute(
            "insert into web_users (tenant_code, login, password_hash, role) "
            "values ('HQ', %s, 'scrypt$1$1$1$00$00', 'admin') returning id",
            (login,),
        ).fetchone()[0]
    )
    if telegram_id is not None:
        conn.execute(
            "insert into bot_bindings (telegram_id, user_id) values (%s, %s)", (telegram_id, ид)
        )
    return ид


def _проверка(
    conn: psycopg.Connection,
    *,
    chat: int,
    name: str,
    tenant: str = "HQ",
    origin: str = "field",
    day: date = date(2026, 11, 6),
) -> str:
    unit = conn.execute(
        "insert into units(tenant_code,name,name_normalized,country) values (%s,%s,%s,'RS') "
        "returning id",
        (tenant, name, name.lower()),
    ).fetchone()[0]
    return str(
        conn.execute(
            "insert into inspections(tenant_code,unit_id,chat_id,kind,inspection_date,"
            "report_lang,ui_lang,speech_lang,checklist_version,pct,grade,source_fingerprint,"
            "status,origin) values (%s,%s,%s,'planned',%s,'ru','en','ru','v1',95,'B',%s,"
            "'draft',%s) returning id",
            (tenant, unit, chat, day, f"{name}-{chat}", origin),
        ).fetchone()[0]
    )


def test_ключ_в_базе_зашифрован_и_читается_обратно(pg_dsn: str, db_env: str) -> None:
    with psycopg.connect(pg_dsn) as conn:
        ид = _человек(conn, "cal-a")
    calendar_store.save_grant(ид, google_email="a@x.y", scope="s", refresh_token=КЛЮЧ)

    with psycopg.connect(pg_dsn) as conn:
        лежит = bytes(
            conn.execute(
                "select refresh_ciphertext from calendar_grants where user_id = %s", (ид,)
            ).fetchone()[0]
        )
    assert КЛЮЧ.encode() not in лежит, "открытый ключ продления лежит в базе"
    assert calendar_store.refresh_token_of(ид) == КЛЮЧ


def test_шифртекст_одного_человека_не_открывается_под_другим(pg_dsn: str, db_env: str) -> None:
    with psycopg.connect(pg_dsn) as conn:
        первый, второй = _человек(conn, "cal-b1"), _человек(conn, "cal-b2")
    calendar_store.save_grant(первый, google_email="a@x.y", scope="s", refresh_token=КЛЮЧ)
    calendar_store.save_grant(второй, google_email="b@x.y", scope="s", refresh_token="другой")
    with psycopg.connect(pg_dsn) as conn:
        conn.execute(
            "update calendar_grants set refresh_ciphertext = "
            "(select refresh_ciphertext from calendar_grants where user_id = %s) "
            "where user_id = %s",
            (первый, второй),
        )

    with pytest.raises(secret_crypto.SecretCryptoError):
        calendar_store.refresh_token_of(второй)


def test_отключение_стирает_подключение_и_записи_событий(pg_dsn: str, db_env: str) -> None:
    with psycopg.connect(pg_dsn) as conn:
        ид = _человек(conn, "cal-c", 9001)
        проверка = _проверка(conn, chat=9001, name="C")
    calendar_store.save_grant(ид, google_email="a@x.y", scope="s", refresh_token=КЛЮЧ)
    calendar_store.remember_event(проверка, ид, event_id="ev", due=СЕГОДНЯ, title="t")

    assert calendar_store.delete_grant(ид) is True

    assert calendar_store.grant_of(ид) is None and calendar_store.events_of(ид) == []
    assert calendar_store.delete_grant(ид) is False


def test_в_выборку_идут_только_полевые_проверки_ук_людей_с_подключением(
    pg_dsn: str, db_env: str
) -> None:
    with psycopg.connect(pg_dsn) as conn:
        с_календарём = _человек(conn, "cal-d1", 9101)
        _человек(conn, "cal-d2", 9102)  # бот привязан, календаря нет
        нужная = _проверка(conn, chat=9101, name="Нужная")
        _проверка(conn, chat=9102, name="БезКалендаря")
        _проверка(conn, chat=0, name="Загруженная", origin="import")
        _проверка(conn, chat=9199, name="БезПривязки")
        _проверка(conn, chat=9101, name="Старая", day=date(2026, 9, 1))
    calendar_store.save_grant(с_календарём, google_email="a@x.y", scope="s", refresh_token=КЛЮЧ)

    найдено = calendar_store.candidates(since=date(2026, 10, 19), dead=("invalid_grant",))

    assert [(к.inspection_id, к.unit, к.ui_lang) for к in найдено] == [(нужная, "Нужная", "en")]
    assert найдено[0].event_id is None


def test_мёртвое_подключение_выпадает_из_выборки_а_временный_сбой_нет(
    pg_dsn: str, db_env: str
) -> None:
    with psycopg.connect(pg_dsn) as conn:
        ид = _человек(conn, "cal-e", 9201)
        _проверка(conn, chat=9201, name="E")
    calendar_store.save_grant(ид, google_email="a@x.y", scope="s", refresh_token=КЛЮЧ)

    calendar_store.mark_problem(ид, "http_503")
    assert len(calendar_store.candidates(since=date(2026, 10, 19), dead=("invalid_grant",))) == 1
    calendar_store.mark_problem(ид, "invalid_grant")
    assert calendar_store.candidates(since=date(2026, 10, 19), dead=("invalid_grant",)) == []
    calendar_store.clear_problem(ид)
    assert len(calendar_store.candidates(since=date(2026, 10, 19), dead=("invalid_grant",))) == 1


def test_стоящее_событие_приходит_вместе_с_кандидатом(pg_dsn: str, db_env: str) -> None:
    with psycopg.connect(pg_dsn) as conn:
        ид = _человек(conn, "cal-f", 9301)
        проверка = _проверка(conn, chat=9301, name="F")
    calendar_store.save_grant(ид, google_email="a@x.y", scope="s", refresh_token=КЛЮЧ)
    calendar_store.remember_event(проверка, ид, event_id="ev9", due=date(2026, 11, 11), title="T")

    (кандидат,) = calendar_store.candidates(since=date(2026, 10, 19), dead=())

    assert (кандидат.event_id, кандидат.event_due, кандидат.event_title) == (
        "ev9",
        date(2026, 11, 11),
        "T",
    )


def test_снятая_проверка_ведёт_к_осиротевшему_событию(pg_dsn: str, db_env: str) -> None:
    with psycopg.connect(pg_dsn) as conn:
        ид = _человек(conn, "cal-g", 9401)
        проверка = _проверка(conn, chat=9401, name="G")
    calendar_store.save_grant(ид, google_email="a@x.y", scope="s", refresh_token=КЛЮЧ)
    calendar_store.remember_event(проверка, ид, event_id="ev7", due=СЕГОДНЯ, title="T")
    assert calendar_store.orphans() == []

    with psycopg.connect(pg_dsn) as conn:  # снятие делает администратор истории (D089)
        conn.execute(
            "update inspections set retracted_at = now(), retraction_reason = 'ошибка' "
            "where id = %s",
            (проверка,),
        )

    assert [(о.inspection_id, о.event_id) for о in calendar_store.orphans()] == [(проверка, "ev7")]
    assert calendar_store.candidates(since=date(2026, 10, 19), dead=()) == []
    calendar_store.forget_event(проверка)
    assert calendar_store.orphans() == []


def test_сбой_без_кода_причины_базой_не_принимается(pg_dsn: str, db_env: str) -> None:
    with psycopg.connect(pg_dsn) as conn:
        ид = _человек(conn, "cal-h")
    calendar_store.save_grant(ид, google_email="a@x.y", scope="s", refresh_token=КЛЮЧ)

    with pytest.raises((DbError, psycopg.Error)):
        calendar_store.mark_problem(ид, "Текст ответа Google с почтой a@x.y")
