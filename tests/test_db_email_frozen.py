"""Почта замороженной учётки не занята навсегда (аудит 12.10, F-031) — уровень базы.

Почта входа через Google уникальна только среди живых учёток. До починки
уникальный индекс держал и почту замороженной: человек, которого заморозили,
навсегда занимал свой адрес, и новую учётку на ту же почту завести было нельзя.
Разморозка обратно возвращает почту, только если её за это время не отдали
другой живой учётке; иначе — отказ с понятной причиной, а не сбой базы.
"""

from __future__ import annotations

import pytest
from conftest import requires_db
from db_harness import завести_пространства

psycopg = pytest.importorskip("psycopg")

from src.db import journals, web_own_profile  # noqa: E402
from src.db.errors import EmailTakenError  # noqa: E402
from src.db.web_access import (  # noqa: E402
    authenticate,
    create_account,
    find_by_email,
    freeze_account,
    open_session,
    set_email,
    unfreeze_account,
)

pytestmark = requires_db

ТЕНАНТ = "rs"
ПАРОЛЬ = "верный-пароль-учётки"
ПОЧТА = "ivan@dodobrands.io"


@pytest.fixture
def обе_роли(pg_dsn: str, db_env: str, monkeypatch: pytest.MonkeyPatch) -> str:
    """Заводит учётки владелец, входит приложение — как на площадке."""
    monkeypatch.setenv("DATABASE_ADMIN_URL", pg_dsn)
    завести_пространства(pg_dsn, ТЕНАНТ)
    return pg_dsn


@pytest.fixture
def замороженная_с_почтой(обе_роли: str) -> str:
    create_account("old", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    set_email("old", tenant=ТЕНАНТ, email=ПОЧТА)
    assert freeze_account("old", tenant=ТЕНАНТ)
    create_account("new", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    return обе_роли


def test_почту_замороженной_можно_дать_живой_учётке(замороженная_с_почтой: str) -> None:
    assert set_email("new", tenant=ТЕНАНТ, email=ПОЧТА), "почта замороженной занята навсегда"

    учётка = find_by_email(ПОЧТА)
    assert учётка is not None and учётка.login == "new"


def test_сам_человек_привязывает_почту_замороженной_в_настройках(
    замороженная_с_почтой: str,
) -> None:
    учётка = authenticate("new", ПАРОЛЬ)
    assert учётка is not None
    сессия = open_session(учётка).token
    assert web_own_profile.begin_google_link(сессия, state="метка", ttl_seconds=600)

    assert (
        web_own_profile.finish_google_link(
            сессия, state="метка", email=ПОЧТА, subject="sub-" + ПОЧТА
        )
        == "ok"
    )


def test_разморозка_с_занятой_почтой_отказывает_с_причиной(замороженная_с_почтой: str) -> None:
    set_email("new", tenant=ТЕНАНТ, email=ПОЧТА)

    with pytest.raises(EmailTakenError, match="почта"):
        unfreeze_account("old", tenant=ТЕНАНТ)

    assert authenticate("old", ПАРОЛЬ) is None, "отказ разморозки всё же разморозил"
    учётка = find_by_email(ПОЧТА)
    assert учётка is not None and учётка.login == "new"


def test_разморозка_со_свободной_почтой_возвращает_её(замороженная_с_почтой: str) -> None:
    assert unfreeze_account("old", tenant=ТЕНАНТ)

    учётка = find_by_email(ПОЧТА)
    assert учётка is not None and учётка.login == "old"


def test_исход_входа_по_почте_называет_живую_учётку(замороженная_с_почтой: str) -> None:
    """Две строки с одной почтой (замороженная и живая): журнал называет живую."""
    set_email("new", tenant=ТЕНАНТ, email=ПОЧТА)
    живая = authenticate("new", ПАРОЛЬ)
    assert живая is not None

    for _ in range(5):
        assert journals.failure_result(email=ПОЧТА)[0] == живая.id
