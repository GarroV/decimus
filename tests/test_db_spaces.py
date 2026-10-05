"""Волна 1 (#340): пространство и его страны заводит команда; опечатка не заводит новое."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import requires_db
from db_harness import admin_role_dsn

psycopg = pytest.importorskip("psycopg")

from src.db.errors import AccessError  # noqa: E402
from src.db.spaces import bind_countries, create_space, list_spaces, space_exists  # noqa: E402

pytestmark = requires_db


@pytest.fixture
def владелец(pg_dsn: str, db_env: str, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("DATABASE_ADMIN_URL", pg_dsn)
    if not space_exists("HQ"):
        create_space("HQ", name="УК")
    return pg_dsn


def test_пространство_и_страна_заводятся(владелец: str) -> None:
    create_space("GE", name="Партнёр Грузия")
    assert bind_countries("GE", ("GE",)) == ("GE",)
    строка = next(s for s in list_spaces() if s.code == "GE")
    assert (строка.name, строка.countries, строка.people) == ("Партнёр Грузия", ("GE",), 0)


@pytest.mark.parametrize("код", ["ge", "../hq", "", "Г1", "HQ", "default"])
def test_негодный_или_занятый_код_это_отказ(владелец: str, код: str) -> None:
    with pytest.raises(AccessError):
        create_space(код, name="х")


def test_код_без_учёта_регистра_занят(владелец: str) -> None:
    """Каталог методики — код строчными, поэтому DEMO и заведённое посевом demo делили бы один."""
    with psycopg.connect(владелец) as conn:
        conn.execute("insert into tenants (code) values ('demo') on conflict do nothing")
    with pytest.raises(AccessError, match="уже заведено"):
        create_space("DEMO", name="Ещё одно демо")


def test_страна_второго_партнёра_это_отказ(владелец: str) -> None:
    """D284: одна страна — один партнёр."""
    create_space("GE", name="Грузия")
    bind_countries("GE", ("GE",))
    create_space("G2", name="Второй")
    with pytest.raises(AccessError, match="GE"):
        bind_countries("G2", ("AM", "GE"))
    assert next(s for s in list_spaces() if s.code == "G2").countries == (), "всё или ничего"


def test_повторная_привязка_своей_страны_не_ошибка(владелец: str) -> None:
    create_space("GE", name="Грузия")
    bind_countries("GE", ("GE",))
    assert bind_countries("GE", ("GE", "AM")) == ("AM", "GE")


def test_уК_не_привязывается_к_странам(владелец: str) -> None:
    with pytest.raises(AccessError):
        bind_countries("HQ", ("GE",))


def test_незаведённое_пространство_не_привязывается(владелец: str) -> None:
    with pytest.raises(AccessError):
        bind_countries("XX", ("GE",))


def test_негодный_код_страны_это_отказ(владелец: str) -> None:
    create_space("GE", name="Грузия")
    with pytest.raises(AccessError):
        bind_countries("GE", ("Georgia",))


# --- команды целиком: подпроцессом, как их зовёт `make` ----------------------

КОРЕНЬ = Path(__file__).resolve().parents[1]


def _команда(скрипт: str, *args: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 — аргументы наши, оболочки нет
        [sys.executable, str(КОРЕНЬ / "tools" / скрипт), *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=300,
    )


def _окружение(pg_dsn: str, db_env: str, **ещё: str) -> dict[str, str]:
    """Все три подключения — на одноразовую базу теста.

    Команда читает `.env` (`load_dotenv`, без перезаписи заданного), и
    незаданное здесь подключение приходит оттуда — из базы стенда. С #487 это
    отказ «Подключения ведут в разные базы», а до него было записью в чужую базу.
    """
    return {
        **os.environ,
        "DATABASE_ADMIN_URL": pg_dsn,
        "DATABASE_URL": db_env,
        "DATABASE_RETRACTION_URL": admin_role_dsn(db_env),
        **ещё,
    }


def test_команда_заводит_привязывает_и_перечисляет(владелец: str, db_env: str) -> None:
    env = _окружение(владелец, db_env)
    assert _команда("space.py", "add", "GE", "--name", "Партнёр Грузия", env=env).returncode == 0
    assert _команда("space.py", "countries", "GE", "GE", env=env).returncode == 0
    перечень = _команда("space.py", "list", env=env)
    assert перечень.returncode == 0
    assert "GE\tПартнёр Грузия\tстраны: GE" in перечень.stdout
    assert "HQ\t" in перечень.stdout and "страны: —" in перечень.stdout


def test_команда_отказывает_строкой(владелец: str, db_env: str) -> None:
    отказ = _команда("space.py", "add", "ge", "--name", "х", env=_окружение(владелец, db_env))
    assert отказ.returncode != 0 and "не годится" in отказ.stderr


def test_учётка_в_незаведённом_пространстве_не_заводится(владелец: str, db_env: str) -> None:
    """Опечатка в --tenant раньше молча заводила новое пустое пространство."""
    env = _окружение(владелец, db_env, WEB_USER_PASSWORD="длинный-пароль-стенда")
    отказ = _команда("web_user.py", "add", "director", "--tenant", "GEE", env=env)
    assert отказ.returncode != 0 and "Пространства «GEE» нет" in отказ.stderr
    assert not space_exists("GEE")


def test_посев_демо_это_пространство_партнёра_со_странами(
    владелец: str, db_env: str, tmp_path: Path
) -> None:
    """D287: демо — партнёр; его точки — в справочнике УК, проверки сливаются."""
    env = _окружение(
        владелец, db_env, SEED_WEB_DEMO_FORCE="1", DEMO_STATE_DIR=str(tmp_path / "state")
    )
    посев = _команда("seed_web_demo.py", env=env)
    assert посев.returncode == 0, посев.stderr[-2000:]
    демо = next(s for s in list_spaces() if s.code == "demo")
    assert демо.countries == ("GE", "RS")
    with psycopg.connect(владелец) as conn:
        чьи = conn.execute(
            "select distinct u.tenant_code from inspections i join units u on u.id = i.unit_id"
            " where i.tenant_code = 'demo'"
        ).fetchall()
    assert чьи == [("HQ",)], "точки демо — в едином справочнике УК"

    # D199: демо-история принята, кроме самой свежей — она показывает приёмку.
    # Повторный посев сносит и принятые: иначе второй запуск не начался бы.
    повтор = _команда("seed_web_demo.py", env=env)
    assert повтор.returncode == 0, повтор.stderr[-2000:]
    with psycopg.connect(владелец) as conn:
        статусы = conn.execute(
            "select status, count(*) from inspections where tenant_code = 'demo' "
            "group by status order by status"
        ).fetchall()
    assert dict(статусы).get("draft") == 1 and dict(статусы).get("finalized", 0) >= 1, статусы
