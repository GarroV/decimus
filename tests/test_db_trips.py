"""Поездки «Календаря» разделены пространствами в самой базе (D505, `0074_trips.sql`).

Требование владельца (D505): поездки одного пространства не видны другому ни при
каком запросе. Здесь проверяется не фильтр в запросе продукта, а сама база: голый
`select` / `update` / `delete` / `insert` роли приложения от имени одного
пространства не видит и не трогает поездок и планов другого — и УК тоже не видит
поездок партнёра (в отличие от проверок, D283).

Набор сам доказывает, что ловит утечку: без политики чужое видно
(`test_без_политики_чужая_поездка_видна`).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from typing import Any

import pytest
from conftest import requires_db

psycopg = pytest.importorskip("psycopg")

from db_harness import привязать_пространства, точка_справочника  # noqa: E402

from src.db import trips as tr  # noqa: E402
from src.db.space import acting_space  # noqa: E402
from src.db.web_access import authenticate, create_account  # noqa: E402

pytestmark = requires_db

ПАРОЛЬ = "пароль-набора-поездок-длинный"
А, Б = "GE", "AM"


@contextmanager
def от_имени(dsn: str, space: str | None) -> Iterator[Any]:
    """Соединение роли приложения от имени `space`; `None` — пространство не поставлено."""
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    чистая = make_conninfo(**{k: v for k, v in conninfo_to_dict(dsn).items() if k != "options"})
    with psycopg.connect(чистая) as conn:
        if space is not None:
            conn.execute("select set_config('decimus.space', %s, false)", (space,))
            conn.commit()
        yield conn


@pytest.fixture
def мир(pg_dsn: str, db_env: str, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """По учётке и поездке с шагом у УК и у двух партнёров; их `id` по имени."""
    monkeypatch.setenv("DATABASE_ADMIN_URL", pg_dsn)
    привязать_пространства(pg_dsn, А, Б)
    with psycopg.connect(pg_dsn) as conn:
        conn.execute("insert into tenants (code) values ('HQ') on conflict do nothing")
    точки = {
        "ge": точка_справочника("Тбилиси-1", country=А),
        "am": точка_справочника("Ереван-1", country=Б),
    }
    ид: dict[str, str] = {**{f"unit_{k}": v for k, v in точки.items()}}
    for пространство in ("HQ", А, Б):
        логин = f"trip-{пространство.lower()}"
        create_account(логин, tenant=пространство, password=ПАРОЛЬ, role="admin")
        учётка = authenticate(логин, ПАРОЛЬ)
        assert учётка is not None
        ид[f"user_{пространство}"] = учётка.id
        with acting_space(пространство):
            поездка = tr.create_trip(
                tr.Draft(
                    executor_name=логин,
                    executor_user_id=учётка.id,
                    country=None,
                    date_from=date(2026, 10, 20),
                    date_to=date(2026, 10, 22),
                    status="planned",
                    note=f"секрет {пространство}",
                ),
                tenant=пространство,
                actor_id=учётка.id,
            )
            найдена = tr.get_trip(поездка, tenant=пространство)
            assert найдена is not None
            tr.add_step(
                найдена,
                tr.StepDraft(day=date(2026, 10, 20), at=None, kind="other", unit_id=None, body="x"),
            )
        ид[пространство] = поездка
    return ид


def _ids(conn: Any, sql: str) -> set[str]:
    return {str(r[0]) for r in conn.execute(sql).fetchall()}


@pytest.mark.parametrize("пространство", ["HQ", А, Б])
def test_голый_select_видит_только_свои_поездки_и_планы(
    мир: dict[str, str], db_env: str, пространство: str
) -> None:
    """Без условия в запросе: каждое пространство — только своё, и УК тоже (D505)."""
    with от_имени(db_env, пространство) as conn:
        assert _ids(conn, "select id from trips") == {мир[пространство]}
        assert _ids(conn, "select trip_id from trip_steps") == {мир[пространство]}
        assert _ids(conn, "select tenant_code from trips") == {пространство}


def test_уК_не_видит_поездок_партнёра_даже_по_номеру(мир: dict[str, str], db_env: str) -> None:
    with от_имени(db_env, "HQ") as conn:
        строка = conn.execute("select note from trips where id = %s", (мир[А],)).fetchone()
        assert строка is None


def test_чужое_не_правится_и_не_удаляется(мир: dict[str, str], db_env: str, pg_dsn: str) -> None:
    for кто, чьё in (("HQ", А), (А, "HQ"), (А, Б)):
        with от_имени(db_env, кто) as conn:
            assert (
                conn.execute("update trips set note = 'взлом' where id = %s", (мир[чьё],)).rowcount
                == 0
            )
            assert (
                conn.execute("delete from trip_steps where trip_id = %s", (мир[чьё],)).rowcount == 0
            )
            assert conn.execute("delete from trips where id = %s", (мир[чьё],)).rowcount == 0
            conn.commit()
    with psycopg.connect(pg_dsn) as owner:
        assert owner.execute("select count(*) from trips where note = 'взлом'").fetchone() == (0,)
        assert owner.execute("select count(*) from trips").fetchone() == (3,)
        assert owner.execute("select count(*) from trip_steps").fetchone() == (3,)


def test_нельзя_вписать_строку_в_чужое_пространство(мир: dict[str, str], db_env: str) -> None:
    вставка = (
        "insert into trips (tenant_code, executor_name, date_from, date_to, created_by) "
        "values (%s, 'x', '2026-10-20', '2026-10-21', %s)"
    )
    with от_имени(db_env, А) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute(вставка, ("HQ", мир["user_HQ"]))


def test_шаг_не_привязать_к_чужой_поездке(мир: dict[str, str], db_env: str) -> None:
    """Шаг со своим пространством к поездке УК: ссылка парой не пускает."""
    with от_имени(db_env, А) as conn, pytest.raises(psycopg.errors.ForeignKeyViolation):
        conn.execute(
            "insert into trip_steps (trip_id, tenant_code, day, kind, body) "
            "values (%s, %s, '2026-10-20', 'other', 'x')",
            (мир["HQ"], А),
        )


def test_исполнитель_только_из_своего_пространства(мир: dict[str, str], db_env: str) -> None:
    with от_имени(db_env, А) as conn, pytest.raises(psycopg.errors.ForeignKeyViolation):
        conn.execute(
            "update trips set executor_user_id = %s where id = %s", (мир["user_HQ"], мир[А])
        )


def test_партнёр_не_вписывает_пиццерию_чужой_страны(мир: dict[str, str], db_env: str) -> None:
    шаг = (
        "insert into trip_steps (trip_id, tenant_code, day, kind, unit_id) "
        "values (%s, %s, '2026-10-20', 'inspection', %s)"
    )
    with от_имени(db_env, А) as conn:
        conn.execute(шаг, (мир[А], А, мир["unit_ge"]))
        conn.commit()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(шаг, (мир[А], А, мир["unit_am"]))


def test_без_пространства_база_отказывает(мир: dict[str, str], db_env: str) -> None:
    with от_имени(db_env, None) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("select id from trips").fetchall()


def test_двери_модуля_не_отдают_чужого(мир: dict[str, str]) -> None:
    """Дверь сказала одно пространство, запрос назвал другое — пусто, а не чужое."""
    with acting_space(А):
        assert tr.get_trip(мир["HQ"], tenant=А) is None
        assert tr.get_trip(мир["HQ"], tenant="HQ") is None
        assert [
            п.id
            for п in tr.list_trips(
                tenant="HQ", date_from=date(2026, 10, 1), date_to=date(2026, 10, 31)
            )
        ] == []
        assert (
            tr.update_trip(
                мир["HQ"],
                tr.Draft("x", None, None, date(2026, 10, 20), date(2026, 10, 21), "planned", ""),
                tenant="HQ",
            )
            is False
        )
        assert tr.delete_trip(мир["HQ"], tenant="HQ") is False


def test_без_политики_чужая_поездка_видна(мир: dict[str, str], db_env: str, pg_dsn: str) -> None:
    """Контроль набора: сняли политику, открыли всем — чужое видно, значит набор ловит."""
    with psycopg.connect(pg_dsn, autocommit=True) as owner:
        owner.execute("drop policy trips_own_space on trips")
        owner.execute("create policy trips_open on trips for all using (true) with check (true)")
    with от_имени(db_env, А) as conn:
        assert мир["HQ"] in _ids(conn, "select id from trips"), (
            "без политики чужое не видно — набор ничего не ловит"
        )
