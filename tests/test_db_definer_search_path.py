"""Функции владельца держат `pg_temp` последним в пути поиска (`0033`).

У функции `security definer` временная схема сеанса ищется ПЕРВОЙ, если её не
назвать в пути явно. Тогда вызвавший заводит временную `web_users` или
`web_sessions`, и функция с правами владельца работает с ней вместо
настоящей. Проверка идёт по каталогу, а не по списку имён. Новая функция
владельца без `pg_temp` в конце пути покраснит здесь, даже если о ней никто не
вспомнил.
"""

from __future__ import annotations

import pytest
from conftest import requires_db

psycopg = pytest.importorskip("psycopg")

pytestmark = requires_db

#: Путь поиска функции владельца — ровно такой, `pg_temp` в конце.
ПУТЬ = "search_path=pg_catalog, public, pg_temp"

#: Функции владельца, известные на сегодня. Проверка не ограничивается ими,
#: список нужен, чтобы пустой каталог не прошёл молча.
ИЗВЕСТНЫЕ = {
    "change_own_password",
    "inspection_unit_of_space",
    "log_inspection_move",
    "unit_space_frozen",
}


def test_у_каждой_функции_владельца_pg_temp_последним(pg_dsn: str) -> None:
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            """
            select p.proname, coalesce(p.proconfig, '{}')
              from pg_proc p
              join pg_namespace n on n.oid = p.pronamespace
             where p.prosecdef and n.nspname = 'public'
            """
        )
        функции = {str(имя): list(настройки) for имя, настройки in cur.fetchall()}

    assert ИЗВЕСТНЫЕ <= функции.keys(), f"функции владельца пропали: {ИЗВЕСТНЫЕ - функции.keys()}"
    без_пути = {имя: н for имя, н in функции.items() if ПУТЬ not in н}
    assert not без_пути, (
        f"функции владельца без `{ПУТЬ}`: {без_пути}. Без `pg_temp` в конце пути "
        f"временная таблица вызвавшего подменяет настоящую (0033)"
    )
