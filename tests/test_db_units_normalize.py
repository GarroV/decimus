"""Запись `make units-normalize` в живой базе (#316, #909): одна транзакция, снимок, повтор пуст.

Выбор точек — в `test_domain_unit_match.py`; здесь только то, что делает с базой запись:
переименование оставляет старое имя синонимом, пустой дубль уходит вместе со своей строкой,
снимок ложится ДО правок, а второй прогон ничего не пишет.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import requires_db
from db_harness import завести_пространства

psycopg = pytest.importorskip("psycopg")

from src.db.directory import upsert_unit  # noqa: E402
from src.db.space import SYSTEM_SPACE, acting_space  # noqa: E402
from src.domain.unit_match import plan  # noqa: E402
from tools.units_normalize import apply  # noqa: E402

pytestmark = requires_db

CODE = "ab" * 16


@pytest.fixture(autouse=True)
def _пространства(request: pytest.FixtureRequest) -> None:
    if "db_env" in request.fixturenames:
        завести_пространства(request.getfixturevalue("pg_dsn"), "HQ")


def _seed(dsn: str) -> tuple[str, str]:
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "insert into unit_profiles (country_code, name_normalized, name, dodo_id, stage, "
            "status, city, address) values ('KG', 'bishkek-8', 'Bishkek-8', %s, 'open', 'x', "
            "'Bishkek', 'Бишкек, проспект Манаса, 7')",
            (CODE,),
        )
        conn.commit()
    web = upsert_unit("Bishkek — 7 Manas Ave", country="KG", city="bishkek")
    other = upsert_unit("Bishkek — Manas", country="KG", city="bishkek", aliases=("Манас",))
    return web, other


def _run(dsn: str, backup: Path) -> list[str]:
    """Запись идёт под служебной ролью, как на площадке: роли приложения delete не выдан."""
    with acting_space(SYSTEM_SPACE):
        actions, _index, _log = apply(dsn, plan, backup)
    return [f"{a.kind}:{a.unit.name}" for a in actions if a.writes]


def test_переименование_оставляет_синоним_и_код_а_повтор_ничего_не_пишет(
    db_env: str, pg_dsn: str, tmp_path: Path
) -> None:
    web, _ = _seed(db_env)
    backup = tmp_path / "снимок.json"

    сделано = _run(pg_dsn, backup)

    assert any(s.startswith("rename:Bishkek — 7 Manas Ave") for s in сделано)
    with psycopg.connect(db_env) as conn:
        строка = conn.execute("select name, code from units where id = %s", (web,)).fetchone()
        синоним = conn.execute(
            "select unit_id::text from unit_aliases where alias = 'Bishkek — 7 Manas Ave'"
        ).fetchone()
    assert строка == ("Bishkek-8", CODE)
    assert синоним == (web,)
    снимок = json.loads(backup.read_text(encoding="utf-8"))
    assert {u["name"] for u in снимок["units"]} >= {"Bishkek — 7 Manas Ave"}

    backup.unlink()
    assert [s for s in _run(pg_dsn, backup) if s.startswith(("rename", "fill"))] == []
    assert not backup.exists()


def test_пустой_дубль_сливается_и_его_синоним_переходит_оставшейся(
    db_env: str, pg_dsn: str, tmp_path: Path
) -> None:
    web, other = _seed(db_env)

    _run(pg_dsn, tmp_path / "снимок.json")

    with psycopg.connect(db_env) as conn:
        остались = {r[0] for r in conn.execute("select id::text from units").fetchall()}
        синоним = conn.execute("select unit_id::text from unit_aliases where alias = 'Манас'")
        ушёл = синоним.fetchone()
    assert (web in остались) != (other in остались)  # одна из двух
    оставшаяся = web if web in остались else other
    assert ушёл == (оставшаяся,)
