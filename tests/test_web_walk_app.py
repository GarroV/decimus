"""D373: мини-апп как приложение аудитора — настройки.

Ядро здесь — права: контролю мини-апп закрыт (D420, F-024), без подписи и без
привязанной учётки действий нет. Подключения Claude (MCP) в мини-аппе нет (D626):
токен выпускается только в вебе, поэтому и `mcp_issue`, и поле `mcp` в ответе
проверяются на отсутствие.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from test_web_walk import АУДИТОР, ТОКЕН, _приложение, подписать

from src.db.bot_links import NEVER_BOUND, Binding, Standing
from src.db.errors import DbError
from src.web import walk, walk_access, walk_settings
from src.web.walk_auth import APP_PATH, INIT_DATA_HEADER

КОЛЛЕГА = АУДИТОР + 1
ПОСТОРОННИЙ = АУДИТОР + 2
#: Аудитор пространства партнёра — со своей учёткой.
ПАРТНЁР = АУДИТОР + 3
#: Учётка роли «контроль» с привязанным ботом.
КОНТРОЛЬ = АУДИТОР + 5


class База:
    """Подмена выбора языка и режимов: запоминает, что с ней делали."""

    def __init__(self) -> None:
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


def test_главная_не_даёт_подключить_claude(база: База, monkeypatch: pytest.MonkeyPatch) -> None:
    """D626: пункта «Подключить Claude» в мини-аппе нет ни у кого; круга доступа тоже."""
    client = _клиент(monkeypatch)

    for кто in (АУДИТОР, КОЛЛЕГА):
        app = client.post(walk.DATA_PATH, data=подписать(кто), content_type="text/plain")
        assert app.status_code == 200 and app.get_json()["state"] == "none"
        assert "mcp" not in app.get_json()["app"], "выпуск токена вернулся в мини-апп"
        assert "circle" not in app.get_json()["app"], "круг доступа вернулся в мини-апп"
        assert app.get_json()["app"]["version"]


def test_язык_человека_сильнее_языка_стенда(база: База, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _клиент(monkeypatch)

    ответ = _действие(client, КОЛЛЕГА, op="lang", lang="en")

    assert ответ.status_code == 200 and база.язык == {КОЛЛЕГА: "en"}
    assert ответ.get_json()["lang"] == "en", "D303: выбор человека — первым"
    assert _действие(client, КОЛЛЕГА, op="lang", lang="xx").status_code == 422


@pytest.mark.parametrize("op", ["mcp_issue", "mcp_add", "mcp_revoke", "mcp_who", "stops"])
def test_выпуска_токена_и_действий_круга_больше_нет(
    база: База, monkeypatch: pytest.MonkeyPatch, op: str
) -> None:
    """D626: токен MCP мини-апп не выпускает; прежние действия круга сняты раньше."""
    client = _клиент(monkeypatch)

    assert _действие(client, АУДИТОР, op=op, id=КОЛЛЕГА).status_code == 400


def test_контролю_мини_апп_закрыт_словами(база: База, monkeypatch: pytest.MonkeyPatch) -> None:
    """F-024, D420: контроль с привязанным ботом не работает в поле — ни чтением, ни записью."""
    client = _клиент(monkeypatch)

    данные = client.post(walk.DATA_PATH, data=подписать(КОНТРОЛЬ), content_type="text/plain")
    запись = _действие(client, КОНТРОЛЬ, op="lang", lang="en")

    assert данные.status_code == 403 and данные.get_json()["error"] == "role"
    assert "проверок" in данные.get_json()["message"]
    assert запись.status_code == 403 and база.язык == {}


def test_база_молчит_отказ_словами(база: База, monkeypatch: pytest.MonkeyPatch) -> None:
    def молчит(*a: Any, **k: Any) -> None:
        raise DbError("нет базы")

    monkeypatch.setattr(walk_settings.bot_langs, "choose_lang", молчит)
    client = _клиент(monkeypatch)

    ответ = _действие(client, АУДИТОР, op="lang", lang="en")

    assert ответ.status_code == 503 and "нет базы" not in ответ.get_json()["message"]


def test_без_подписи_ничего(база: База, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _клиент(monkeypatch)
    assert client.post(APP_PATH, json={"op": "lang", "lang": "en"}).status_code == 401
    assert _действие(client, ПОСТОРОННИЙ, op="lang", lang="en").status_code == 401
    assert база.язык == {}


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
