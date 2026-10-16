"""D373: мини-апп как приложение аудитора — настройки и подключение Claude.

Ядро здесь — права: токен MCP человек выпускает себе сам и только на СВОЮ
учётку, к которой привязан бот (D448: круга доступа нет); без учётки токена нет;
выпуск — только по свежей подписи (F-032); контролю мини-апп закрыт (D420,
F-024). Ошибка тут молчалива — чужой получил бы токен ко всей истории
проверок, — поэтому проверяется каждое действие и его отказ.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from test_web_walk import АУДИТОР, ТОКЕН, _приложение, подписать

from src.db.bot_links import NEVER_BOUND, Binding, Standing
from src.db.errors import DbError, UnboundError
from src.db.mcp_access import IssuedToken
from src.web import walk, walk_access, walk_settings
from src.web.walk_auth import APP_PATH, INIT_DATA_HEADER, MINT_MAX_AGE_SECONDS

КОЛЛЕГА = АУДИТОР + 1
ПОСТОРОННИЙ = АУДИТОР + 2
#: Аудитор пространства партнёра — со своей учёткой.
ПАРТНЁР = АУДИТОР + 3
#: Учётка роли «контроль» с привязанным ботом.
КОНТРОЛЬ = АУДИТОР + 5


class База:
    """Подмена `db.mcp_access` и выбора языка: запоминает, что с ней делали."""

    def __init__(self) -> None:
        self.выпущено: list[int] = []
        self.язык: dict[int, str] = {}
        self.режим: dict[int, str] = {}
        self.перевод: dict[int, str] = {}
        #: Telegram ID → (пространство, роль) живой привязки к учётке.
        self.учётки: dict[int, tuple[str, str]] = {
            АУДИТОР: ("HQ", "admin"),
            КОЛЛЕГА: ("HQ", "developer"),
            ПАРТНЁР: ("GE", "auditor"),
            КОНТРОЛЬ: ("HQ", "control"),
        }

    def issue_token(self, who: int) -> IssuedToken:
        if who not in self.учётки:
            raise UnboundError("нет привязки")
        self.выпущено.append(who)
        space, role = self.учётки[who]
        return IssuedToken(
            value=f"tok-SECRET-{who}",
            tenant=space,
            role=role,
            expires_at=datetime(2026, 11, 11, tzinfo=UTC),
            replaced_previous=True,
        )

    def standing(self, who: int) -> Standing:
        """Привязки бота: у кого из `учётки` она есть — живая; остальные — никогда."""
        if who not in self.учётки:
            return NEVER_BOUND
        space, role = self.учётки[who]
        return Standing.live(
            Binding(who, f"u-{who}", f"login-{who}", space, datetime.now(UTC), role)
        )


@pytest.fixture
def база(domain_env: Path, monkeypatch: pytest.MonkeyPatch) -> База:
    б = База()
    monkeypatch.setattr(walk_settings.mcp_access, "issue_token", б.issue_token)
    monkeypatch.setattr(walk_settings.bot_langs, "chosen_lang", lambda who: б.язык.get(who))
    monkeypatch.setattr(
        walk_settings.bot_langs, "choose_lang", lambda who, lang: б.язык.__setitem__(who, lang)
    )
    monkeypatch.setattr(
        walk_settings.finish_modes, "chosen_finish_mode", lambda who: б.режим.get(who)
    )
    monkeypatch.setattr(
        walk_settings.finish_modes,
        "choose_finish_mode",
        lambda who, mode: б.режим.__setitem__(who, mode),
    )
    monkeypatch.setattr(
        walk_settings.translate_modes, "chosen_translate_mode", lambda who: б.перевод.get(who)
    )
    monkeypatch.setattr(
        walk_settings.translate_modes,
        "choose_translate_mode",
        lambda who, mode: б.перевод.__setitem__(who, mode),
    )
    monkeypatch.setattr(walk_access.bot_links, "standing", б.standing)
    monkeypatch.setattr(walk.queries, "previous_findings", lambda **_: None)
    return б


def _клиент(monkeypatch: pytest.MonkeyPatch) -> Any:
    return _приложение(
        monkeypatch,
        TELEGRAM_BOT_TOKEN=ТОКЕН,
    ).test_client()


def _действие(client: Any, кто: int, **тело: Any) -> Any:
    return client.post(APP_PATH, json=тело, headers={INIT_DATA_HEADER: подписать(кто)})


def test_главная_даёт_подключить_claude_каждому(
    база: База, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D448: пункт «Подключить Claude» у всех, кого мини-апп пускает; круга нет."""
    client = _клиент(monkeypatch)

    моё = client.post(walk.DATA_PATH, data=подписать(АУДИТОР), content_type="text/plain")
    коллеги = client.post(walk.DATA_PATH, data=подписать(КОЛЛЕГА), content_type="text/plain")

    assert моё.status_code == 200 and моё.get_json()["state"] == "none"
    assert моё.get_json()["app"]["mcp"] is True
    assert коллеги.get_json()["app"]["mcp"] is True
    assert "circle" not in моё.get_json()["app"], "круг доступа вернулся в мини-апп"
    assert моё.get_json()["app"]["version"]


def test_язык_человека_сильнее_языка_стенда(база: База, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _клиент(monkeypatch)

    ответ = _действие(client, КОЛЛЕГА, op="lang", lang="en")

    assert ответ.status_code == 200 and база.язык == {КОЛЛЕГА: "en"}
    assert ответ.get_json()["lang"] == "en", "D303: выбор человека — первым"
    assert _действие(client, КОЛЛЕГА, op="lang", lang="xx").status_code == 422


@pytest.mark.parametrize("кто", [АУДИТОР, КОЛЛЕГА, ПАРТНЁР])
def test_каждый_выпускает_токен_себе_сам(
    база: База, monkeypatch: pytest.MonkeyPatch, кто: int
) -> None:
    """D448: никто никому не выдаёт — аудитор и партнёр выпускают себе, на свою учётку."""
    client = _клиент(monkeypatch)

    ответ = _действие(client, кто, op="mcp_issue")

    assert ответ.status_code == 200, ответ.get_json()
    assert база.выпущено == [кто], "токен — на учётку самого человека, по его подписи"
    assert f"tok-SECRET-{кто}" in ответ.get_json()["command"]
    assert ответ.get_json()["replaced"] is True
    assert ответ.get_json()["expires"] == "2026-11-11", "у токена срок, и он показан"
    assert ответ.headers["Cache-Control"] == "no-store", "команду с токеном не кэшировать"


def test_выпуск_не_принимает_чужой_id(база: База, monkeypatch: pytest.MonkeyPatch) -> None:
    """Кому выпускать, решает подпись Telegram, а не поле запроса."""
    client = _клиент(monkeypatch)

    ответ = _действие(client, КОЛЛЕГА, op="mcp_issue", id=АУДИТОР)

    assert ответ.status_code == 200 and база.выпущено == [КОЛЛЕГА]


@pytest.mark.parametrize("op", ["mcp_add", "mcp_revoke", "mcp_who", "stops"])
def test_действий_круга_больше_нет(база: База, monkeypatch: pytest.MonkeyPatch, op: str) -> None:
    client = _клиент(monkeypatch)

    assert _действие(client, АУДИТОР, op=op, id=КОЛЛЕГА).status_code == 400


def test_без_привязки_к_учётке_токен_не_выпускается(
    база: База, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Без учётки мини-апп не пускает вовсе (D520), и токена тем более нет (аудит 12.10)."""
    del база.учётки[АУДИТОР]
    client = _клиент(monkeypatch)

    ответ = _действие(client, АУДИТОР, op="mcp_issue")

    assert ответ.status_code == 401 and база.выпущено == []


def test_старая_подпись_не_выпускает_токен(база: База, monkeypatch: pytest.MonkeyPatch) -> None:
    """F-032: подпись старше пяти минут годна для записи проверки, но не для выпуска токена."""
    client = _клиент(monkeypatch)
    старая = подписать(АУДИТОР, auth_date=int(time.time()) - MINT_MAX_AGE_SECONDS - 60)

    def с_подписью(**тело: Any) -> Any:
        return client.post(APP_PATH, json=тело, headers={INIT_DATA_HEADER: старая})

    выпуск = с_подписью(op="mcp_issue")
    язык = с_подписью(op="lang", lang="en")

    assert выпуск.status_code == 401 and база.выпущено == []
    assert "откройте" in выпуск.get_json()["message"].lower()
    assert язык.status_code == 200, "обычные действия живут по прежним шести часам"


def test_контролю_мини_апп_закрыт_словами(база: База, monkeypatch: pytest.MonkeyPatch) -> None:
    """F-024, D420: контроль с привязанным ботом не работает в поле — ни чтением, ни записью."""
    client = _клиент(monkeypatch)

    данные = client.post(walk.DATA_PATH, data=подписать(КОНТРОЛЬ), content_type="text/plain")
    запись = _действие(client, КОНТРОЛЬ, op="lang", lang="en")
    выпуск = _действие(client, КОНТРОЛЬ, op="mcp_issue")

    assert данные.status_code == 403 and данные.get_json()["error"] == "role"
    assert "проверок" in данные.get_json()["message"]
    assert запись.status_code == 403 and база.язык == {}
    assert выпуск.status_code == 403 and база.выпущено == [], (
        "контроль подключает Claude на сайте, не в мини-аппе обхода"
    )


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


def test_ссылка_на_настройки_сайта_из_внешнего_адреса_админки(
    база: База, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D447: мини-апп ведёт в «Настройки» сайта, адрес берёт из `ADMIN_PUBLIC_URL`."""
    monkeypatch.setenv("ADMIN_PUBLIC_URL", "https://admin.example/")
    client = _клиент(monkeypatch)

    приложение = client.post(
        walk.DATA_PATH, data=подписать(АУДИТОР), content_type="text/plain"
    ).get_json()["app"]

    assert приложение["settings_url"] == "https://admin.example/settings"


def test_без_адреса_админки_ссылки_нет(база: База, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ADMIN_PUBLIC_URL", raising=False)
    client = _клиент(monkeypatch)

    приложение = client.post(
        walk.DATA_PATH, data=подписать(АУДИТОР), content_type="text/plain"
    ).get_json()["app"]

    assert приложение["settings_url"] is None
