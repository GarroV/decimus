"""Режим «Завершить» хранится за человеком (D449, миграция `0056`).

Под ролью приложения — так, как ходит мини-апп: заодно это проверка, что
выданных ей прав хватает на запись и перезапись выбора.
"""

from __future__ import annotations

import pytest
from conftest import requires_db

psycopg = pytest.importorskip("psycopg")

from src.db.errors import AccessError  # noqa: E402
from src.db.finish_modes import choose_finish_mode, chosen_finish_mode  # noqa: E402

pytestmark = requires_db


def test_выбора_нет_пока_человек_не_выбирал(db_env: str) -> None:
    assert chosen_finish_mode(501) is None


def test_выбор_сохраняется_перезаписывается_и_не_достаётся_другому(db_env: str) -> None:
    choose_finish_mode(501, "report")
    assert chosen_finish_mode(501) == "report"

    choose_finish_mode(501, "summary")
    assert chosen_finish_mode(501) == "summary"
    assert chosen_finish_mode(502) is None


def test_режим_вне_списка_не_доходит_до_базы() -> None:
    with pytest.raises(ValueError, match="не заведён"):
        choose_finish_mode(501, "both")


def test_база_не_принимает_чужой_режим(db_env: str) -> None:
    with psycopg.connect(db_env) as conn, pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("insert into finish_modes (telegram_id, mode) values (501, 'both')")


def test_удалить_выбор_роль_приложения_не_может(db_env: str) -> None:
    choose_finish_mode(501, "report")
    with psycopg.connect(db_env) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("delete from finish_modes where telegram_id = 501")


def test_отказ_базы_это_ошибка_а_не_пустой_выбор(
    db_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://nobody@127.0.0.1:1/none")
    with pytest.raises(AccessError):
        chosen_finish_mode(501)
