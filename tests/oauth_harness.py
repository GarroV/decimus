"""Хранилище OAuth в памяти — для экранных наборов без базы (D417).

Подменяются только двери `src.db.oauth_store`, где живёт SQL. Правила —
адрес возврата, PKCE, решения об обмене кода и refresh (`judge_code`,
`judge_refresh`) — остаются продуктовыми: двойник зовёт их же. Подменить и
их значило бы проверять оснастку, а набор зеленел бы на снятом заслоне.

Живой путь до Postgres проверяет `tests/test_db_oauth_store.py`.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest

from src.db import oauth_store
from src.db.errors import OAuthGrantError
from src.db.oauth_store import (
    Client,
    CodeState,
    Connection,
    OAuthOwner,
    RefreshState,
    TokenPair,
    judge_code,
    judge_refresh,
)


@dataclass
class _Код:
    client: Client
    user_id: str
    redirect_uri: str
    challenge: str
    expires_at: datetime
    grant: str | None = None


@dataclass
class _Подключение:
    user_id: str
    client: Client
    created_at: datetime
    last_used_at: datetime | None = None
    revoked: bool = False


@dataclass
class _Токен:
    grant: str
    kind: str
    expires_at: datetime
    used: bool = False


@dataclass
class ПамятьOAuth:
    """То, что `oauth_store` держит в четырёх таблицах, — словарями."""

    clients: dict[str, Client] = field(default_factory=dict)
    codes: dict[str, _Код] = field(default_factory=dict)
    grants: dict[str, _Подключение] = field(default_factory=dict)
    tokens: dict[str, _Токен] = field(default_factory=dict)
    #: Учётки: id → (логин, пространство, роль). Отключённые — в `disabled`.
    accounts: dict[str, tuple[str, str, str]] = field(default_factory=dict)
    disabled: set[str] = field(default_factory=set)
    #: Откуда и когда заведён каждый клиент — для пределов регистрации.
    registered: dict[str, tuple[str, datetime]] = field(default_factory=dict)
    #: Сколько раз звали чистку.
    purges: int = 0
    _номер: itertools.count[int] = field(default_factory=lambda: itertools.count(1))

    def _новый(self) -> str:
        return f"{next(self._номер):08d}-0000-4000-8000-000000000000"

    def register_client(self, name: object, redirect_uris: list[str], *, address: str) -> Client:
        if not redirect_uris or not all(map(oauth_store.redirect_uri_allowed, redirect_uris)):
            raise OAuthGrantError("invalid_redirect_uri", "двойник: адрес не из разрешённых")
        клиент = Client(
            id=len(self.clients) + 1,
            client_id=f"client-{len(self.clients) + 1:016d}",
            client_name=oauth_store.clean_client_name(name),
            redirect_uris=tuple(redirect_uris),
        )
        self.clients[клиент.client_id] = клиент
        self.registered[клиент.client_id] = (address, datetime.now(UTC))
        return клиент

    def recent_clients(self, window: timedelta, *, address: str | None = None) -> int:
        с = datetime.now(UTC) - window
        return sum(
            1
            for откуда, когда in self.registered.values()
            if когда > с and (address is None or откуда == address)
        )

    def purge_stale(self) -> int:
        self.purges += 1
        return 0

    def find_client(self, client_id: str) -> Client | None:
        return self.clients.get(client_id)

    def issue_code(
        self,
        client: Client,
        *,
        user_id: str,
        redirect_uri: str,
        code_challenge: str,
        resource: str | None,
    ) -> str:
        if redirect_uri not in client.redirect_uris:
            raise OAuthGrantError("invalid_request", "двойник: адрес не у клиента")
        код = oauth_store.new_secret()
        self.codes[код] = _Код(
            client=client,
            user_id=user_id,
            redirect_uri=redirect_uri,
            challenge=code_challenge,
            expires_at=datetime.now(UTC) + oauth_store.CODE_TTL,
        )
        return код

    def _пара(self, grant: str) -> TokenPair:
        сейчас = datetime.now(UTC)
        access, refresh = oauth_store.new_secret(), oauth_store.new_secret()
        self.tokens[access] = _Токен(grant, "access", сейчас + oauth_store.ACCESS_TTL)
        self.tokens[refresh] = _Токен(grant, "refresh", сейчас + oauth_store.REFRESH_TTL)
        return TokenPair(access_token=access, refresh_token=refresh, expires_in=3600)

    def exchange_code(
        self, code: str, *, client_id: str, redirect_uri: str, verifier: str
    ) -> TokenPair:
        строка = self.codes.get(code)
        состояние = (
            None
            if строка is None
            else CodeState(
                client_id=строка.client.client_id,
                redirect_uri=строка.redirect_uri,
                code_challenge=строка.challenge,
                used=строка.grant is not None,
                alive=строка.expires_at > datetime.now(UTC),
                account_alive=строка.user_id not in self.disabled,
            )
        )
        решение = judge_code(
            состояние, client_id=client_id, redirect_uri=redirect_uri, verifier=verifier
        )
        if строка is not None and решение.revoke and строка.grant is not None:
            self.grants[строка.grant].revoked = True
        if решение.refusal is not None or строка is None:
            raise OAuthGrantError("invalid_grant", решение.refusal or "")
        grant = self._новый()
        self.grants[grant] = _Подключение(строка.user_id, строка.client, datetime.now(UTC))
        строка.grant = grant
        return self._пара(grant)

    def refresh_tokens(self, refresh_token: str, *, client_id: str) -> TokenPair:
        токен = self.tokens.get(refresh_token)
        if токен is not None and токен.kind != "refresh":
            токен = None
        подключение = None if токен is None else self.grants[токен.grant]
        состояние = (
            None
            if токен is None or подключение is None
            else RefreshState(
                client_id=подключение.client.client_id,
                used=токен.used,
                alive=токен.expires_at > datetime.now(UTC),
                grant_alive=not подключение.revoked,
                account_alive=подключение.user_id not in self.disabled,
            )
        )
        решение = judge_refresh(состояние, client_id=client_id)
        if подключение is not None and решение.revoke:
            подключение.revoked = True
        if решение.refusal is not None or токен is None:
            raise OAuthGrantError("invalid_grant", решение.refusal or "")
        токен.used = True
        return self._пара(токен.grant)

    def resolve_access_token(self, token: str) -> OAuthOwner | None:
        токен = self.tokens.get(token)
        if токен is None or токен.kind != "access" or токен.expires_at <= datetime.now(UTC):
            return None
        подключение = self.grants[токен.grant]
        if подключение.revoked or подключение.user_id in self.disabled:
            return None
        подключение.last_used_at = datetime.now(UTC)
        логин, пространство, роль = self.accounts.get(
            подключение.user_id, ("director", "HQ", "auditor")
        )
        return OAuthOwner(user_id=подключение.user_id, login=логин, tenant=пространство, role=роль)

    def list_connections(self, user_id: str) -> tuple[Connection, ...]:
        return tuple(
            Connection(
                id=номер,
                client_name=п.client.client_name,
                created_at=п.created_at,
                last_used_at=п.last_used_at,
            )
            for номер, п in self.grants.items()
            if п.user_id == user_id and not п.revoked
        )

    def revoke_connection(self, connection_id: str, *, user_id: str) -> bool:
        п = self.grants.get(connection_id)
        if п is None or п.user_id != user_id or п.revoked:
            return False
        п.revoked = True
        return True


ДВЕРИ = (
    "register_client",
    "recent_clients",
    "purge_stale",
    "find_client",
    "issue_code",
    "exchange_code",
    "refresh_tokens",
    "resolve_access_token",
    "list_connections",
    "revoke_connection",
)


def подменить_oauth(monkeypatch: pytest.MonkeyPatch) -> ПамятьOAuth:
    """Двери `oauth_store` — в память; правила остаются продуктовыми."""
    память = ПамятьOAuth()
    for имя in ДВЕРИ:
        monkeypatch.setattr(oauth_store, имя, getattr(память, имя))
    return память
