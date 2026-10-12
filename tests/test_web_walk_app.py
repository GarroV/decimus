"""D373: мини-апп как приложение аудитора — настройки и круг доступа к MCP.

Ядро здесь — права: токен MCP выпускается только кругу и только на учётку
самого человека; приводить можно только человека с ботом, привязанным к учётке
в охвате приводящего; основателя не отозвать; партнёр не видит и не трогает
людей УК (аудит 12.10, F-036); выдача и правка доступа — только по свежей
подписи (F-032); контролю мини-апп закрыт (D420, F-024). Ошибка тут молчалива —
чужой получил бы токен ко всей истории проверок, — поэтому проверяется каждое
действие и его отказ.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from test_web_walk import АУДИТОР, ТОКЕН, _приложение, подписать

from src.db.bot_links import NEVER_BOUND, Binding, Standing
from src.db.errors import DbError, OutOfScopeError, UnboundError
from src.db.mcp_access import AdminRow, IssuedToken, Revocation, in_scope
from src.web import walk, walk_access, walk_settings
from src.web.walk_auth import APP_PATH, INIT_DATA_HEADER, MINT_MAX_AGE_SECONDS

КОЛЛЕГА = АУДИТОР + 1
ПОСТОРОННИЙ = АУДИТОР + 2
#: Участник круга из пространства партнёра и его коллега там же.
ПАРТНЁР = АУДИТОР + 3
КОЛЛЕГА_ПАРТНЁРА = АУДИТОР + 4
#: Учётка роли «контроль» с привязанным ботом.
КОНТРОЛЬ = АУДИТОР + 5


class База:
    """Подмена `db.mcp_access` и выбора языка: запоминает, что с ней делали."""

    def __init__(self, круг: set[int]) -> None:
        self.круг = круг
        self.выпущено: list[int] = []
        self.отозвано: list[int] = []
        self.язык: dict[int, str] = {}
        #: Telegram ID → (пространство, роль) живой привязки к учётке.
        self.учётки: dict[int, tuple[str, str]] = {
            АУДИТОР: ("HQ", "admin"),
            КОЛЛЕГА: ("HQ", "auditor"),
            ПАРТНЁР: ("GE", "admin"),
            КОЛЛЕГА_ПАРТНЁРА: ("GE", "auditor"),
            КОНТРОЛЬ: ("HQ", "control"),
        }

    def _охват(self, who: int, within: str | None, *, bound: bool) -> None:
        """То же правило, что у базы (`mcp_access._require_scope`)."""
        space = self.учётки.get(who, (None, ""))[0]
        if not in_scope(within, space):
            raise OutOfScopeError("не ваше")
        if bound and space is None:
            raise UnboundError("нет привязки")

    def is_admin(self, who: int) -> bool:
        return who in self.круг

    def add_admin(self, who: int, *, by: int | None, within: str | None) -> bool:
        self._охват(who, within, bound=within is not None)
        новый = who not in self.круг
        self.круг.add(who)
        return новый

    def revoke_access(self, who: int, *, by: int, within: str | None) -> Revocation:
        self._охват(who, within, bound=False)
        self.отозвано.append(who)
        self.круг.discard(who)
        return Revocation(telegram_id=who, was_admin=True, tokens_revoked=0)

    def issue_token(self, who: int) -> IssuedToken:
        if who not in self.учётки:
            raise UnboundError("нет привязки")
        self.выпущено.append(who)
        space, role = self.учётки[who]
        return IssuedToken(
            value="tok-SECRET",
            tenant=space,
            role=role,
            expires_at=datetime(2026, 11, 11, tzinfo=UTC),
            replaced_previous=True,
        )

    def list_admins(self, *, within: str | None) -> list[AdminRow]:
        return [
            AdminRow(
                telegram_id=who,
                added_by=None,
                added_at="2026-10-09T10:00:00",
                revoked_at=None,
                revoked_by=None,
                has_live_token=False,
                space=self.учётки.get(who, (None, ""))[0],
            )
            for who in sorted(self.круг)
            if in_scope(within, self.учётки.get(who, (None, ""))[0])
        ]

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
    б = База(круг=set())
    for имя in ("is_admin", "add_admin", "revoke_access", "issue_token", "list_admins"):
        monkeypatch.setattr(walk_settings.mcp_access, имя, getattr(б, имя))
    monkeypatch.setattr(walk_settings.bot_langs, "chosen_lang", lambda who: б.язык.get(who))
    monkeypatch.setattr(
        walk_settings.bot_langs, "choose_lang", lambda who, lang: б.язык.__setitem__(who, lang)
    )
    monkeypatch.setattr(walk_access.bot_links, "standing", б.standing)
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
    assert база.выпущено == [АУДИТОР], "токен — на учётку самого человека"
    assert "tok-SECRET" in ответ.get_json()["command"] and ответ.get_json()["replaced"] is True
    assert ответ.get_json()["expires"] == "2026-11-11", "у токена срок, и он показан"
    assert ответ.headers["Cache-Control"] == "no-store", "команду с токеном не кэшировать"


def test_без_привязки_к_учётке_токен_не_выпускается(
    база: База, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Сотрудник УК по списку окружения, без учётки: бот его пускает, токена нет (аудит 12.10)."""
    del база.учётки[АУДИТОР]
    client = _клиент(monkeypatch)

    ответ = _действие(client, АУДИТОР, op="mcp_issue")

    assert ответ.status_code == 422 and база.выпущено == []
    assert "учётк" in ответ.get_json()["message"], "отказ объясняет, что нужна учётка"


def test_привести_можно_только_человека_с_учёткой(
    база: База, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _клиент(monkeypatch)

    чужой = _действие(client, АУДИТОР, op="mcp_add", id=ПОСТОРОННИЙ)
    свой = _действие(client, АУДИТОР, op="mcp_add", id=str(КОЛЛЕГА))

    assert чужой.status_code == 422 and ПОСТОРОННИЙ not in база.круг
    assert свой.status_code == 200 and КОЛЛЕГА in база.круг
    assert [r["id"] for r in свой.get_json()["circle"]] == sorted(база.круг)


def test_партнёр_не_видит_и_не_трогает_людей_уК(
    база: База, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F-036: круг поделён по пространствам. До фикса партнёр видел и отзывал всех."""
    база.круг.update({КОЛЛЕГА, ПАРТНЁР, КОЛЛЕГА_ПАРТНЁРА})
    client = _клиент(monkeypatch)

    список = _действие(client, ПАРТНЁР, op="mcp_who")
    отзыв_уК = _действие(client, ПАРТНЁР, op="mcp_revoke", id=КОЛЛЕГА)
    привод_уК = _действие(client, ПАРТНЁР, op="mcp_add", id=ПОСТОРОННИЙ)
    отзыв_своего = _действие(client, ПАРТНЁР, op="mcp_revoke", id=КОЛЛЕГА_ПАРТНЁРА)

    assert список.status_code == 200
    видно = {r["id"] for r in список.get_json()["circle"]}
    assert видно == {ПАРТНЁР, КОЛЛЕГА_ПАРТНЁРА}, "партнёру видны Telegram ID людей УК"
    assert отзыв_уК.status_code == 403 and КОЛЛЕГА not in база.отозвано
    assert привод_уК.status_code == 403 and ПОСТОРОННИЙ not in база.круг, (
        "партнёру «нет привязки» и «чужой» отвечают одинаково"
    )
    assert отзыв_своего.status_code == 200 and база.отозвано == [КОЛЛЕГА_ПАРТНЁРА]


def test_уК_видит_весь_круг(база: База, monkeypatch: pytest.MonkeyPatch) -> None:
    база.круг.update({КОЛЛЕГА, ПАРТНЁР})
    client = _клиент(monkeypatch)

    список = _действие(client, АУДИТОР, op="mcp_who")

    assert {r["id"] for r in список.get_json()["circle"]} == {АУДИТОР, КОЛЛЕГА, ПАРТНЁР}


def test_старая_подпись_не_выпускает_токен_и_не_правит_круг(
    база: База, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F-032: подпись старше пяти минут годна для записи проверки, но не для выдачи доступа."""
    client = _клиент(monkeypatch)
    старая = подписать(АУДИТОР, auth_date=int(time.time()) - MINT_MAX_AGE_SECONDS - 60)

    def с_подписью(**тело: Any) -> Any:
        return client.post(APP_PATH, json=тело, headers={INIT_DATA_HEADER: старая})

    выпуск = с_подписью(op="mcp_issue")
    привод = с_подписью(op="mcp_add", id=КОЛЛЕГА)
    отзыв = с_подписью(op="mcp_revoke", id=КОЛЛЕГА)
    язык = с_подписью(op="lang", lang="en")

    assert выпуск.status_code == 401 and база.выпущено == []
    assert "откройте" in выпуск.get_json()["message"].lower()
    assert привод.status_code == 401 and КОЛЛЕГА not in база.круг
    assert отзыв.status_code == 401 and база.отозвано == []
    assert язык.status_code == 200, "обычные действия живут по прежним шести часам"


def test_контролю_мини_апп_закрыт_словами(база: База, monkeypatch: pytest.MonkeyPatch) -> None:
    """F-024, D420: контроль с привязанным ботом не работает в поле — ни чтением, ни записью."""
    client = _клиент(monkeypatch)

    данные = client.post(walk.DATA_PATH, data=подписать(КОНТРОЛЬ), content_type="text/plain")
    запись = _действие(client, КОНТРОЛЬ, op="lang", lang="en")

    assert данные.status_code == 403 and данные.get_json()["error"] == "role"
    assert "проверок" in данные.get_json()["message"]
    assert запись.status_code == 403 and база.язык == {}


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
