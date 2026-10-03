"""Ядро D286: ссылка привязки одноразовая, короткоживущая, привязывает к учётке и её пространству.

Review Focus 1–3 волны 1 (#340): перехват и повтор ссылки, второй Telegram к той
же учётке и чужой Telegram к учётке, отвязка и отключение.
"""

from __future__ import annotations

import re

import pytest
from conftest import requires_db

psycopg = pytest.importorskip("psycopg")

from src.db.bot_links import (  # noqa: E402
    LINK_PREFIX,
    binding_of,
    issue_link,
    live_bindings,
    redeem,
    resolve,
    unbind,
)
from src.db.web_access import create_account, disable_account  # noqa: E402

pytestmark = requires_db
ПАРОЛЬ = "верный-пароль-учётки"


@pytest.fixture
def учётки(pg_dsn: str, db_env: str, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    monkeypatch.setenv("DATABASE_ADMIN_URL", pg_dsn)
    return {
        "ge": create_account("ge-auditor", tenant="GE", password=ПАРОЛЬ).id,
        "hq": create_account("hq-auditor", tenant="HQ", password=ПАРОЛЬ).id,
    }


def test_ссылка_привязывает_к_пространству_учётки(учётки: dict[str, str]) -> None:
    привязка = redeem(issue_link(учётки["ge"]).token, telegram_id=501)
    assert привязка is not None
    assert (привязка.tenant, привязка.login) == ("GE", "ge-auditor")
    опознан = resolve(501)
    assert опознан is not None and опознан.tenant == "GE"


def test_повтор_ссылки_не_срабатывает(учётки: dict[str, str]) -> None:
    """Review Focus 1: перехваченная ссылка после хозяина ничего не даёт."""
    ссылка = issue_link(учётки["ge"])
    assert redeem(ссылка.token, telegram_id=501) is not None
    assert redeem(ссылка.token, telegram_id=666) is None
    assert resolve(666) is None
    assert resolve(501) is not None, "повтор не должен снимать привязку хозяина"


def test_просроченная_ссылка_не_срабатывает(учётки: dict[str, str], pg_dsn: str) -> None:
    ссылка = issue_link(учётки["ge"])
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "update bot_link_tokens set expires_at = now() - interval '1 second'"
            " where user_id = %s",
            (учётки["ge"],),
        )
    assert redeem(ссылка.token, telegram_id=501) is None
    assert resolve(501) is None


def test_чужая_или_выдуманная_ссылка_не_срабатывает(учётки: dict[str, str]) -> None:
    assert redeem("x" * 32, telegram_id=501) is None
    assert redeem("", telegram_id=501) is None


def test_новая_ссылка_гасит_прежнюю(учётки: dict[str, str]) -> None:
    прежняя = issue_link(учётки["ge"])
    свежая = issue_link(учётки["ge"])
    assert redeem(прежняя.token, telegram_id=501) is None
    assert redeem(свежая.token, telegram_id=501) is not None


def test_ссылка_отключённой_учётки_не_срабатывает(учётки: dict[str, str]) -> None:
    ссылка = issue_link(учётки["ge"])
    disable_account("ge-auditor", tenant="GE")
    assert redeem(ссылка.token, telegram_id=501) is None


def test_второй_telegram_гасит_прежнюю_привязку(учётки: dict[str, str]) -> None:
    """Review Focus 2, D291: новая привязка той же учётки заменяет прежнюю."""
    redeem(issue_link(учётки["ge"]).token, telegram_id=501)
    redeem(issue_link(учётки["ge"]).token, telegram_id=502)
    assert resolve(501) is None
    второй = resolve(502)
    assert второй is not None and второй.login == "ge-auditor"


def test_telegram_чужой_учётки_не_перепривязывается(учётки: dict[str, str]) -> None:
    """Review Focus 2, D291: Telegram учётки A по ссылке учётки B не перепривязывается."""
    redeem(issue_link(учётки["hq"]).token, telegram_id=501)
    assert redeem(issue_link(учётки["ge"]).token, telegram_id=501) is None
    опознан = resolve(501)
    assert опознан is not None and опознан.tenant == "HQ"
    assert binding_of(учётки["ge"]) is None


def test_отвязка_и_отключение_снимают_доступ(учётки: dict[str, str]) -> None:
    """Review Focus 3."""
    redeem(issue_link(учётки["ge"]).token, telegram_id=501)
    assert unbind(учётки["ge"]) is True
    assert resolve(501) is None and binding_of(учётки["ge"]) is None
    assert unbind(учётки["ge"]) is False
    redeem(issue_link(учётки["hq"]).token, telegram_id=601)
    disable_account("hq-auditor", tenant="HQ")
    assert resolve(601) is None


def test_в_базе_нет_токена_только_отпечаток(учётки: dict[str, str], pg_dsn: str) -> None:
    ссылка = issue_link(учётки["ge"])
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute("select fingerprint from bot_link_tokens where user_id = %s", (учётки["ge"],))
        (отпечаток,) = cur.fetchone()  # type: ignore[misc]
    assert ссылка.token not in отпечаток and len(отпечаток) == 64


def test_погашенную_ссылку_не_воскресить_правкой_строки(
    учётки: dict[str, str], db_env: str
) -> None:
    """Сужающая политика: роль приложения не снимает пометку погашения."""
    ссылка = issue_link(учётки["ge"])
    redeem(ссылка.token, telegram_id=501)
    with psycopg.connect(db_env) as conn, conn.cursor() as cur:
        cur.execute("update bot_link_tokens set used_at = null where user_id = %s", (учётки["ge"],))
        assert cur.rowcount == 0
    assert redeem(ссылка.token, telegram_id=666) is None


def test_метка_помещается_в_deep_link(учётки: dict[str, str]) -> None:
    метка = LINK_PREFIX + issue_link(учётки["ge"]).token
    assert re.fullmatch(r"[A-Za-z0-9_-]{1,64}", метка)


def test_живые_привязки_одним_запросом_по_ключу_учётки(учётки: dict[str, str]) -> None:
    redeem(issue_link(учётки["ge"]).token, telegram_id=501)
    redeem(issue_link(учётки["hq"]).token, telegram_id=601)
    unbind(учётки["hq"])

    живые = live_bindings()

    assert set(живые) == {учётки["ge"]}
    assert живые[учётки["ge"]].telegram_id == 501
