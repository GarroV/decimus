"""«Заморозить» и «Выйти везде» (D462, миграция `0063`) — уровень базы.

Ядро доступа: ошибка тихая — человека заморозили, а у него остаётся живая сессия,
подключение Claude, токен или бот. Каждая проверка идёт по ВСЕМ дверям, которыми
человек входит, под ролью приложения (`db_env`), как на площадке:

- веб — сессия (`resolve_session`);
- Claude — личный токен MCP и OAuth (код, access, refresh);
- бот — привязка и неиспользованная ссылка привязки.

Разморозка снимает только отметку: закрытое заморозкой не оживает — иначе
размороженный получил бы назад сессию и подключение, закрытые «на случай взлома».
"""

from __future__ import annotations

import base64
import hashlib
import shutil
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from conftest import requires_db
from db_harness import empty_database, привязать_бота

psycopg = pytest.importorskip("psycopg")

from src.db import bot_links, mcp_access  # noqa: E402
from src.db.errors import OAuthGrantError  # noqa: E402
from src.db.migrate import MIGRATIONS_DIR, apply_migrations  # noqa: E402
from src.db.oauth_store import (  # noqa: E402
    Client,
    RegistrationLimits,
    exchange_code,
    issue_code,
    refresh_tokens,
    register_client,
    resolve_access_token,
)
from src.db.web_access import (  # noqa: E402
    authenticate,
    freeze_account,
    list_accounts,
    open_session,
    password_hash,
    resolve_session,
    sign_out_everywhere,
    unfreeze_account,
)

pytestmark = requires_db

ТЕНАНТ = "HQ"
ПАРОЛЬ = "пароль-учётки-теста-d462"
ВОЗВРАТ = "https://claude.ai/api/mcp/auth_callback"
РЕСУРС = "https://mcp.example/mcp"
ПРЕДЕЛЫ = RegistrationLimits(window=timedelta(hours=1), per_address=100, total=1000)
VERIFIER = "x" * 64
CHALLENGE = (
    base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).rstrip(b"=").decode()
)
TELEGRAM = 7001
ЧУЖОЙ_TELEGRAM = 7002


class Человек:
    """Учётка со всеми дверями: сессия, токен MCP, Claude по OAuth, бот, ссылка привязки."""

    def __init__(self, user_id: str, login: str, клиент: Client, telegram: int) -> None:
        self.id = user_id
        self.login = login
        self.telegram = telegram
        self.клиент = клиент
        self.сессия = ""
        self.токен_mcp = ""
        self.access = ""
        self.refresh = ""
        self.ссылка = ""
        self.код = ""

    def открыть_всё(self) -> None:
        """Выдать все двери заново: у учётки уже есть привязка бота (`привязать_бота`)."""
        учётка = authenticate(self.login, ПАРОЛЬ)
        assert учётка is not None, "вход учётки перед заморозкой не сработал"
        self.сессия = open_session(учётка).token
        self.токен_mcp = mcp_access.issue_for_account(self.id).value
        пара = exchange_code(
            issue_code(
                self.клиент,
                user_id=self.id,
                redirect_uri=ВОЗВРАТ,
                code_challenge=CHALLENGE,
                resource=РЕСУРС,
            ),
            client_id=self.клиент.client_id,
            redirect_uri=ВОЗВРАТ,
            verifier=VERIFIER,
        )
        self.access, self.refresh = пара.access_token, пара.refresh_token
        # Ещё не обменянный код: после заморозки он не должен дать новое подключение.
        self.код = issue_code(
            self.клиент,
            user_id=self.id,
            redirect_uri=ВОЗВРАТ,
            code_challenge=CHALLENGE,
            resource=РЕСУРС,
        )
        self.ссылка = bot_links.issue_link(self.id).token

    def живое(self) -> dict[str, bool]:
        """Какими дверями человек ещё входит — по одному ответу на дверь."""
        return {
            "веб": resolve_session(self.сессия) is not None,
            "токен MCP": mcp_access.resolve_token(self.токен_mcp) is not None,
            "Claude access": resolve_access_token(self.access, resource=РЕСУРС) is not None,
            "Claude refresh": self._refresh_работает(),
            "Claude код": self._код_работает(),
            "бот": bot_links.resolve(self.telegram) is not None,
            "ссылка привязки": bot_links.redeem(self.ссылка, telegram_id=9999) is not None,
        }

    def _refresh_работает(self) -> bool:
        try:
            refresh_tokens(self.refresh, client_id=self.клиент.client_id, resource=РЕСУРС)
        except OAuthGrantError:
            return False
        return True

    def _код_работает(self) -> bool:
        try:
            exchange_code(
                self.код,
                client_id=self.клиент.client_id,
                redirect_uri=ВОЗВРАТ,
                verifier=VERIFIER,
            )
        except OAuthGrantError:
            return False
        return True


#: Каждая дверь — отдельный тест: пока проверка шла одним словарём, поломка одного
#: шага заморозки пряталась за первой же упавшей дверью (замер на испорченной копии).
ДВЕРИ = (
    "веб",
    "токен MCP",
    "Claude access",
    "Claude refresh",
    "Claude код",
    "бот",
    "ссылка привязки",
)


@pytest.fixture
def клиент(pg_dsn: str, db_env: str, monkeypatch: pytest.MonkeyPatch) -> Client:
    return register_client("Claude", [ВОЗВРАТ], address="203.0.113.5", limits=ПРЕДЕЛЫ)


def _человек(
    pg_dsn: str, monkeypatch: pytest.MonkeyPatch, клиент: Client, логин: str, telegram: int
) -> Человек:
    """Учётка администратора УК с привязанным ботом; пароль нужен для входа."""
    # `привязать_бота` заводит учётку со своим паролем; нужный нам пароль ставит
    # смена командой — она же закрывает сессии, поэтому дальше всё открывается заново.
    from src.db.web_access import change_password

    user_id = привязать_бота(
        pg_dsn, monkeypatch, telegram, tenant=ТЕНАНТ, role="admin", login=логин
    )
    change_password(логин, tenant=ТЕНАНТ, password=ПАРОЛЬ)
    человек = Человек(user_id, логин, клиент, telegram)
    человек.открыть_всё()
    return человек


@pytest.fixture
def анна(pg_dsn: str, monkeypatch: pytest.MonkeyPatch, клиент: Client) -> Человек:
    return _человек(pg_dsn, monkeypatch, клиент, "anna", TELEGRAM)


@pytest.fixture
def борис(pg_dsn: str, monkeypatch: pytest.MonkeyPatch, клиент: Client) -> Человек:
    return _человек(pg_dsn, monkeypatch, клиент, "boris", ЧУЖОЙ_TELEGRAM)


def _строка(dsn: str, sql: str, *params: Any) -> tuple[Any, ...]:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    assert row is not None
    return row


# --- заморозка закрывает ВСЕ двери --------------------------------------------


def test_до_заморозки_все_двери_открыты(анна: Человек) -> None:
    assert анна.живое() == dict.fromkeys(ДВЕРИ, True)


@pytest.mark.parametrize("дверь", ДВЕРИ)
def test_заморозка_закрывает_дверь(анна: Человек, дверь: str) -> None:
    assert freeze_account("anna", tenant=ТЕНАНТ)

    assert not анна.живое()[дверь], f"замороженный входит через дверь «{дверь}»"


def test_заморозка_пишет_след_в_базе(pg_dsn: str, анна: Человек, борис: Человек) -> None:
    freeze_account("anna", tenant=ТЕНАНТ, by=борис.id)

    причина, снято = _строка(
        pg_dsn,
        "select revoked_reason, revoked_at is not null from oauth_grants where user_id = %s",
        анна.id,
    )
    assert (причина, снято) == ("frozen", True)
    (отвязан,) = _строка(
        pg_dsn, "select unbound_at is not null from bot_bindings where user_id = %s", анна.id
    )
    assert отвязан
    (кем,) = _строка(pg_dsn, "select disabled_by from web_users where id = %s", анна.id)
    assert str(кем) == борис.id


def test_заморозка_одного_не_трогает_другого(анна: Человек, борис: Человек) -> None:
    freeze_account("anna", tenant=ТЕНАНТ)

    assert борис.живое() == dict.fromkeys(ДВЕРИ, True)


def test_заморозка_без_живой_учётки_отказывает(анна: Человек) -> None:
    assert freeze_account("anna", tenant=ТЕНАНТ)
    assert not freeze_account("anna", tenant=ТЕНАНТ), "повторная заморозка вернула успех"
    assert not freeze_account("nobody", tenant=ТЕНАНТ)


def test_охват_цели_держится_условием_в_запросе(анна: Человек) -> None:
    assert not freeze_account("anna", tenant=ТЕНАНТ, only_roles=("auditor",))
    assert анна.живое()["веб"], "заморозка вне охвата всё же сработала"
    assert freeze_account("anna", tenant=ТЕНАНТ, only_roles=("admin",))


def test_перечень_называет_кто_заморозил(анна: Человек, борис: Человек) -> None:
    freeze_account("anna", tenant=ТЕНАНТ, by=борис.id)

    строки = {r.login: r for r in list_accounts(tenant=ТЕНАНТ)}
    assert строки["anna"].disabled_by == "boris"
    assert строки["anna"].disabled_at is not None
    assert строки["boris"].disabled_by is None


# --- разморозка не оживляет закрытое -------------------------------------------


@pytest.mark.parametrize("дверь", ДВЕРИ)
def test_разморозка_не_оживляет_дверь(анна: Человек, борис: Человек, дверь: str) -> None:
    freeze_account("anna", tenant=ТЕНАНТ, by=борис.id)

    assert unfreeze_account("anna", tenant=ТЕНАНТ)

    assert not анна.живое()[дверь], (
        f"дверь «{дверь}» ожила после разморозки: заморозка её не закрыла насовсем"
    )


def test_разморозка_снимает_отметку_и_подпись(анна: Человек, борис: Человек) -> None:
    freeze_account("anna", tenant=ТЕНАНТ, by=борис.id)

    assert unfreeze_account("anna", tenant=ТЕНАНТ)

    assert authenticate("anna", ПАРОЛЬ) is not None, "размороженный не может войти заново"
    строки = {r.login: r for r in list_accounts(tenant=ТЕНАНТ)}
    assert строки["anna"].disabled_at is None and строки["anna"].disabled_by is None


def test_разморожен_человек_выпускает_доступ_заново(анна: Человек) -> None:
    freeze_account("anna", tenant=ТЕНАНТ)
    unfreeze_account("anna", tenant=ТЕНАНТ)

    учётка = authenticate("anna", ПАРОЛЬ)
    assert учётка is not None
    assert resolve_session(open_session(учётка).token) is not None
    assert mcp_access.resolve_token(mcp_access.issue_for_account(анна.id).value) is not None


def test_разморозка_живой_учётки_и_чужой_роли_отказывает(анна: Человек) -> None:
    assert not unfreeze_account("anna", tenant=ТЕНАНТ), "разморозили не замороженную"
    freeze_account("anna", tenant=ТЕНАНТ)
    assert not unfreeze_account("anna", tenant=ТЕНАНТ, only_roles=("auditor",))
    assert unfreeze_account("anna", tenant=ТЕНАНТ, only_roles=("admin",))


# --- «Выйти везде» ----------------------------------------------------------------


@pytest.mark.parametrize("дверь", [д for д in ДВЕРИ if д not in ("бот", "ссылка привязки")])
def test_выйти_везде_закрывает_дверь(анна: Человек, дверь: str) -> None:
    assert sign_out_everywhere(анна.сессия)

    assert not анна.живое()[дверь], f"после «выйти везде» дверь «{дверь}» открыта"


def test_выйти_везде_закрывает_сессию_на_другом_устройстве(анна: Человек) -> None:
    учётка = authenticate("anna", ПАРОЛЬ)
    assert учётка is not None
    вторая = open_session(учётка).token

    assert sign_out_everywhere(анна.сессия)

    assert resolve_session(вторая) is None


def test_выйти_везде_оставляет_бота_и_учётку(pg_dsn: str, анна: Человек) -> None:
    sign_out_everywhere(анна.сессия)

    assert bot_links.resolve(анна.telegram) is not None, "«выйти везде» отвязало бота"
    (причина,) = _строка(
        pg_dsn, "select revoked_reason from oauth_grants where user_id = %s", анна.id
    )
    assert причина == "user"
    (отключена,) = _строка(
        pg_dsn, "select disabled_at is not null from web_users where id = %s", анна.id
    )
    assert not отключена, "«выйти везде» заморозило учётку"


def test_выйти_везде_не_трогает_других(анна: Человек, борис: Человек) -> None:
    sign_out_everywhere(анна.сессия)

    assert борис.живое() == dict.fromkeys(ДВЕРИ, True)


def test_выйти_везде_по_мёртвой_сессии_ничего_не_делает(анна: Человек) -> None:
    assert not sign_out_everywhere("не-токен-сессии")
    assert анна.живое()["веб"]
    assert sign_out_everywhere(анна.сессия)
    assert not sign_out_everywhere(анна.сессия), "закрытая сессия снова что-то закрыла"


def test_после_выйти_везде_входит_заново(анна: Человек) -> None:
    sign_out_everywhere(анна.сессия)

    учётка = authenticate("anna", ПАРОЛЬ)
    assert учётка is not None
    assert resolve_session(open_session(учётка).token) is not None


# --- сбой одного шага и возврат учётки: всё закрывается и не оживает ---------------


@pytest.mark.parametrize("дверь", ДВЕРИ)
def test_отключение_мимо_триггера_разморозка_закрывает_всё(
    pg_dsn: str, анна: Человек, дверь: str
) -> None:
    """Отключение, сделанное до `0063` или мимо триггера, не должно воскреснуть при разморозке."""
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute("alter table web_users disable trigger web_users_freeze_cascade")
        cur.execute(
            "alter table web_users disable trigger web_users_access_change_revokes_mcp_tokens"
        )
        cur.execute("update web_users set disabled_at = now() where id = %s", (анна.id,))
        cur.execute("alter table web_users enable trigger web_users_freeze_cascade")
        cur.execute(
            "alter table web_users enable trigger web_users_access_change_revokes_mcp_tokens"
        )

    assert unfreeze_account("anna", tenant=ТЕНАНТ)

    assert not анна.живое()[дверь], f"дверь «{дверь}» пережила отключение мимо триггера"


@pytest.mark.parametrize("дверь", ["Claude access", "Claude refresh"])
def test_токен_oauth_не_оживает_даже_без_отметки_отзыва(
    pg_dsn: str, анна: Человек, дверь: str
) -> None:
    """Токены гаснут и сроком: снятая отметка отзыва подключения их не воскрешает."""
    freeze_account("anna", tenant=ТЕНАНТ)
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "update oauth_grants set revoked_at = null, revoked_reason = null where user_id = %s",
            (анна.id,),
        )
    unfreeze_account("anna", tenant=ТЕНАНТ)

    assert not анна.живое()[дверь]


def test_выйти_везде_гасит_и_срок_токенов_oauth(pg_dsn: str, анна: Человек) -> None:
    sign_out_everywhere(анна.сессия)

    (живых,) = _строка(
        pg_dsn,
        "select count(*) from oauth_tokens t join oauth_grants g on g.id = t.grant_id "
        "where g.user_id = %s and t.expires_at > now()",
        анна.id,
    )
    assert живых == 0


# --- накат `0063`: учётки, отключённые раньше -----------------------------------------

МИГРАЦИЯ = "0063_freeze.sql"


def _каталог(tmp_path: Path, *, включая: bool) -> Path:
    каталог = tmp_path / ("по" if включая else "до")
    каталог.mkdir()
    for файл in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if файл.name < МИГРАЦИЯ or (включая and файл.name == МИГРАЦИЯ):
            shutil.copy(файл, каталог / файл.name)
    return каталог


def test_накат_закрывает_всё_у_ранее_отключённых(tmp_path: Path) -> None:
    хеш = password_hash("пароль-учётки-теста")
    with empty_database() as dsn:
        apply_migrations(dsn, directory=_каталог(tmp_path, включая=False))
        with psycopg.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("insert into tenants (code) values ('HQ') on conflict do nothing")
            ids = {}
            for логин in ("stary", "zhivoy"):
                cur.execute(
                    "insert into web_users (tenant_code, login, password_hash, role) "
                    "values ('HQ', %s, %s, 'admin') returning id",
                    (логин, хеш),
                )
                ids[логин] = cur.fetchone()[0]  # type: ignore[index]
                cur.execute(
                    "insert into web_sessions (user_id, fingerprint, expires_at) "
                    "values (%s, %s, now() + interval '1 hour')",
                    (ids[логин], f"{len(ids):064x}"),
                )
                cur.execute(
                    "insert into bot_bindings (telegram_id, user_id) values (%s, %s)",
                    (len(ids), ids[логин]),
                )
            # Отключён ДО миграции: сессия и привязка бота остались живыми (`0059` гасил
            # только токены MCP).
            cur.execute("update web_users set disabled_at = now() where login = 'stary'")

        assert apply_migrations(dsn, directory=_каталог(tmp_path, включая=True)) == [МИГРАЦИЯ]

        with psycopg.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "select u.login, s.closed_at is not null, b.unbound_at is not null "
                "from web_users u join web_sessions s on s.user_id = u.id "
                "join bot_bindings b on b.user_id = u.id order by u.login"
            )
            assert cur.fetchall() == [("stary", True, True), ("zhivoy", False, False)]
