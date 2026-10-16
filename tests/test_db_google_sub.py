"""Номер аккаунта Google (`sub`) держит учётку за одним аккаунтом (аудит 12.10, F-027).

Вход через Google сверял только строку почты. Почта у аккаунта Google не
постоянна: её меняют, домен Workspace переходит к другому владельцу, удалённый
адрес заводят заново. Для партнёров, где нет домена компании (`hd`), почта была
единственной привязкой. Теперь первый вход (или привязка в «Настройках»)
записывает `sub` за учёткой, а следующие входы сверяют его: другой аккаунт с
той же почтой учётку не получает. У действующих учёток `sub` дописывается при
следующем входе. Смена почты снимает `sub` — у новой почты свой аккаунт.
"""

from __future__ import annotations

import pytest
from conftest import requires_db
from db_harness import завести_пространства

psycopg = pytest.importorskip("psycopg")

from src.db import web_own_profile  # noqa: E402
from src.db.web_access import (  # noqa: E402
    authenticate,
    claim_google_sub,
    create_account,
    freeze_account,
    open_session,
    set_email,
)

pytestmark = requires_db

ТЕНАНТ = "rs"
ПАРОЛЬ = "верный-пароль-учётки"
ПОЧТА = "partner@example.com"
АККАУНТ = "110169484474386276334"
ДРУГОЙ = "205551234567890123456"


@pytest.fixture
def обе_роли(pg_dsn: str, db_env: str, monkeypatch: pytest.MonkeyPatch) -> str:
    """Заводит учётки владелец, входит приложение — как на площадке."""
    monkeypatch.setenv("DATABASE_ADMIN_URL", pg_dsn)
    завести_пространства(pg_dsn, ТЕНАНТ)
    return pg_dsn


@pytest.fixture
def с_почтой(обе_роли: str) -> str:
    create_account("anna", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    set_email("anna", tenant=ТЕНАНТ, email=ПОЧТА)
    return обе_роли


def _номер(dsn: str, login: str = "anna") -> str | None:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("select google_sub from web_users where login = %s", (login,))
        строка = cur.fetchone()
    assert строка is not None
    return строка[0]


def test_первый_вход_записывает_номер_аккаунта(с_почтой: str) -> None:
    assert _номер(с_почтой) is None, "у действующей учётки номер заполняется при входе"

    assert claim_google_sub(ПОЧТА, АККАУНТ) == "ok"

    assert _номер(с_почтой) == АККАУНТ


def test_следующий_вход_тем_же_аккаунтом_пускает(с_почтой: str) -> None:
    claim_google_sub(ПОЧТА, АККАУНТ)

    assert claim_google_sub(ПОЧТА, АККАУНТ) == "ok"


def test_другой_аккаунт_с_той_же_почтой_не_пускает(с_почтой: str) -> None:
    claim_google_sub(ПОЧТА, АККАУНТ)

    assert claim_google_sub(ПОЧТА, ДРУГОЙ) == "other"
    assert _номер(с_почтой) == АККАУНТ, "чужой аккаунт переписал номер учётки"


def test_незнакомая_и_замороженная_почта_не_сверяется(с_почтой: str) -> None:
    assert claim_google_sub("kto-ugodno@gmail.com", АККАУНТ) == "missing"
    freeze_account("anna", tenant=ТЕНАНТ)
    assert claim_google_sub(ПОЧТА, АККАУНТ) == "missing"
    assert _номер(с_почтой) is None


def test_смена_почты_админом_снимает_номер(с_почтой: str) -> None:
    claim_google_sub(ПОЧТА, АККАУНТ)

    set_email("anna", tenant=ТЕНАНТ, email="anna-new@example.com")

    assert _номер(с_почтой) is None
    assert claim_google_sub("anna-new@example.com", ДРУГОЙ) == "ok"


def test_та_же_почта_повторно_номер_не_снимает(с_почтой: str) -> None:
    claim_google_sub(ПОЧТА, АККАУНТ)

    set_email("anna", tenant=ТЕНАНТ, email=ПОЧТА)

    assert _номер(с_почтой) == АККАУНТ


def test_привязка_в_настройках_записывает_номер_и_снятие_его_снимает(обе_роли: str) -> None:
    create_account("anna", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    учётка = authenticate("anna", ПАРОЛЬ)
    assert учётка is not None
    сессия = open_session(учётка).token
    assert web_own_profile.begin_google_link(сессия, state="метка", ttl_seconds=600)

    итог = web_own_profile.finish_google_link(сессия, state="метка", email=ПОЧТА, subject=АККАУНТ)

    assert итог == "ok"
    assert _номер(обе_роли) == АККАУНТ
    assert claim_google_sub(ПОЧТА, ДРУГОЙ) == "other"
    assert web_own_profile.unlink_google(сессия, current=ПАРОЛЬ) == "ok"
    assert _номер(обе_роли) is None


def test_один_аккаунт_google_не_держит_две_живые_учётки(обе_роли: str) -> None:
    """Тот же аккаунт уже у другой живой учётки — привязка отвечает «занята»."""
    create_account("anna", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    set_email("anna", tenant=ТЕНАНТ, email=ПОЧТА)
    claim_google_sub(ПОЧТА, АККАУНТ)
    create_account("boris", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    учётка = authenticate("boris", ПАРОЛЬ)
    assert учётка is not None
    сессия = open_session(учётка).token
    web_own_profile.begin_google_link(сессия, state="метка", ttl_seconds=600)

    итог = web_own_profile.finish_google_link(
        сессия, state="метка", email="boris@example.com", subject=АККАУНТ
    )

    assert итог == "taken"
    assert _номер(обе_роли, "boris") is None
