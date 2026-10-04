"""Ядро D286: ссылка привязки одноразовая, короткоживущая, привязывает к учётке и её пространству.

Review Focus 1–3 волны 1 (#340): перехват и повтор ссылки, второй Telegram к той
же учётке и чужой Telegram к учётке, отвязка и отключение.
"""

from __future__ import annotations

import re
import threading
import time

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
    standing,
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


def test_ссылка_не_сгорает_если_telegram_привязан_к_другой_учётке(
    учётки: dict[str, str],
) -> None:
    """Ревью #340, п.8: отвязал прежнюю учётку — та же ссылка срабатывает."""
    redeem(issue_link(учётки["hq"]).token, telegram_id=501)
    ссылка = issue_link(учётки["ge"])
    assert redeem(ссылка.token, telegram_id=501) is None
    unbind(учётки["hq"])
    привязка = redeem(ссылка.token, telegram_id=501)
    assert привязка is not None and привязка.tenant == "GE"


def _ждать_блокировки(pg_dsn: str, сколько: float = 10.0) -> None:
    """Дождаться, пока чья-то вставка встанет в ожидание чужой транзакции."""
    срок = time.monotonic() + сколько
    with psycopg.connect(pg_dsn, autocommit=True) as conn:
        while time.monotonic() < срок:
            ждёт = conn.execute("select count(*) from pg_locks where not granted").fetchone()
            if ждёт is not None and ждёт[0] > 0:
                return
            time.sleep(0.05)
    raise AssertionError("параллельная попытка так и не встала в ожидание")


def test_параллельная_привязка_того_же_telegram_даёт_отказ_а_не_ошибку(
    учётки: dict[str, str], pg_dsn: str
) -> None:
    """Ревью #340, п.8: проигравшая гонку попытка — `None`, ссылка цела."""
    ссылка = issue_link(учётки["ge"])
    итог: list[object] = []
    with psycopg.connect(pg_dsn) as соперник:
        # Соперник привязал тот же Telegram к другой учётке и ещё не закрыл
        # транзакцию: проверка «занят ли» его строки не видит.
        соперник.execute(
            "insert into bot_bindings (telegram_id, user_id) values (501, %s)", (учётки["hq"],)
        )
        поток = threading.Thread(
            target=lambda: итог.append(_попытка(ссылка.token, 501)), daemon=True
        )
        поток.start()
        _ждать_блокировки(pg_dsn)
    поток.join(timeout=10)
    assert итог == [None], итог
    опознан = resolve(501)
    assert опознан is not None and опознан.tenant == "HQ"
    unbind(учётки["hq"])
    assert redeem(ссылка.token, telegram_id=501) is not None, "проигравшая попытка не сожгла ссылку"


def _попытка(token: str, telegram_id: int) -> object:
    try:
        return redeem(token, telegram_id=telegram_id)
    except Exception as exc:  # исход гонки и есть предмет теста
        return exc


def test_отвязка_и_отключение_снимают_доступ(учётки: dict[str, str]) -> None:
    """Review Focus 3."""
    redeem(issue_link(учётки["ge"]).token, telegram_id=501)
    assert unbind(учётки["ge"]) is True
    assert resolve(501) is None and binding_of(учётки["ge"]) is None
    assert unbind(учётки["ge"]) is False
    redeem(issue_link(учётки["hq"]).token, telegram_id=601)
    disable_account("hq-auditor", tenant="HQ")
    assert resolve(601) is None


def test_положение_помнит_снятую_привязку(учётки: dict[str, str]) -> None:
    """Ревью #340, п.5: отвязанный и с отключённой учёткой — «была привязка»."""
    assert standing(501).ever_bound is False
    redeem(issue_link(учётки["ge"]).token, telegram_id=501)
    живая = standing(501)
    assert живая.binding is not None and живая.binding.tenant == "GE"
    unbind(учётки["ge"])
    assert (standing(501).binding, standing(501).ever_bound) == (None, True)
    redeem(issue_link(учётки["hq"]).token, telegram_id=601)
    disable_account("hq-auditor", tenant="HQ")
    assert (standing(601).binding, standing(601).ever_bound) == (None, True)


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
