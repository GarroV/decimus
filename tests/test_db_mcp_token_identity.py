"""Личный токен MCP — на учётку сайта, со сроком и ролью (аудит 12.10, миграция `0059`).

Ядро безопасности: до фикса токен знал только Telegram ID и пространство, и
- отключённая учётка или сменённая роль не гасили его (F-023, F-035);
- роль «контроль» получала через Claude проверки и методику (F-017, F-022; D420);
- доступ раздавал «круг» по Telegram ID, плоский на все пространства (F-036).

D448: круга нет, токен человек выпускает себе сам — на свою учётку; права решает
роль; доступ кончается отключением или сменой роли. Каждая проверка здесь
проверяет то, что на прежнем коде проходило. Идёт под ролью приложения
(`db_env`), как на площадке.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest
from conftest import requires_db
from db_harness import empty_database, привязать_бота

psycopg = pytest.importorskip("psycopg")

from src.db import bot_links, mcp_access  # noqa: E402
from src.db.errors import AccessError, UnboundError  # noqa: E402
from src.db.mcp_access import (  # noqa: E402
    issue_for_account,
    issue_token,
    live_token_expiry,
    resolve_token,
    revoke_tokens,
)
from src.db.migrate import MIGRATIONS_DIR, apply_migrations  # noqa: E402
from src.db.web_access import disable_account, password_hash, set_role  # noqa: E402
from src.mcp import config as mcp_config  # noqa: E402
from src.mcp.catalogue import KIND_RATINGS, KIND_RATINGS_READ, find  # noqa: E402
from src.mcp.rpc import handle  # noqa: E402

pytestmark = requires_db

АДМИН_УК = 301
КОНТРОЛЬ_УК = 302
АДМИН_ПАРТНЁРА = 401
СОТРУДНИК_ПАРТНЁРА = 402
БЕЗ_УЧЁТКИ = 999


@pytest.fixture
def учётки(pg_dsn: str, db_env: str, monkeypatch: pytest.MonkeyPatch) -> dict[int, str]:
    """Telegram ID → `web_users.id`: УК (админ, контроль) и партнёр GE (админ, сотрудник)."""
    return {
        АДМИН_УК: привязать_бота(pg_dsn, monkeypatch, АДМИН_УК, tenant="HQ", role="admin"),
        КОНТРОЛЬ_УК: привязать_бота(pg_dsn, monkeypatch, КОНТРОЛЬ_УК, tenant="HQ", role="control"),
        АДМИН_ПАРТНЁРА: привязать_бота(
            pg_dsn, monkeypatch, АДМИН_ПАРТНЁРА, tenant="GE", role="admin"
        ),
        СОТРУДНИК_ПАРТНЁРА: привязать_бота(
            pg_dsn, monkeypatch, СОТРУДНИК_ПАРТНЁРА, tenant="GE", role="auditor"
        ),
    }


def _выдать(кто: int) -> str:
    """Выпуск себе из бота — без чьего-либо разрешения: круга нет (D448)."""
    return issue_token(кто).value


def _выполнить(dsn: str, sql: str, params: tuple[Any, ...] = ()) -> None:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(sql, params)


# --- жизнь токена следует за учёткой (F-023, F-035) ------------------------------


def test_токен_несёт_роль_и_пространство_учётки(учётки: dict[int, str]) -> None:
    токен = _выдать(СОТРУДНИК_ПАРТНЁРА)

    владелец = resolve_token(токен)

    assert владелец is not None
    assert (владелец.tenant, владелец.role) == ("GE", "auditor")


def test_отключённая_учётка_токеном_не_пользуется(учётки: dict[int, str]) -> None:
    токен = _выдать(СОТРУДНИК_ПАРТНЁРА)

    assert disable_account(f"tg-{СОТРУДНИК_ПАРТНЁРА}", tenant="GE") is True

    assert resolve_token(токен) is None, "отключённый человек продолжает ходить в Claude"


def test_смена_роли_гасит_токен(учётки: dict[int, str]) -> None:
    токен = _выдать(АДМИН_УК)

    assert set_role(f"tg-{АДМИН_УК}", tenant="HQ", role="control") is True

    assert resolve_token(токен) is None, "токен пережил понижение роли"
    # Перевыпуск — уже с новой ролью, и права теперь решает она.
    новый = resolve_token(issue_token(АДМИН_УК).value)
    assert новый is not None and новый.role == "control"


def test_истёкший_токен_не_опознаётся(учётки: dict[int, str], pg_dsn: str) -> None:
    токен = _выдать(АДМИН_УК)
    assert resolve_token(токен) is not None

    _выполнить(
        pg_dsn,
        "update mcp_tokens set expires_at = now() - interval '1 second' where telegram_id = %s",
        (АДМИН_УК,),
    )

    assert resolve_token(токен) is None, "токен работает после срока"


def test_срок_по_умолчанию_тридцать_дней(учётки: dict[int, str], pg_dsn: str) -> None:
    _выдать(АДМИН_УК)
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "select round(extract(epoch from expires_at - issued_at) / 86400) from mcp_tokens "
            "where telegram_id = %s and revoked_at is null",
            (АДМИН_УК,),
        )
        assert cur.fetchone() == (30,)


def test_срок_задаётся_окружением(учётки: dict[int, str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_TOKEN_TTL_DAYS", "7")

    выпуск = issue_token(АДМИН_УК)

    from datetime import UTC, datetime, timedelta

    assert abs(выпуск.expires_at - (datetime.now(UTC) + timedelta(days=7))) < timedelta(hours=1)


def test_без_учётки_токен_не_выпускается(учётки: dict[int, str]) -> None:
    """Сотрудник по списку окружения без привязки бота — токена из чата нет."""
    with pytest.raises(UnboundError):
        issue_token(БЕЗ_УЧЁТКИ)


def test_после_отвязки_бота_из_чата_не_выпустить(учётки: dict[int, str]) -> None:
    """Отвязка закрывает дверь бота; выпущенный токен живёт — он на учётке, не на чате."""
    токен = _выдать(АДМИН_УК)

    assert bot_links.unbind(учётки[АДМИН_УК]) is True

    with pytest.raises(UnboundError):
        issue_token(АДМИН_УК)
    assert resolve_token(токен) is not None


# --- выпуск себе сам, на любой двери (D447, D448) --------------------------------


@pytest.mark.parametrize("кто", [КОНТРОЛЬ_УК, СОТРУДНИК_ПАРТНЁРА, АДМИН_ПАРТНЁРА])
def test_любая_роль_выпускает_себе_сама_без_чьей_либо_выдачи(
    учётки: dict[int, str], кто: int
) -> None:
    """Никого не приводили и ничего не выдавали — учётки и её роли достаточно."""
    выпуск = issue_for_account(учётки[кто])

    владелец = resolve_token(выпуск.value)
    assert владелец is not None and владелец.user_id == учётки[кто]


def test_круга_в_модуле_нет() -> None:
    """Дверей «выдать другому» и «отозвать у другого по Telegram ID» не осталось."""
    for имя in ("add_admin", "revoke_access", "list_admins", "is_admin", "in_scope"):
        assert not hasattr(mcp_access, имя), f"круг доступа вернулся: {имя}"


def test_веб_и_бот_делят_один_живой_токен_учётки(учётки: dict[int, str], pg_dsn: str) -> None:
    из_бота = _выдать(АДМИН_УК)

    из_веба = issue_for_account(учётки[АДМИН_УК])

    assert из_веба.replaced_previous is True
    assert resolve_token(из_бота) is None, "токен из бота пережил выпуск в вебе"
    assert resolve_token(из_веба.value) is not None
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "select telegram_id from mcp_tokens where user_id = %s and revoked_at is null",
            (учётки[АДМИН_УК],),
        )
        assert cur.fetchall() == [(None,)], "веб записал Telegram, которого не знает"


def test_свой_отзыв_гасит_сразу(учётки: dict[int, str]) -> None:
    выпуск = issue_for_account(учётки[СОТРУДНИК_ПАРТНЁРА])
    assert live_token_expiry(учётки[СОТРУДНИК_ПАРТНЁРА]) is not None

    assert revoke_tokens(учётки[СОТРУДНИК_ПАРТНЁРА]) == 1

    assert resolve_token(выпуск.value) is None
    assert live_token_expiry(учётки[СОТРУДНИК_ПАРТНЁРА]) is None
    assert revoke_tokens(учётки[СОТРУДНИК_ПАРТНЁРА]) == 0


def test_отключённой_учётке_токен_не_выпускается(учётки: dict[int, str]) -> None:
    assert disable_account(f"tg-{СОТРУДНИК_ПАРТНЁРА}", tenant="GE") is True

    with pytest.raises(AccessError):
        issue_for_account(учётки[СОТРУДНИК_ПАРТНЁРА])


def test_возврат_прежней_роли_токен_не_оживляет(учётки: dict[int, str], pg_dsn: str) -> None:
    """Смена роли гасит токен в базе (триггер `0059`), а не только не находит его."""
    токен = _выдать(АДМИН_УК)

    assert set_role(f"tg-{АДМИН_УК}", tenant="HQ", role="control") is True
    assert set_role(f"tg-{АДМИН_УК}", tenant="HQ", role="admin") is True

    assert resolve_token(токен) is None, "токен ожил с возвратом роли"
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute("select revoked_by from mcp_tokens where user_id = %s", (учётки[АДМИН_УК],))
        assert cur.fetchall() == [(0,)]


# --- права в Claude решает роль (F-017, F-022; D420) -----------------------------


def _инструменты(доступ: mcp_config.Access) -> set[str]:
    ответ = handle(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        tenant=доступ.tenant,
        role=доступ.role,
        actor=доступ.actor,
    )
    assert ответ is not None
    return {инструмент["name"] for инструмент in ответ["result"]["tools"]}


def test_токен_контроля_видит_только_рейтинги(учётки: dict[int, str]) -> None:
    доступ = mcp_config._owner_from_store(_выдать(КОНТРОЛЬ_УК))

    assert доступ is not None and доступ.role == "control"
    видно = _инструменты(доступ)
    assert видно, "контролю закрыли вообще всё"
    чужие = {имя for имя in видно if find(имя).kind not in (KIND_RATINGS, KIND_RATINGS_READ)}  # type: ignore[union-attr]
    assert чужие == set(), f"контролю видны инструменты не про рейтинги: {sorted(чужие)}"
    assert "list_inspections" not in видно


def test_вызов_проверок_токеном_контроля_отказ(учётки: dict[int, str]) -> None:
    доступ = mcp_config._owner_from_store(_выдать(КОНТРОЛЬ_УК))
    assert доступ is not None

    ответ = handle(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "list_inspections", "arguments": {}},
        },
        tenant=доступ.tenant,
        role=доступ.role,
        actor=доступ.actor,
    )

    assert ответ is not None
    assert ответ["result"].get("isError") is True, "контроль получил ответ инструмента проверок"
    assert "control" in ответ["result"]["content"][0]["text"]


def test_смена_роли_сужает_инструменты(учётки: dict[int, str]) -> None:
    """Админ УК видит проверки; понижен до контроля и перевыпустил — видит только рейтинги."""
    админ = mcp_config._owner_from_store(_выдать(АДМИН_УК))
    assert админ is not None and "list_inspections" in _инструменты(админ)

    set_role(f"tg-{АДМИН_УК}", tenant="HQ", role="control")
    контроль = mcp_config._owner_from_store(issue_token(АДМИН_УК).value)

    assert контроль is not None
    assert "list_inspections" not in _инструменты(контроль)


def test_личный_токен_снятия_не_даёт(учётки: dict[int, str]) -> None:
    доступ = mcp_config._owner_from_store(_выдать(АДМИН_УК))
    assert доступ is not None and доступ.may_retract is False
    assert доступ.actor == f"web:tg-{АДМИН_УК}", "подпись — логин учётки, как у входа OAuth"


# --- миграция `0059`: прежние токены и снятый круг ---------------------------------

МИГРАЦИЯ = "0059_mcp_token_identity.sql"


def _каталог(tmp_path: Path, *, включая: bool) -> Path:
    каталог = tmp_path / ("по" if включая else "до")
    каталог.mkdir()
    for файл in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if файл.name < МИГРАЦИЯ or (включая and файл.name == МИГРАЦИЯ):
            shutil.copy(файл, каталог / файл.name)
    return каталог


def test_миграция_связывает_привязанные_и_гасит_остальные(tmp_path: Path) -> None:
    """Связывается только токен с живой привязкой к живой учётке того же пространства."""
    хеш = password_hash("пароль-учётки-теста")
    with empty_database() as dsn:
        apply_migrations(dsn, directory=_каталог(tmp_path, включая=False))
        with psycopg.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("insert into tenants (code) values ('HQ'), ('GE') on conflict do nothing")
            учётка: dict[str, object] = {}
            for логин, пространство, роль in (
                ("svyazan", "HQ", "admin"),
                ("otklyuchen", "HQ", "admin"),
                ("drugoe", "GE", "admin"),
            ):
                cur.execute(
                    "insert into web_users (tenant_code, login, password_hash, role) "
                    "values (%s, %s, %s, %s) returning id",
                    (пространство, логин, хеш, роль),
                )
                строка = cur.fetchone()
                assert строка is not None
                учётка[логин] = строка[0]
            cur.execute("update web_users set disabled_at = now() where login = 'otklyuchen'")
            for tg, логин in ((1, "svyazan"), (2, "otklyuchen"), (3, "drugoe")):
                cur.execute(
                    "insert into bot_bindings (telegram_id, user_id) values (%s, %s)",
                    (tg, учётка[логин]),
                )
            # 1 — связывается; 2 — учётка отключена; 3 — пространство токена не то;
            # 4 — привязки нет вовсе; 5 — уже отозван и остаётся как был.
            for tg, пространство in ((1, "HQ"), (2, "HQ"), (3, "HQ"), (4, "HQ"), (5, "HQ")):
                cur.execute(
                    "insert into mcp_tokens (telegram_id, tenant_code, fingerprint) "
                    "values (%s, %s, %s)",
                    (tg, пространство, f"{tg:064x}"),
                )
            cur.execute(
                "update mcp_tokens set revoked_at = now(), revoked_by = 7 where telegram_id = 5"
            )
            # Круг с живым участником — как на проде: таблица уходит вместе со строкой.
            cur.execute("insert into mcp_admins (telegram_id) values (1)")

        применено = apply_migrations(dsn, directory=_каталог(tmp_path, включая=True))

        assert применено == [МИГРАЦИЯ]
        with psycopg.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "select telegram_id, user_id is not null, role, expires_at > now(), "
                "revoked_at is null, revoked_by from mcp_tokens order by telegram_id"
            )
            строки = cur.fetchall()
            cur.execute("select to_regclass('mcp_admins')")
            круг = cur.fetchone()
        assert круг == (None,), "круг доступа (mcp_admins) пережил миграцию"
        assert строки == [
            (1, True, "admin", True, True, None),
            (2, False, None, None, False, 0),
            (3, False, None, None, False, 0),
            (4, False, None, None, False, 0),
            (5, False, None, None, False, 7),
        ]
