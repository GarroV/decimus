"""Имя из карточки человека по Telegram ID и по логину: запросы к базе (D642)."""

from __future__ import annotations

import pytest
from conftest import requires_db
from db_harness import завести_пространства

psycopg = pytest.importorskip("psycopg")

from src.db import auditor_card  # noqa: E402
from src.db.bot_links import issue_link, redeem, unbind  # noqa: E402
from src.db.web_access import create_account  # noqa: E402

pytestmark = requires_db
ПАРОЛЬ = "верный-пароль-учётки"


@pytest.fixture
def учётка(pg_dsn: str, db_env: str, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("DATABASE_ADMIN_URL", pg_dsn)
    завести_пространства(pg_dsn, "HQ")
    return create_account("rinat", tenant="HQ", password=ПАРОЛЬ).id


def _задать_имя(pg_dsn: str, user_id: str, имя: str | None, латиницей: str | None = None) -> None:
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "update web_users set display_name = %s, display_name_latin = %s where id = %s",
            (имя, латиницей, user_id),
        )


def test_по_telegram_привязанному_к_карточке(pg_dsn: str, учётка: str) -> None:
    _задать_имя(pg_dsn, учётка, "Жульфаев Ринат")
    redeem(issue_link(учётка).token, telegram_id=501)
    assert auditor_card.name_by_telegram(501) == "Жульфаев Ринат"


def test_telegram_без_привязки_даёт_none(pg_dsn: str, учётка: str) -> None:
    _задать_имя(pg_dsn, учётка, "Жульфаев Ринат")
    assert auditor_card.name_by_telegram(999) is None


def test_отвязанный_telegram_даёт_none(pg_dsn: str, учётка: str) -> None:
    _задать_имя(pg_dsn, учётка, "Жульфаев Ринат")
    redeem(issue_link(учётка).token, telegram_id=501)
    unbind(учётка)
    assert auditor_card.name_by_telegram(501) is None


def test_у_карточки_нет_имени_даёт_none(pg_dsn: str, учётка: str) -> None:
    redeem(issue_link(учётка).token, telegram_id=501)
    assert auditor_card.name_by_telegram(501) is None


def test_по_логину_и_пространству(pg_dsn: str, учётка: str) -> None:
    _задать_имя(pg_dsn, учётка, "Жульфаев Ринат")
    assert auditor_card.name_by_login("HQ", "Rinat ") == "Жульфаев Ринат"
    assert auditor_card.name_by_login("GE", "rinat") is None


def test_имя_латиницей_из_карточки_сильнее_имени_из_google(pg_dsn: str, учётка: str) -> None:
    _задать_имя(pg_dsn, учётка, "Жульфаев Ринат", "Rinat Zhulfaev")
    redeem(issue_link(учётка).token, telegram_id=501)
    assert auditor_card.name_by_telegram(501) == "Rinat Zhulfaev"
    assert auditor_card.name_by_login("HQ", "rinat") == "Rinat Zhulfaev"


def test_пустое_имя_латиницей_не_затирает_имя(pg_dsn: str, учётка: str) -> None:
    _задать_имя(pg_dsn, учётка, "Жульфаев Ринат", "  ")
    assert auditor_card.name_by_login("HQ", "rinat") == "Жульфаев Ринат"
