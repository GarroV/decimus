"""#481: пространство не заводится неявно — опечатка в его коде это громкий отказ.

До исправления четыре двери базы (`web_access`, `mcp_access`, `synonyms`,
`directory`) перед записью вставляли строку в `tenants` с `on conflict do
nothing`: опечатка в коде пространства тихо заводила новое пустое
пространство, и запись уезжала туда. Пространства заводит команда
(`make space`), строку `HQ` — схема (`0029`). Слив проверки (`push.py`) этого
уже не делает с волны 1.

Каждый случай проверяет обе половины: отказ назван, и в `tenants` ничего не
появилось.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from conftest import requires_db

psycopg = pytest.importorskip("psycopg")

from src.db.directory import upsert_unit  # noqa: E402
from src.db.errors import AccessError, PushError, SynonymError  # noqa: E402
from src.db.mcp_access import add_admin, issue_token  # noqa: E402
from src.db.synonyms import remember_phrase  # noqa: E402
from src.db.web_access import create_account  # noqa: E402

pytestmark = requires_db

ОПЕЧАТКА = "HQQ"
ОСНОВАТЕЛЬ = 100500


def _пространства(dsn: str) -> set[str]:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("select code from tenants")
        return {str(r[0]) for r in cur.fetchall()}


def _учётка(_: str) -> Any:
    return create_account("director", tenant=ОПЕЧАТКА, password="верный-пароль-учётки")


def _токен(_: str) -> Any:
    add_admin(ОСНОВАТЕЛЬ, by=None)
    return issue_token(ОСНОВАТЕЛЬ, tenant=ОПЕЧАТКА)


def _синоним(_: str) -> Any:
    return remember_phrase("жёлтый зонт", item_code="CLN05", lang="ru", tenant=ОПЕЧАТКА)


def _точка(_: str) -> Any:
    return upsert_unit("Белград 2", tenant=ОПЕЧАТКА)


@pytest.mark.parametrize(
    ("дверь", "отказ"),
    [
        (_учётка, AccessError),
        (_токен, AccessError),
        (_синоним, SynonymError),
        (_точка, PushError),
    ],
    ids=["web_access", "mcp_access", "synonyms", "directory"],
)
def test_опечатка_в_пространстве_это_отказ_а_не_новое_пространство(
    pg_dsn: str,
    db_env: str,
    monkeypatch: pytest.MonkeyPatch,
    дверь: Callable[[str], Any],
    отказ: type[Exception],
) -> None:
    monkeypatch.setenv("DATABASE_ADMIN_URL", pg_dsn)
    было = _пространства(pg_dsn)

    with pytest.raises(отказ) as пойман:
        дверь(ОПЕЧАТКА)

    assert ОПЕЧАТКА in str(пойман.value)
    assert "make space" in str(пойман.value)
    assert _пространства(pg_dsn) == было


def test_заведённое_пространство_работает_как_раньше(
    pg_dsn: str, db_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Отказ — только на незаведённое: `HQ` заводит схема, и запись в него идёт."""
    monkeypatch.setenv("DATABASE_ADMIN_URL", pg_dsn)

    assert create_account("director", tenant="HQ", password="верный-пароль-учётки").tenant == "HQ"
    assert upsert_unit("Белград 2", tenant="HQ")
