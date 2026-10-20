"""Кто выбирает адрес для счётчика перебора, когда сервер слушает сеть контейнера.

F-038 и F-007 аудита 12.10. До правки в проде (`WEB_HOST=0.0.0.0`,
`WEB_TRUSTED_PROXIES=1`) `waitress` верил заголовкам звена от ЛЮБОГО соседа
(`trusted_proxy="*"`), и `client_address` брал то, что отправитель сам написал в
`X-Forwarded-For`: сосед, дотянувшийся до порта мимо прокси, менял ключ
счётчика на каждый запрос. Теперь звено называется адресом
(`WEB_TRUSTED_PROXY_ADDR`), а заголовки остальных режет `guard_forwarded`.

Чистый Python: ни базы, ни сети.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from flask import Flask

from src.web.config import (
    WEB_TRUSTED_PROXY_ADDR_VAR,
    Settings,
    load_settings,
    require_signing_key,
)
from src.web.errors import WebConfigError
from src.web.proxy import _proxy_options, guard_forwarded, peer_trusted
from src.web.remote import client_address

KEY = "signing-key-at-least-thirty-two-characters-long"
PEER = "172.18.0.5"  # сосед по docker-сети, не прокси
PROXY_NET = "172.19.0.0/16"  # сеть прокси, названная звеном


def _settings(*, trusted: int, host: str, addrs: tuple[str, ...] = ()) -> Settings:
    return Settings(
        host=host,
        port=8267,
        tenant="demo",
        ui_lang="ru",
        secret_key=KEY,
        trusted_proxies=trusted,
        trusted_proxy_addrs=addrs,
    )


def _ключи(settings: Settings, peer: str, forged: tuple[str, ...]) -> set[str]:
    """Ключ счётчика для каждого подделанного `X-Forwarded-For` — сквозь обёртку звена."""
    app = Flask(__name__)
    seen: set[str] = set()

    @app.post("/login")
    def login() -> str:
        seen.add(client_address(trusted_proxies=settings.trusted_proxies))
        return ""

    app.wsgi_app = guard_forwarded(app.wsgi_app, settings)  # type: ignore[method-assign]
    client = app.test_client()
    for адрес in forged:
        client.post(
            "/login", headers={"X-Forwarded-For": адрес}, environ_base={"REMOTE_ADDR": peer}
        )
    return seen


def test_в_сети_контейнера_любой_сосед_звеном_не_становится() -> None:
    options = _proxy_options(_settings(trusted=1, host="0.0.0.0"))  # noqa: S104 -- так слушает прод
    assert options.get("trusted_proxy") != "*"


def test_сосед_не_выбирает_ключ_счётчика() -> None:
    settings = _settings(trusted=1, host="0.0.0.0", addrs=(PROXY_NET,))  # noqa: S104
    seen = _ключи(settings, PEER, ("198.51.100.1", "198.51.100.2", "198.51.100.3"))
    assert seen == {PEER}


def test_названное_звено_передаёт_адрес_клиента() -> None:
    settings = _settings(trusted=1, host="0.0.0.0", addrs=(PROXY_NET,))  # noqa: S104
    seen = _ключи(settings, "172.19.0.2", ("198.51.100.1", "198.51.100.2"))
    assert seen == {"198.51.100.1", "198.51.100.2"}


@pytest.mark.parametrize(
    ("peer", "addrs", "ok"),
    [
        ("172.19.3.4", ("172.19.0.0/16",), True),
        ("172.18.3.4", ("172.19.0.0/16",), False),
        ("10.0.0.7", ("172.19.0.0/16", "10.0.0.7"), True),
        ("не-адрес", ("172.19.0.0/16",), False),
        ("192.0.2.1", ("*",), True),
        ("192.0.2.1", (), False),
    ],
)
def test_звено_по_адресу_и_подсети(peer: str, addrs: tuple[str, ...], ok: bool) -> None:
    assert peer_trusted(peer, addrs) is ok


def _env(**extra: str) -> dict[str, str]:
    return {"WEB_TENANT": "demo", "WEB_SECRET_KEY": KEY, **extra}


def test_адрес_звена_читается_списком() -> None:
    settings = load_settings(_env(**{WEB_TRUSTED_PROXY_ADDR_VAR: " 172.19.0.0/16, 10.0.0.7 "}))
    assert settings.trusted_proxy_addrs == ("172.19.0.0/16", "10.0.0.7")


def test_кривой_адрес_звена_отказ_запуска() -> None:
    with pytest.raises(WebConfigError, match=WEB_TRUSTED_PROXY_ADDR_VAR):
        load_settings(_env(**{WEB_TRUSTED_PROXY_ADDR_VAR: "caddy"}))


def test_админка_в_сети_без_ключа_подписи_не_поднимается() -> None:
    """F-008: временный ключ в проде — выход всех при каждой выкатке."""
    settings = load_settings(
        {"WEB_TENANT": "demo", "WEB_HOST": "0.0.0.0", "WEB_LISTEN_NETWORK": "1"}  # noqa: S104
    )
    with pytest.raises(WebConfigError, match="WEB_SECRET_KEY"):
        require_signing_key(settings)


def test_на_петле_временный_ключ_законен() -> None:
    settings = load_settings({"WEB_TENANT": "demo"})
    assert settings.secret_key_is_ephemeral
    require_signing_key(settings)
    require_signing_key(replace(settings, secret_key_is_ephemeral=False, host="0.0.0.0"))  # noqa: S104


def test_прод_требует_адрес_звена_без_допускающего_умолчания() -> None:
    """F-038: прод-надстройка не подставляет `*` и не собирается без адреса звена."""
    from pathlib import Path

    строки = [
        строка
        for строка in Path("docker-compose.prod.yml").read_text(encoding="utf-8").splitlines()
        if строка.strip().startswith(f"{WEB_TRUSTED_PROXY_ADDR_VAR}:")
    ]
    assert len(строки) == 1, строки
    assert f"${{{WEB_TRUSTED_PROXY_ADDR_VAR}:?" in строки[0]
    assert ":-" not in строки[0] and "*" not in строки[0].split(":?")[0]


# --- F-107: ключ фронта проверяется и на origin ---------------------------------

FRONT = "front-key-for-tests-0123456789abcdef"
FRONT_HEADER = "X-Decimus-Front-Key"


def _адрес_клиента(front_key: str, headers: dict[str, str], peer: str = "172.19.0.2") -> str:
    settings = replace(
        _settings(trusted=1, host="0.0.0.0", addrs=(PROXY_NET,)),  # noqa: S104
        front_key=front_key,
    )
    app = Flask(__name__)
    seen: list[str] = []

    @app.get("/")
    def index() -> str:
        seen.append(client_address(trusted_proxies=settings.trusted_proxies))
        return ""

    app.wsgi_app = guard_forwarded(app.wsgi_app, settings)  # type: ignore[method-assign, assignment]
    app.test_client().get(
        "/",
        headers={"X-Forwarded-For": "198.51.100.9", **headers},
        environ_base={"REMOTE_ADDR": peer},
    )
    return seen[0]


def test_ключ_совпал_заголовкам_звена_верим() -> None:
    assert _адрес_клиента(FRONT, {FRONT_HEADER: FRONT}) == "198.51.100.9"


@pytest.mark.parametrize("headers", [{}, {FRONT_HEADER: "wrong"}, {FRONT_HEADER: ""}])
def test_ключ_задан_но_не_совпал_сосед_по_подсети_чужой(headers: dict[str, str]) -> None:
    assert _адрес_клиента(FRONT, headers) == "172.19.0.2"


def test_ключ_не_задан_доверие_по_подсети_и_одно_предупреждение(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("WARNING", logger="src.web.proxy"):
        assert _адрес_клиента("", {}) == "198.51.100.9"
    assert sum("WEB_FRONT_KEY" in r.getMessage() for r in caplog.records) == 1


def test_отказ_пишется_в_журнал_без_значения_ключа(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("WARNING", logger="src.web.proxy"):
        _адрес_клиента(FRONT, {FRONT_HEADER: "wrong-value"})
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "ключа фронта" in text
    assert FRONT not in text
    assert "wrong-value" not in text


def test_ключ_читается_из_окружения_и_не_светится_в_repr() -> None:
    settings = load_settings(_env(WEB_FRONT_KEY=f" {FRONT} "))
    assert settings.front_key == FRONT
    assert FRONT not in repr(settings)
    assert load_settings(_env()).front_key == ""
