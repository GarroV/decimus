"""D373: мини-апп как приложение аудитора — настройки и круг доступа к MCP.

Ядро здесь — права: токен MCP выпускается только кругу и только на
пространство самого человека; приводить можно только тех, кого пускает бот;
основателя не отозвать. Ошибка тут молчалива — чужой получил бы токен ко всей
истории проверок, — поэтому проверяется каждое действие и его отказ.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from test_web_walk import АУДИТОР, ТОКЕН, _приложение, подписать

from src.db.bot_links import NEVER_BOUND
from src.db.errors import DbError
from src.db.mcp_access import AdminRow, IssuedToken, Revocation
from src.domain.tenants import HQ_TENANT
from src.web import walk, walk_access, walk_settings
from src.web.walk_auth import APP_PATH, INIT_DATA_HEADER

КОЛЛЕГА = АУДИТОР + 1
ПОСТОРОННИЙ = АУДИТОР + 2


class База:
    """Подмена `db.mcp_access` и выбора языка: запоминает, что с ней делали."""

    def __init__(self, круг: set[int]) -> None:
        self.круг = круг
        self.выпущено: list[tuple[int, str]] = []
        self.отозвано: list[int] = []
        self.язык: dict[int, str] = {}

    def is_admin(self, who: int) -> bool:
        return who in self.круг

    def add_admin(self, who: int, *, by: int | None) -> bool:
        новый = who not in self.круг
        self.круг.add(who)
        return новый

    def revoke_access(self, who: int, *, by: int) -> Revocation:
        self.отозвано.append(who)
        self.круг.discard(who)
        return Revocation(telegram_id=who, was_admin=True, tokens_revoked=0)

    def issue_token(self, who: int, *, tenant: str) -> IssuedToken:
        self.выпущено.append((who, tenant))
        return IssuedToken(value="tok-SECRET", tenant=tenant, replaced_previous=True)

    def list_admins(self) -> list[AdminRow]:
        return [
            AdminRow(
                telegram_id=who,
                added_by=None,
                added_at="2026-10-09T10:00:00",
                revoked_at=None,
                revoked_by=None,
                has_live_token=False,
            )
            for who in sorted(self.круг)
        ]


@pytest.fixture
def база(domain_env: Path, monkeypatch: pytest.MonkeyPatch) -> База:
    б = База(круг=set())
    for имя in ("is_admin", "add_admin", "revoke_access", "issue_token", "list_admins"):
        monkeypatch.setattr(walk_settings.mcp_access, имя, getattr(б, имя))
    monkeypatch.setattr(walk_settings.bot_langs, "chosen_lang", lambda who: б.язык.get(who))
    monkeypatch.setattr(
        walk_settings.bot_langs, "choose_lang", lambda who, lang: б.язык.__setitem__(who, lang)
    )
    monkeypatch.setattr(walk_access.bot_links, "standing", lambda _: NEVER_BOUND)
    monkeypatch.setattr(walk.queries, "previous_findings", lambda **_: None)
    return б


def _клиент(monkeypatch: pytest.MonkeyPatch) -> Any:
    return _приложение(
        monkeypatch,
        TELEGRAM_BOT_TOKEN=ТОКЕН,
        ALLOWED_TELEGRAM_IDS=f"{АУДИТОР},{КОЛЛЕГА}",
        BOT_MCP_OWNER_ID=str(АУДИТОР),
    ).test_client()


def _действие(client: Any, кто: int, **тело: Any) -> Any:
    return client.post(APP_PATH, json=тело, headers={INIT_DATA_HEADER: подписать(кто)})


def test_главная_знает_круг_и_версию(база: База, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _клиент(monkeypatch)

    моё = client.post(walk.DATA_PATH, data=подписать(АУДИТОР), content_type="text/plain")
    коллеги = client.post(walk.DATA_PATH, data=подписать(КОЛЛЕГА), content_type="text/plain")

    assert моё.status_code == 200 and моё.get_json()["state"] == "none"
    assert моё.get_json()["app"]["circle"] is True, "основатель в круге по настройке"
    assert коллеги.get_json()["app"]["circle"] is False
    assert моё.get_json()["app"]["version"]


def test_язык_человека_сильнее_языка_стенда(база: База, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _клиент(monkeypatch)

    ответ = _действие(client, КОЛЛЕГА, op="lang", lang="en")

    assert ответ.status_code == 200 and база.язык == {КОЛЛЕГА: "en"}
    assert ответ.get_json()["lang"] == "en", "D303: выбор человека — первым"
    assert _действие(client, КОЛЛЕГА, op="lang", lang="xx").status_code == 422


def test_токен_только_кругу(база: База, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _клиент(monkeypatch)

    ответ = _действие(client, КОЛЛЕГА, op="mcp_issue")

    assert ответ.status_code == 403 and база.выпущено == [], "токен ко всей истории — не каждому"


def test_токен_кругу_на_его_пространство(база: База, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _клиент(monkeypatch)

    ответ = _действие(client, АУДИТОР, op="mcp_issue")

    assert ответ.status_code == 200, ответ.get_json()
    assert база.выпущено == [(АУДИТОР, HQ_TENANT)], "сотрудник УК без привязки — пространство УК"
    assert "tok-SECRET" in ответ.get_json()["command"] and ответ.get_json()["replaced"] is True


def test_привести_можно_только_того_кого_пускает_бот(
    база: База, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _клиент(monkeypatch)

    чужой = _действие(client, АУДИТОР, op="mcp_add", id=ПОСТОРОННИЙ)
    свой = _действие(client, АУДИТОР, op="mcp_add", id=str(КОЛЛЕГА))

    assert чужой.status_code == 422 and ПОСТОРОННИЙ not in база.круг
    assert свой.status_code == 200 and КОЛЛЕГА in база.круг
    assert [r["id"] for r in свой.get_json()["circle"]] == sorted(база.круг)


def test_основателя_не_отозвать(база: База, monkeypatch: pytest.MonkeyPatch) -> None:
    база.круг.add(КОЛЛЕГА)
    client = _клиент(monkeypatch)

    основатель = _действие(client, КОЛЛЕГА, op="mcp_revoke", id=АУДИТОР)
    коллега = _действие(client, АУДИТОР, op="mcp_revoke", id=КОЛЛЕГА)

    assert основатель.status_code == 422 and АУДИТОР not in база.отозвано
    assert коллега.status_code == 200 and база.отозвано == [КОЛЛЕГА]


def test_вне_круга_список_и_отзыв_закрыты(база: База, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _клиент(monkeypatch)

    for тело in ({"op": "mcp_who"}, {"op": "mcp_revoke", "id": АУДИТОР}, {"op": "stops"}):
        assert _действие(client, КОЛЛЕГА, **тело).status_code == 403, тело
    assert база.отозвано == []


def test_база_молчит_отказ_словами(база: База, monkeypatch: pytest.MonkeyPatch) -> None:
    def молчит(*a: Any, **k: Any) -> None:
        raise DbError("нет базы")

    monkeypatch.setattr(walk_settings.mcp_access, "issue_token", молчит)
    client = _клиент(monkeypatch)

    ответ = _действие(client, АУДИТОР, op="mcp_issue")

    assert ответ.status_code == 503 and "нет базы" not in ответ.get_json()["message"]


def test_без_подписи_ничего(база: База, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _клиент(monkeypatch)
    assert client.post(APP_PATH, json={"op": "mcp_issue"}).status_code == 401
    assert _действие(client, ПОСТОРОННИЙ, op="mcp_issue").status_code == 401
    assert база.выпущено == []
