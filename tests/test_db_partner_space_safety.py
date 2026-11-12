"""Защита пространства партнёра на уровне базы (D759, миграция `0132`).

Ядро доступа: ошибка тихая — пароль сменили, а ключ Claude жив; пространство
«заморожено», а в нём заведён новый вход; разморозка вернула тех, кого заморозили
раньше по одной. Идёт под ролями площадки (`db_env`), как остальные наборы базы.
"""

from __future__ import annotations

from typing import Any

import pytest
from conftest import requires_db
from db_harness import выпустить_токен_чата, привязать_бота

psycopg = pytest.importorskip("psycopg")

from src.db import mcp_access, partner_events, space_freeze  # noqa: E402
from src.db.errors import AccessError  # noqa: E402
from src.db.web_access import (  # noqa: E402
    acting_as,
    change_password,
    create_account,
    freeze_account,
    set_email,
    set_role,
    unfreeze_account,
)

pytestmark = requires_db

АДМИН_УК = 801
АДМИН_GE = 802
СОТРУДНИК_GE = 803
СОТРУДНИК_GE_2 = 804


@pytest.fixture
def учётки(pg_dsn: str, db_env: str, monkeypatch: pytest.MonkeyPatch) -> dict[int, str]:
    return {
        АДМИН_УК: привязать_бота(pg_dsn, monkeypatch, АДМИН_УК, tenant="HQ", role="admin"),
        АДМИН_GE: привязать_бота(pg_dsn, monkeypatch, АДМИН_GE, tenant="GE", role="admin"),
        СОТРУДНИК_GE: привязать_бота(pg_dsn, monkeypatch, СОТРУДНИК_GE, tenant="GE"),
        СОТРУДНИК_GE_2: привязать_бота(pg_dsn, monkeypatch, СОТРУДНИК_GE_2, tenant="GE"),
    }


def _логин(tg: int) -> str:
    return f"tg-{tg}"


def _выполнить(dsn: str, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall() if cur.description else []


# --- 1. пароль гасит ключ Claude -------------------------------------------------


def test_смена_пароля_отзывает_ключ_claude(учётки: dict[int, str]) -> None:
    токен = выпустить_токен_чата(АДМИН_GE).value
    assert mcp_access.resolve_token(токен) is not None

    assert change_password(_логин(АДМИН_GE), tenant="GE", password="новый-пароль-учётки-1") is True

    assert mcp_access.resolve_token(токен) is None, "ключ Claude пережил смену пароля"


def test_нейтральная_правка_ключ_не_трогает(учётки: dict[int, str], pg_dsn: str) -> None:
    токен = выпустить_токен_чата(АДМИН_GE).value

    _выполнить(pg_dsn, "update web_users set web_lang = 'en' where id = %s", (учётки[АДМИН_GE],))

    assert mcp_access.resolve_token(токен) is not None, "язык не должен гасить ключ"


# --- 2. заморозка пространства ---------------------------------------------------


def _живая(dsn: str, user_id: str) -> bool:
    return _выполнить(dsn, "select disabled_at is null from web_users where id = %s", (user_id,))[
        0
    ][0]


def test_заморозка_пространства_замораживает_всех_действующих_и_гасит_ключи(
    учётки: dict[int, str], pg_dsn: str
) -> None:
    токен = выпустить_токен_чата(СОТРУДНИК_GE).value

    число = space_freeze.freeze_space("GE", by=учётки[АДМИН_УК])

    assert число == 3
    assert not any(_живая(pg_dsn, учётки[tg]) for tg in (АДМИН_GE, СОТРУДНИК_GE, СОТРУДНИК_GE_2))
    assert _живая(pg_dsn, учётки[АДМИН_УК]), "заморозка пространства задела УК"
    assert mcp_access.resolve_token(токен) is None, "ключ Claude жив в замороженном пространстве"
    assert "GE" in space_freeze.frozen_spaces()
    assert space_freeze.frozen_spaces()["GE"].accounts == 3


def test_разморозка_возвращает_только_замороженных_кнопкой(
    учётки: dict[int, str], pg_dsn: str
) -> None:
    assert freeze_account(_логин(СОТРУДНИК_GE_2), tenant="GE") is True  # раньше, по одной

    assert space_freeze.freeze_space("GE", by=учётки[АДМИН_УК]) == 2
    assert space_freeze.unfreeze_space("GE") == 2

    assert _живая(pg_dsn, учётки[АДМИН_GE])
    assert _живая(pg_dsn, учётки[СОТРУДНИК_GE])
    assert not _живая(pg_dsn, учётки[СОТРУДНИК_GE_2]), "разморозка вернула замороженного по одной"
    assert space_freeze.frozen_spaces() == {}


def test_отдельная_заморозка_после_пространственной_переживает_разморозку_пространства(
    учётки: dict[int, str], pg_dsn: str
) -> None:
    space_freeze.freeze_space("GE", by=учётки[АДМИН_УК])

    assert freeze_account(_логин(СОТРУДНИК_GE), tenant="GE", by=учётки[АДМИН_УК]) is True
    assert space_freeze.unfreeze_space("GE") == 2

    assert not _живая(pg_dsn, учётки[СОТРУДНИК_GE]), "разморозка пространства оживила учётку"
    assert _живая(pg_dsn, учётки[АДМИН_GE])


def test_в_замороженном_пространстве_учётку_не_завести(учётки: dict[int, str]) -> None:
    space_freeze.freeze_space("GE", by=None)

    with pytest.raises(AccessError):
        create_account("novichok", tenant="GE", password="пароль-новичка-1234", role="auditor")


def test_в_замороженном_пространстве_отдельную_не_разморозить(учётки: dict[int, str]) -> None:
    space_freeze.freeze_space("GE", by=None)

    with pytest.raises(AccessError):
        unfreeze_account(_логин(СОТРУДНИК_GE), tenant="GE")


def test_ук_не_замораживается(учётки: dict[int, str], pg_dsn: str) -> None:
    with pytest.raises(AccessError):
        space_freeze.freeze_space("HQ", by=None)
    # И прямым вызовом функции базы тоже.
    with pytest.raises(psycopg.Error):
        _выполнить(pg_dsn, "select freeze_space('HQ', null)")
    assert _живая(pg_dsn, учётки[АДМИН_УК])


def test_повторная_заморозка_ничего_не_делает(учётки: dict[int, str]) -> None:
    space_freeze.freeze_space("GE", by=None)

    assert space_freeze.freeze_space("GE", by=None) == 0


def test_после_разморозки_учётку_снова_завести_можно(учётки: dict[int, str]) -> None:
    space_freeze.freeze_space("GE", by=None)
    space_freeze.unfreeze_space("GE")

    создана = create_account(
        "novichok", tenant="GE", password="пароль-новичка-1234", role="auditor"
    )

    assert создана.login == "novichok"


# --- 3. события пространств партнёров --------------------------------------------


def test_новый_админ_партнёра_записывается_с_автором(учётки: dict[int, str]) -> None:
    with acting_as(учётки[АДМИН_УК]):
        create_account("nino", tenant="GE", password="пароль-нино-1234", role="admin")

    события, всего = partner_events.unseen(учётки[АДМИН_УК])

    assert всего == len(события)
    нино = [e for e in события if e.login == "nino"]
    assert [(e.kind, e.tenant, e.actor) for e in нино] == [("admin_added", "GE", _логин(АДМИН_УК))]


def test_повышение_до_админа_и_смена_почты_записываются(учётки: dict[int, str]) -> None:
    before, _ = partner_events.unseen(учётки[АДМИН_УК])
    with acting_as(учётки[АДМИН_УК]):
        assert set_role(_логин(СОТРУДНИК_GE), tenant="GE", role="admin") is True
        assert set_email(_логин(СОТРУДНИК_GE_2), tenant="GE", email="a@mail.example") is True
        assert set_email(_логин(СОТРУДНИК_GE_2), tenant="GE", email="b@mail.example") is True

    события, _ = partner_events.unseen(учётки[АДМИН_УК])
    новые = {(e.kind, e.login) for e in события} - {(e.kind, e.login) for e in before}

    assert (("admin_added", _логин(СОТРУДНИК_GE))) in новые
    # Первая почта сразу после заведения — часть заведения, вторая — смена.
    assert (("email_changed", _логин(СОТРУДНИК_GE_2))) in новые


def test_в_ук_события_не_пишутся(учётки: dict[int, str]) -> None:
    create_account("new-hq-admin", tenant="HQ", password="пароль-ук-12345", role="admin")

    события, _ = partner_events.unseen(учётки[АДМИН_УК])

    assert all(e.tenant != "HQ" for e in события)


def test_видел_отмечается_у_каждого_отдельно(учётки: dict[int, str]) -> None:
    create_account("nino", tenant="GE", password="пароль-нино-1234", role="admin")
    первый, второй = учётки[АДМИН_УК], учётки[АДМИН_GE]
    событие = next(e for e in partner_events.unseen(первый)[0] if e.login == "nino")

    assert partner_events.mark_seen(первый, событие.id) is True

    assert all(e.id != событие.id for e in partner_events.unseen(первый)[0])
    assert any(e.id == событие.id for e in partner_events.unseen(второй)[0]), (
        "отметка одного скрыла событие у другого"
    )
