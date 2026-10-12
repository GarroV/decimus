"""Чистые правила OAuth (D417): адрес возврата и PKCE — без базы.

Ядро: ошибка здесь не падает, а отдаёт код чужому адресу или пускает обмен без
доказательства, что меняет тот же клиент, что просил. Поэтому каждое правило
проверено и на годном, и на испорченном входе.
"""

from __future__ import annotations

import base64
import hashlib

import pytest

from src.db.oauth_store import (
    DEFAULT_CLIENT_NAME,
    MAX_CLIENT_NAME,
    challenge_valid,
    clean_client_name,
    fingerprint,
    is_loopback,
    new_secret,
    pkce_matches,
    redirect_uri_allowed,
)

VERIFIER = "v" * 43 + "-._~0123456789"


def _challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


@pytest.mark.parametrize(
    "адрес",
    [
        "https://claude.ai/api/mcp/auth_callback",
        "https://claude.com/api/mcp/auth_callback",
        "http://localhost:1/callback",
        "http://localhost:33418/callback",
        "http://127.0.0.1:65535/callback",
    ],
)
def test_адрес_claude_принимается(адрес: str) -> None:
    assert redirect_uri_allowed(адрес) is True


@pytest.mark.parametrize(
    "адрес",
    [
        "https://evil.com/api/mcp/auth_callback",
        "https://evil.com",
        "http://localhost.evil.com/callback",
        "http://localhost.evil.com:8080/callback",
        "http://127.0.0.1.evil.com:80/callback",
        "http://claude.ai/api/mcp/auth_callback",
        "https://claude.ai/api/mcp/auth_callback/../x",
        "https://claude.ai/api/mcp/auth_callback?x=1",
        "https://claude.ai.evil.com/api/mcp/auth_callback",
        "https://localhost:8080/callback",
        "http://localhost/callback",
        "http://localhost:0/callback",
        "http://localhost:65536/callback",
        "http://localhost:8080/callback/evil",
        "http://localhost:8080/other",
        "http://[::1]:8080/callback",
        "",
        None,
        42,
    ],
)
def test_чужой_адрес_отвергается(адрес: object) -> None:
    assert redirect_uri_allowed(адрес) is False


def test_петля_помечается_для_предупреждения() -> None:
    assert is_loopback("http://localhost:8080/callback")
    assert not is_loopback("https://claude.ai/api/mcp/auth_callback")


def test_pkce_верный_verifier_проходит() -> None:
    assert pkce_matches(VERIFIER, _challenge(VERIFIER)) is True


def test_pkce_чужой_verifier_отвергается() -> None:
    assert pkce_matches(VERIFIER + "x", _challenge(VERIFIER)) is False


def test_pkce_plain_отвергается() -> None:
    """`plain`: verifier равен challenge. S256 такое не пропускает."""
    вызов = "a" * 43

    assert challenge_valid(вызов)
    assert pkce_matches(вызов, вызов) is False


@pytest.mark.parametrize("verifier", ["", "короткий", "a" * 42, "a" * 129, "a b" * 20, None])
def test_pkce_кривой_verifier_отвергается(verifier: object) -> None:
    assert pkce_matches(verifier, _challenge("a" * 43)) is False


@pytest.mark.parametrize("вызов", ["", "a" * 42, "a" * 44, "a" * 42 + "=", None, 1])
def test_кривой_challenge_отвергается(вызов: object) -> None:
    assert challenge_valid(вызов) is False


def test_имя_клиента_чистится() -> None:
    assert clean_client_name("  Claude\n\x00 ") == "Claude"
    assert clean_client_name(None) == DEFAULT_CLIENT_NAME
    assert clean_client_name("\n") == DEFAULT_CLIENT_NAME
    assert len(clean_client_name("я" * 1000)) == MAX_CLIENT_NAME


def test_секрет_и_отпечаток() -> None:
    секрет = new_secret()

    assert len(секрет) >= 43
    assert fingerprint(секрет) == hashlib.sha256(секрет.encode()).hexdigest()
    assert секрет not in fingerprint(секрет)
