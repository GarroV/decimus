"""Уведомления в базе (#1129, D604, D614): события предписаний и чтение только своего (0090).

Ядро (кому что показывается — молчаливая ошибка тут выглядит как чужое предписание на
экране): запрос на согласование получают ВСЕ с ролью ОСБ, возврат, согласование и
черновик в почту — автор запроса; сам действующий себя не уведомляет; чтение, подсчёт и
отметка видят только строки своей учётки.

Две части. Первая идёт без базы, на курсоре-двойнике: она проверяет, КОМУ и ЧТО пишет
`prescriptions_write`. Вторая (`requires_db`) — настоящая таблица `0090`: права ролей,
изоляция по учётке и то, что уведомление ложится одной транзакцией с переходом.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from conftest import requires_db
from db_harness import set_retraction_env, привязать_страну, точка_справочника

from src.db import notifications as store
from src.db import prescriptions as rx
from src.db import prescriptions_write as rxw

# ── Часть 1: без базы, курсор-двойник ────────────────────────────────

ОСБ_1 = "11111111-0000-0000-0000-000000000001"
ОСБ_2 = "11111111-0000-0000-0000-000000000002"
АВТОР_КЛЮЧ = "22222222-0000-0000-0000-000000000001"
ТЕМА = "Предписание · Грузия"


class Курсор:
    """Курсор администратора истории: отвечает на три запроса событий и пишет вставки."""

    def __init__(self, *, автор: str = "dev-anna") -> None:
        self.автор = автор
        self.вставки: list[tuple[Any, ...]] = []
        self._ответ: list[tuple[Any, ...]] = []

    def execute(self, sql: str, params: Any = None) -> None:
        if sql.strip().startswith("insert into notifications"):
            self.вставки.append(tuple(params))
            self._ответ = []
        elif "from prescriptions where id" in sql:
            self._ответ = [(ТЕМА, self.автор)]
        elif "where role = %s" in sql:
            assert params == ("osb", "HQ"), "адресаты ОСБ ищутся в пространстве УК"
            self._ответ = [(ОСБ_1,), (ОСБ_2,)]
        elif "where login = %s" in sql:
            ключи = {"dev-anna": АВТОР_КЛЮЧ, "osb-1": ОСБ_1}
            найден = ключи.get(params[0])
            self._ответ = [(найден,)] if найден else []
        else:
            raise AssertionError(f"неожиданный запрос: {sql}")

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._ответ[0] if self._ответ else None

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._ответ


IDENT = "aaaaaaaa-0000-0000-0000-000000000001"


def test_запрос_на_согласование_получают_все_осб() -> None:
    курсор = Курсор()

    rxw._notify_event(курсор, rxw.NOTE_REQUESTED, IDENT, actor="dev-anna")  # type: ignore[arg-type]

    assert [строка[0] for строка in курсор.вставки] == [ОСБ_1, ОСБ_2]
    assert {строка[1] for строка in курсор.вставки} == {"rx_requested"}
    assert {строка[2] for строка in курсор.вставки} == {f"/osb?id={IDENT}"}
    assert json.loads(курсор.вставки[0][3]) == {"subject": ТЕМА, "by": "dev-anna"}


def test_осб_запросившая_согласование_сама_себя_не_уведомляет() -> None:
    курсор = Курсор(автор="osb-1")

    rxw._notify_event(курсор, rxw.NOTE_REQUESTED, IDENT, actor="osb-1")  # type: ignore[arg-type]

    assert [строка[0] for строка in курсор.вставки] == [ОСБ_2]


@pytest.mark.parametrize(
    "вид", [rxw.NOTE_RETURNED, rxw.NOTE_APPROVED, rxw.NOTE_ISSUED], ids=lambda v: v
)
def test_ответ_по_предписанию_получает_только_автор(вид: str) -> None:
    курсор = Курсор()

    rxw._notify_event(курсор, вид, IDENT, actor="osb-1")  # type: ignore[arg-type]

    assert [(строка[0], строка[1]) for строка in курсор.вставки] == [(АВТОР_КЛЮЧ, вид)]
    assert курсор.вставки[0][2] == f"/actions?tab=prescriptions&id={IDENT}"


def test_автор_согласовавший_свой_черновик_себя_не_уведомляет() -> None:
    курсор = Курсор(автор="dev-anna")

    rxw._notify_event(курсор, rxw.NOTE_APPROVED, IDENT, actor="dev-anna")  # type: ignore[arg-type]

    assert курсор.вставки == []


def test_автор_без_живой_учётки_не_роняет_переход() -> None:
    курсор = Курсор(автор="ушедший")

    rxw._notify_event(курсор, rxw.NOTE_RETURNED, IDENT, actor="osb-1")  # type: ignore[arg-type]

    assert курсор.вставки == []


def test_notify_схлопывает_повторы_и_пустой_набор_ничего_не_пишет() -> None:
    курсор = Курсор()

    записано = store.notify(курсор, [ОСБ_1, ОСБ_1, ОСБ_2], "rx_requested", "/osb", {})  # type: ignore[arg-type]
    пусто = store.notify(курсор, [], "rx_requested", "/osb", {})  # type: ignore[arg-type]

    assert (записано, пусто) == (2, 0)
    assert len(курсор.вставки) == 2


# ── Часть 2: настоящая таблица ───────────────────────────────────────

psycopg = pytest.importorskip("psycopg")

АВТОР = "dev-anna"
ОСБ = "osb-vera"
ОСБ_ВТОРАЯ = "osb-igor"
ГОСТЬ = "guest-oleg"


@pytest.fixture
def admin_env(db_env: str, monkeypatch: pytest.MonkeyPatch) -> str:
    return set_retraction_env(db_env, monkeypatch)


@pytest.fixture
def люди(pg_dsn: str, db_env: str, domain_env: Path, admin_env: str) -> dict[str, str]:
    """Учётки УК: автор-девелопер, две ОСБ и гость; ключи — как их знает база."""
    from src.db.web_access import password_hash

    точка_справочника("Batumi-1", country="GE", city="Batumi")
    привязать_страну(pg_dsn, tenant="GE", country="GE")
    хеш = password_hash("пароль-учётки-теста")
    ключи: dict[str, str] = {}
    with psycopg.connect(pg_dsn) as conn:
        conn.execute("insert into tenants (code) values ('HQ') on conflict do nothing")
        for логин, роль in (
            (АВТОР, "developer"),
            (ОСБ, "osb"),
            (ОСБ_ВТОРАЯ, "osb"),
            (ГОСТЬ, "guest"),
        ):
            строка = conn.execute(
                "insert into web_users (tenant_code, login, password_hash, role) "
                "values ('HQ', %s, %s, %s) returning id::text",
                (логин, хеш, роль),
            ).fetchone()
            assert строка is not None
            ключи[логин] = строка[0]
        conn.commit()
    return ключи


def _черновик() -> rx.Draft:
    from datetime import date, timedelta

    return rx.Draft(
        country="GE",
        due_on=date.today() + timedelta(days=30),
        recipients="ops@ge.example.com",
        subject=ТЕМА,
        body="Требуем устранить нарушения в срок.",
    )


@requires_db
def test_запрос_на_согласование_ложится_всем_осб_и_только_им(люди: dict[str, str]) -> None:
    ident = rxw.create_draft(_черновик(), actor=АВТОР, submit=True)

    for логин in (ОСБ, ОСБ_ВТОРАЯ):
        строки = store.list_for(люди[логин])
        assert [(s.kind, s.link) for s in строки] == [("rx_requested", f"/osb?id={ident}")]
        assert строки[0].params == {"subject": ТЕМА, "by": АВТОР}
    assert store.list_for(люди[АВТОР]) == [], "автор сам себя уведомил"
    assert store.list_for(люди[ГОСТЬ]) == [], "гость не ОСБ"


@requires_db
def test_возврат_и_согласование_уходят_автору(люди: dict[str, str]) -> None:
    ident = rxw.create_draft(_черновик(), actor=АВТОР, submit=True)

    rxw.return_to_author(ident, actor=ОСБ, comment="Уточните срок")
    rxw.request_review(ident, actor=АВТОР)
    rxw.approve(ident, actor=ОСБ)

    виды = [s.kind for s in store.list_for(люди[АВТОР])]
    assert sorted(виды) == ["rx_approved", "rx_returned"]


@requires_db
def test_читается_и_считается_только_своё(люди: dict[str, str]) -> None:
    rxw.create_draft(_черновик(), actor=АВТОР, submit=True)

    assert store.unread_count(люди[ОСБ]) == 1
    assert store.unread_count(люди[АВТОР]) == 0
    assert store.list_for(люди[ГОСТЬ]) == []


@requires_db
def test_чужое_не_отмечается_ни_по_номеру_ни_по_адресу(люди: dict[str, str]) -> None:
    ident = rxw.create_draft(_черновик(), actor=АВТОР, submit=True)
    чужая = store.list_for(люди[ОСБ])[0]

    assert store.mark_read(люди[ОСБ_ВТОРАЯ], чужая.id) is False
    assert store.mark_read_by_link(люди[ОСБ_ВТОРАЯ], f"/osb?id={ident}") == 1  # своя, не чужая
    assert store.unread_count(люди[ОСБ]) == 1, "отметка второй ОСБ задела первую"
    assert store.mark_read(люди[ОСБ], чужая.id) is True
    assert store.mark_read(люди[ОСБ], чужая.id) is False, "повторная отметка"
    assert store.unread_count(люди[ОСБ]) == 0


@requires_db
def test_отказ_перехода_не_оставляет_уведомления(люди: dict[str, str]) -> None:
    ident = rxw.create_draft(_черновик(), actor=АВТОР)

    with pytest.raises(Exception, match="на согласовании"):
        rxw.return_to_author(ident, actor=ОСБ, comment="не на согласовании")  # draft → отказ

    assert store.list_for(люди[АВТОР]) == []
    assert store.list_for(люди[ОСБ]) == []


@requires_db
def test_роль_приложения_не_переписывает_суть_уведомления(
    люди: dict[str, str], pg_dsn: str
) -> None:
    rxw.create_draft(_черновик(), actor=АВТОР, submit=True)
    from src.db.config import check_environment

    with psycopg.connect(check_environment().dsn) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("update notifications set link = '/x'")
        conn.rollback()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("delete from notifications")


@requires_db
def test_paused_plan_notifications_are_hidden_but_not_deleted(
    люди: dict[str, str], pg_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    rxw.create_draft(_черновик(), actor=АВТОР, submit=True)
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        assert store.notify(cur, [люди[ОСБ]], "plan_requested", "/actions?tab=plans") == 1
    assert store.unread_count(люди[ОСБ]) == 2
    monkeypatch.setenv("ACTION_PLANS_ENABLED", "0")
    assert store.unread_count(люди[ОСБ]) == 1
    assert not any(n.kind.startswith("plan_") for n in store.list_for(люди[ОСБ]))
    monkeypatch.setenv("ACTION_PLANS_ENABLED", "1")
    assert store.unread_count(люди[ОСБ]) == 2
    assert any(n.kind == "plan_requested" for n in store.list_for(люди[ОСБ]))
