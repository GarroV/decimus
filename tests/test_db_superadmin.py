"""#585 (D364): главный админ и пространства партнёров с экрана — уровень базы.

Ядро прав. Здесь то, что держит база, а не экран:

* главный админ (`superadmin`) бывает только в УК — код и схема (`0041`);
* последнего действующего главного админа нельзя ни отключить, ни понизить —
  триггер на `web_users`, и это проверяется прямой записью мимо кода, и двумя
  транзакциями, снимающими друг друга одновременно;
* заслон «чью роль можно трогать» (`only_roles`) стоит в самом запросе записи:
  цель, сменившая роль между чтением перечня и записью, не правится;
* пространство партнёра с экрана заводится вместе со странами одной
  транзакцией, под той же ролью, что учётки (администратор истории, `0041`).

Прогон под ролью администратора истории — так ходит веб на площадке.
"""

from __future__ import annotations

import threading
from typing import Any

import pytest
from conftest import requires_db
from db_harness import set_retraction_env, завести_пространства

psycopg = pytest.importorskip("psycopg")

from src.db import spaces, web_access  # noqa: E402
from src.db.errors import AccessError  # noqa: E402

pytestmark = requires_db

ПАРОЛЬ = "длинный-пароль-1"


@pytest.fixture
def роль_веба(pg_dsn: str, db_env: str, monkeypatch: pytest.MonkeyPatch) -> str:
    """Учётки и пространства пишет администратор истории, как веб на площадке."""
    завести_пространства(pg_dsn, "GE")
    return set_retraction_env(db_env, monkeypatch)


def _живые_главные(pg_dsn: str) -> set[str]:
    with psycopg.connect(pg_dsn) as conn:
        строки = conn.execute(
            "select login from web_users where role = 'superadmin' and disabled_at is null"
        ).fetchall()
    return {str(r[0]) for r in строки}


def test_главный_админ_заводится_в_уК(роль_веба: str) -> None:
    учётка = web_access.create_account("boss", tenant="HQ", password=ПАРОЛЬ, role="superadmin")

    assert учётка.role == "superadmin"


def test_главный_админ_у_партнёра_отказ_кодом_и_схемой(роль_веба: str, pg_dsn: str) -> None:
    with pytest.raises(AccessError, match="только в пространстве УК"):
        web_access.create_account("boss", tenant="GE", password=ПАРОЛЬ, role="superadmin")
    web_access.create_account("nino", tenant="GE", password=ПАРОЛЬ, role="admin")

    with psycopg.connect(pg_dsn) as conn, pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("update web_users set role = 'superadmin' where login = 'nino'")


def test_главный_админ_назначает_другого(роль_веба: str, pg_dsn: str) -> None:
    web_access.create_account("boss", tenant="HQ", password=ПАРОЛЬ, role="superadmin")
    web_access.create_account("dev", tenant="HQ", password=ПАРОЛЬ, role="admin")

    assert web_access.reassign_role("dev", tenant="HQ", role="superadmin") == "admin"
    assert _живые_главные(pg_dsn) == {"boss", "dev"}


def test_последнего_главного_не_понизить(роль_веба: str, pg_dsn: str) -> None:
    web_access.create_account("boss", tenant="HQ", password=ПАРОЛЬ, role="superadmin")

    with pytest.raises(web_access.LastSuperadminError):
        web_access.reassign_role("boss", tenant="HQ", role="admin")
    assert _живые_главные(pg_dsn) == {"boss"}


def test_последнего_главного_не_отключить(роль_веба: str, pg_dsn: str) -> None:
    web_access.create_account("boss", tenant="HQ", password=ПАРОЛЬ, role="superadmin")

    with pytest.raises(web_access.LastSuperadminError):
        web_access.disable_account("boss", tenant="HQ")
    assert _живые_главные(pg_dsn) == {"boss"}


def test_последнего_главного_держит_база_а_не_код(роль_веба: str) -> None:
    """Прямая запись ролью веба мимо `web_access` — тот же отказ."""
    web_access.create_account("boss", tenant="HQ", password=ПАРОЛЬ, role="superadmin")

    with psycopg.connect(роль_веба) as conn:
        for запрос in (
            "update web_users set role = 'admin' where login = 'boss'",
            "update web_users set disabled_at = now() where login = 'boss'",
        ):
            with pytest.raises(psycopg.Error) as отказ:
                conn.execute(запрос)
            assert отказ.value.sqlstate == web_access.LAST_SUPERADMIN_SQLSTATE
            conn.rollback()


def test_последнего_главного_не_удалить_и_не_снять_всех_одной_командой(
    роль_веба: str, pg_dsn: str
) -> None:
    """Удаление и снятие нескольких строк одной командой — тот же отказ, даже владельцем схемы."""
    web_access.create_account("boss", tenant="HQ", password=ПАРОЛЬ, role="superadmin")
    web_access.create_account("dev", tenant="HQ", password=ПАРОЛЬ, role="superadmin")

    with psycopg.connect(pg_dsn) as conn:
        for запрос in (
            "delete from web_users where role = 'superadmin'",
            "update web_users set disabled_at = now() where role = 'superadmin'",
            "update web_users set role = 'admin' where role = 'superadmin'",
        ):
            with pytest.raises(psycopg.Error) as отказ:
                conn.execute(запрос)
            assert отказ.value.sqlstate == web_access.LAST_SUPERADMIN_SQLSTATE
            conn.rollback()
    assert _живые_главные(pg_dsn) == {"boss", "dev"}


def test_из_двух_главных_одного_снять_можно_второго_нет(роль_веба: str, pg_dsn: str) -> None:
    web_access.create_account("boss", tenant="HQ", password=ПАРОЛЬ, role="superadmin")
    web_access.create_account("dev", tenant="HQ", password=ПАРОЛЬ, role="superadmin")

    assert web_access.disable_account("dev", tenant="HQ") is True
    with pytest.raises(web_access.LastSuperadminError):
        web_access.reassign_role("boss", tenant="HQ", role="auditor")
    assert _живые_главные(pg_dsn) == {"boss"}


def test_двое_главных_снимают_друг_друга_одновременно(роль_веба: str, pg_dsn: str) -> None:
    """Гонка: каждая транзакция по отдельности видит второго главного живым.

    Без общей блокировки обе прошли бы проверку и закоммитились — главных
    админов не осталось бы ни одного. Первая держит блокировку до коммита,
    вторая ждёт и после коммита первой видит, что снимает последнего.
    """
    web_access.create_account("boss", tenant="HQ", password=ПАРОЛЬ, role="superadmin")
    web_access.create_account("dev", tenant="HQ", password=ПАРОЛЬ, role="superadmin")
    исход: dict[str, Any] = {}

    первая = psycopg.connect(роль_веба)
    первая.execute("update web_users set role = 'admin' where login = 'boss'")

    def вторая() -> None:
        with psycopg.connect(роль_веба) as conn:
            try:
                conn.execute("update web_users set role = 'admin' where login = 'dev'")
                conn.commit()
                исход["вторая"] = "прошла"
            except psycopg.Error as exc:
                исход["вторая"] = exc.sqlstate

    поток = threading.Thread(target=вторая)
    поток.start()
    поток.join(timeout=2)
    assert поток.is_alive(), "вторая транзакция не ждала первую — общей блокировки нет"
    первая.commit()
    первая.close()
    поток.join(timeout=30)

    assert исход["вторая"] == web_access.LAST_SUPERADMIN_SQLSTATE
    assert _живые_главные(pg_dsn) == {"dev"}


def test_снятие_не_главного_не_ждёт_и_не_мешает(роль_веба: str) -> None:
    """Триггер срабатывает только на главного: аудитора отключают как прежде."""
    web_access.create_account("petr", tenant="HQ", password=ПАРОЛЬ)

    assert web_access.disable_account("petr", tenant="HQ") is True


@pytest.mark.parametrize("дверь", ["role", "disable", "email"])
def test_чужая_роль_цели_не_правится_запросом(роль_веба: str, pg_dsn: str, дверь: str) -> None:
    """`only_roles` — условие в самом запросе: админа не тронет тот, кому он вне охвата."""
    web_access.create_account("dev", tenant="HQ", password=ПАРОЛЬ, role="admin")
    охват = ("auditor", "control")

    if дверь == "role":
        assert (
            web_access.reassign_role("dev", tenant="HQ", role="auditor", only_roles=охват) is None
        )
    elif дверь == "disable":
        assert web_access.disable_account("dev", tenant="HQ", only_roles=охват) is False
    else:
        assert (
            web_access.set_email("dev", tenant="HQ", email="dev@example.com", only_roles=охват)
            is False
        )

    with psycopg.connect(pg_dsn) as conn:
        строка = conn.execute(
            "select role, disabled_at, email from web_users where login = 'dev'"
        ).fetchone()
    assert строка == ("admin", None, None)


def test_охват_по_роли_пропускает_свою_цель(роль_веба: str) -> None:
    web_access.create_account("petr", tenant="HQ", password=ПАРОЛЬ)

    assert (
        web_access.reassign_role("petr", tenant="HQ", role="control", only_roles=("auditor",))
        == "auditor"
    )


def test_пространство_партнёра_заводится_со_странами(роль_веба: str) -> None:
    заведено = spaces.create_partner_space("AM", name="Партнёр", countries=("AM", "AZ"))

    assert заведено.code == "AM" and заведено.countries == ("AM", "AZ")
    строка = next(s for s in spaces.overview() if s.code == "AM")
    assert строка.countries == ("AM", "AZ") and строка.name == "Партнёр"


def test_занятая_страна_не_заводит_пространство_вовсе(роль_веба: str) -> None:
    spaces.create_partner_space("AM", name="", countries=("AM",))

    with pytest.raises(AccessError, match="AM"):
        spaces.create_partner_space("KZ", name="", countries=("KZ", "AM"))
    assert "KZ" not in {s.code for s in spaces.overview()}


@pytest.mark.parametrize(
    ("code", "countries"),
    [("HQ", ("UZ",)), ("hq", ("UZ",)), ("GE", ("UZ",)), ("X", ("UZ",)), ("UZ", ()), ("UZ", ("U",))],
)
def test_негодное_пространство_отказ(роль_веба: str, code: str, countries: tuple[str, ...]) -> None:
    with pytest.raises(AccessError):
        spaces.create_partner_space(code, name="", countries=countries)
    assert "UZ" not in {s.code for s in spaces.overview()}


def test_страны_добавляются_пространству_партнёра(роль_веба: str) -> None:
    spaces.create_partner_space("AM", name="", countries=("AM",))

    assert spaces.add_countries("AM", ("AZ",)) == ("AM", "AZ")
    with pytest.raises(AccessError):
        spaces.add_countries("HQ", ("UZ",))


def test_первого_главного_назначает_команда(
    роль_веба: str, pg_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Разовый бутстрап (docs/08-deploy.md): миграция никого не назначает, назначает команда.

    Все три подключения заданы явно ДО импорта команды: она читает `.env` при
    импорте, а `load_dotenv` не перезаписывает заданное — иначе запись ушла бы
    в базу стенда, а не в одноразовую.
    """
    import importlib
    import sys
    from pathlib import Path

    monkeypatch.setenv("DATABASE_ADMIN_URL", pg_dsn)
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "tools"))
    web_user = importlib.import_module("web_user")
    web_access.create_account("owner", tenant="HQ", password=ПАРОЛЬ, role="admin")

    assert web_user.main(["role", "owner", "superadmin", "--tenant", "HQ"]) == 0
    assert _живые_главные(pg_dsn) == {"owner"}
    sys.modules.pop("web_user", None)
