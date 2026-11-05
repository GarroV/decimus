"""Журнал шагов обхода (D710, миграция `0119`) — уровень базы.

Ядро доступа: шаги видят только главный админ и админ УК; прочим функция чтения отдаёт
пустое, а прямого права на таблицу у роли приложения нет. Шаги находятся по чату, пространству
и дате обхода проверки, слитой в базу. Всё идёт под ролью приложения (`db_env`), как на
площадке. Требует живой базы: без неё набор пропускается, а пропуск — не зелёный.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from conftest import requires_db
from db_harness import завести_пространства, слить_проверку

psycopg = pytest.importorskip("psycopg")

from src.db import walk_log  # noqa: E402
from src.db.walk_log import WalkStep  # noqa: E402
from src.db.web_access import authenticate, create_account, open_session  # noqa: E402

pytestmark = requires_db

ПАРОЛЬ = "пароль-учётки-теста-d709-журнал-обхода"
ЧАТ = 424242
ДАТА = "2026-11-05"
ТОЧКА = "Brasov-1"


def _токен(логин: str, роль: str, tenant: str) -> str:
    create_account(логин, tenant=tenant, password=ПАРОЛЬ, role=роль)
    учётка = authenticate(логин, ПАРОЛЬ)
    assert учётка is not None
    return open_session(учётка, ip="198.51.100.1", user_agent="UA").token


@pytest.fixture
def токены(
    pg_dsn: str, db_env: str, domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> dict[str, str]:
    monkeypatch.setenv("DATABASE_ADMIN_URL", pg_dsn)
    завести_пространства(pg_dsn, "HQ", "RS")
    return {
        "super": _токен("sofia", "superadmin", "HQ"),
        "hq_admin": _токен("anna", "admin", "HQ"),
        "partner_admin": _токен("boris", "admin", "RS"),
        "developer": _токен("dev", "developer", "HQ"),
        "partner_auditor": _токен("vera", "auditor", "RS"),
    }


def _шаг(**kw: object) -> None:
    base: dict[str, object] = dict(
        chat_id=ЧАТ,
        step="class",
        outcome="ok",
        run_id="run-1",
        tenant="HQ",
        unit=ТОЧКА,
        visit_date=date.fromisoformat(ДАТА),
        words="повреждённая мусорка на улице",
        photos=1,
        item_code="TEH14",
        zone="outside",
        verdict="not_established",
        reason="не мешает работе",
        detail={"clarifications": 0},
        duration_ms=1500,
    )
    walk_log.record(WalkStep(**{**base, **kw}))  # type: ignore[arg-type]


def _проверка() -> str:
    return слить_проверку(unit=ТОЧКА, tenant="HQ", chat_id=ЧАТ, date=ДАТА)


def test_админы_видят_шаги_проверки_по_чату_пространству_и_дате(
    токены: dict[str, str],
) -> None:
    ident = _проверка()
    _шаг()
    _шаг(step="save", verdict="manual", level="D1", words="")
    _шаг(chat_id=ЧАТ + 1)
    _шаг(visit_date=date(2026, 11, 4))
    _шаг(tenant="RS")

    for кто in ("super", "hq_admin"):
        строки = walk_log.read(токены[кто], ident)
        assert [r.step for r in строки] == ["class", "save"], кто
        assert строки[0].item_code == "TEH14" and строки[0].detail == {"clarifications": 0}
        assert строки[0].verdict == "not_established" and строки[0].duration_ms == 1500


def test_остальным_журнал_не_отдаётся(токены: dict[str, str]) -> None:
    ident = _проверка()
    _шаг()

    for кто in ("partner_admin", "developer", "partner_auditor"):
        assert walk_log.read(токены[кто], ident) == (), кто
    assert walk_log.read("токен-без-сессии", ident) == ()


def test_у_роли_приложения_нет_права_читать_и_править_таблицу(
    токены: dict[str, str],
) -> None:
    from src.db.errors import AccessError
    from src.db.web_access import _connected

    _шаг()
    for запрос in (
        "select * from walk_log",
        "update walk_log set photos = 0",
        "delete from walk_log",
    ):
        with pytest.raises(AccessError, match="InsufficientPrivilege"):
            with _connected("проверка прав") as conn, conn.cursor() as cur:
                cur.execute(запрос)


def test_учётка_аудитора_подставляется_по_привязке_бота(токены: dict[str, str]) -> None:
    from src.db import bot_links

    ident = _проверка()
    учётка = authenticate("dev", ПАРОЛЬ)
    assert учётка is not None
    bot_links.redeem(bot_links.issue_link(учётка.id).token, telegram_id=ЧАТ)
    _шаг()

    (строка,) = walk_log.read(токены["super"], ident)

    assert строка.login == "dev"


def test_срок_хранения_тридцать_дней(токены: dict[str, str], pg_dsn: str) -> None:
    ident = _проверка()
    _шаг(words="свежий")
    _шаг(words="почти месяц")
    _шаг(words="старый")
    with psycopg.connect(pg_dsn) as conn:
        conn.execute(
            "update walk_log set occurred_at = now() - interval '29 days' "
            "where words = 'почти месяц'"
        )
        conn.execute(
            "update walk_log set occurred_at = now() - interval '31 days' where words = 'старый'"
        )

    убрано = walk_log.purge()

    assert убрано == 1
    assert [r.words for r in walk_log.read(токены["super"], ident)] == ["почти месяц", "свежий"]


def test_слишком_длинные_слова_усекаются_а_не_роняют_запись(токены: dict[str, str]) -> None:
    ident = _проверка()
    _шаг(words="я" * 5000, reason="п" * 4000)

    (строка,) = walk_log.read(токены["super"], ident)

    assert len(строка.words) == 2000 and len(строка.reason) == 1500
