"""`dodois_status` (MCP): кто видит и что НЕ отдаётся.

Ядро — право: вкладку «Dodo IS» видит один главный админ УК (действие `keys.manage`), и
инструмент открыт ровно ему — в `tools/list` и на вызове. Второе ядро — секреты: ни токена, ни
хэша ссылки, ни почты учётки, ни ключей в ответе быть не должно. База подменена на уровне
`dodois_logins` и `dodois_metrics`.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from src.db import dodois_logins, dodois_metrics
from src.domain.dodois import Invite, Login
from src.mcp import dodois_read
from src.mcp.catalogue import find
from src.mcp.errors import ToolError
from src.mcp.policy import action_of
from src.mcp.rpc import handle

СЕЙЧАС = datetime.now(UTC)
СЕКРЕТЫ = ("TOKEN-SECRET-123", "hash-deadbeef", "boss@example.com", "client_secret")


def _вход(country: str) -> Login:
    return Login(
        country, "intl", "link", "garva", "Ivan Test", "boss@example.com",
        СЕЙЧАС - timedelta(days=3), "units", 12, 10, СЕЙЧАС - timedelta(hours=5),
        СЕЙЧАС + timedelta(hours=1), СЕЙЧАС - timedelta(minutes=30), "partial", None,
    )  # fmt: skip


def _ссылка(country: str, дней_назад: int, **kw: Any) -> Invite:
    выдана = СЕЙЧАС - timedelta(days=дней_назад)
    return Invite(
        1, country, "garva", выдана, выдана + timedelta(hours=24), kw.get("used_at"), None,
        "hash-deadbeef", "id-1", "superadmin", "HQ",
    )  # fmt: skip


@pytest.fixture
def база(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dodois_logins, "list_logins", lambda: (_вход("RS"),))
    monkeypatch.setattr(
        dodois_logins,
        "list_invites",
        lambda limit=30: (_ссылка("RS", 1, used_at=СЕЙЧАС), _ссылка("RS", 20), _ссылка("BG", 2)),
    )
    загрузка = СЕЙЧАС - timedelta(hours=1)
    monkeypatch.setattr(
        dodois_metrics,
        "kind_loads",
        lambda: [
            dodois_metrics.KindLoad("RS", "sales", загрузка, 40, загрузка, True, None),
            dodois_metrics.KindLoad("RS", "kr", загрузка, 9, загрузка, False, "http_503"),
        ],
    )
    monkeypatch.setattr(
        dodois_metrics,
        "country_data",
        lambda month: [dodois_metrics.CountryData("RS", 8, date(СЕЙЧАС.year, СЕЙЧАС.month, 1))],
    )


def _вызов(роль: str, tenant: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    ответ = handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "dodois_status", "arguments": arguments or {}},
        },
        tenant=tenant,
        checklist=None,
        source=None,
        may_retract=False,
        actor="x",
        role=роль,
    )
    assert ответ is not None
    return ответ["result"]


def _список(роль: str, tenant: str) -> set[str]:
    ответ = handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, tenant=tenant, role=роль)
    assert ответ is not None
    return {t["name"] for t in ответ["result"]["tools"]}


def test_действие_инструмента_то_же_что_у_вкладки() -> None:
    spec = find("dodois_status")
    assert spec is not None and action_of(spec) == "keys.manage"


@pytest.mark.parametrize(
    ("tenant", "роль", "видит"),
    [
        ("HQ", "superadmin", True),
        ("HQ", "admin", False),
        ("HQ", "developer", False),
        ("HQ", "control", False),
        ("HQ", "guest", False),
        ("HQ", "osb", False),
        ("RS", "admin", False),
        ("RS", "auditor", False),
    ],
)
def test_кто_видит_инструмент(база: None, tenant: str, роль: str, видит: bool) -> None:
    assert ("dodois_status" in _список(роль, tenant)) is видит
    ответ = _вызов(роль, tenant)
    assert bool(ответ.get("isError")) is (not видит)
    if not видит:
        assert "RS" not in json.dumps(ответ) and "Ivan" not in json.dumps(ответ)


def test_ответ_без_секретов_и_с_данными(база: None) -> None:
    ответ = _вызов("superadmin", "HQ")
    assert not ответ.get("isError")
    текст = json.dumps(ответ, ensure_ascii=False)
    for секрет in СЕКРЕТЫ:
        assert секрет not in текст
    for поле in ("token_hash", "account_email", "access_token", "refresh_token"):
        assert поле not in текст
    данные = dodois_read.dodois_status(tenant="HQ")
    страны = {c["country"]: c for c in данные["countries"]}  # type: ignore[attr-defined]
    rs = страны["RS"]
    assert rs["connected"] and rs["state"] == "partial" and rs["account_name"] == "Ivan Test"
    assert [i["status"] for i in rs["invites_last_7_days"]] == ["used"]
    assert rs["data"]["units_with_data"] == 8
    assert {x["kind"]: x["last_attempt_error"] for x in rs["data_loads"]} == {
        "sales": None,
        "kr": "http_503",
    }
    assert страны["BG"]["connected"] is False and len(страны["BG"]["invites_last_7_days"]) == 1


def test_страна_фильтруется_и_кривой_код_отказ(база: None) -> None:
    одна = dodois_read.dodois_status(tenant="HQ", country="rs")
    assert [c["country"] for c in одна["countries"]] == ["RS"]  # type: ignore[attr-defined]
    with pytest.raises(ToolError):
        dodois_read.dodois_status(tenant="HQ", country="Serbia")
