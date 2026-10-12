"""Язык чек-листа хранится за человеком (D440, миграция `0057`).

Под ролью приложения — так, как ходит мини-апп: заодно это проверка, что
выданных ей прав хватает на запись и перезапись выбора.
"""

from __future__ import annotations

import pytest
from conftest import requires_db

psycopg = pytest.importorskip("psycopg")

from src.db.checklist_langs import choose_checklist_lang, chosen_checklist_lang  # noqa: E402
from src.db.errors import AccessError  # noqa: E402


def test_код_не_языка_не_доходит_до_базы() -> None:
    with pytest.raises(ValueError, match="не разбирается"):
        choose_checklist_lang(501, "ru; drop table x")


@requires_db
def test_выбора_нет_пока_человек_не_выбирал(db_env: str) -> None:
    assert chosen_checklist_lang(501) is None


@requires_db
def test_выбор_сохраняется_перезаписывается_и_не_достаётся_другому(db_env: str) -> None:
    choose_checklist_lang(501, "en")
    assert chosen_checklist_lang(501) == "en"

    choose_checklist_lang(501, "ru")
    assert chosen_checklist_lang(501) == "ru"
    assert chosen_checklist_lang(502) is None


@requires_db
def test_база_не_принимает_не_код_языка(db_env: str) -> None:
    with psycopg.connect(db_env) as conn, pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("insert into checklist_langs (telegram_id, lang) values (501, 'EN!')")


@requires_db
def test_удалить_выбор_роль_приложения_не_может(db_env: str) -> None:
    choose_checklist_lang(501, "en")
    with psycopg.connect(db_env) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("delete from checklist_langs where telegram_id = 501")


@requires_db
def test_отказ_базы_это_ошибка_а_не_пустой_выбор(
    db_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://nobody@127.0.0.1:1/none")
    with pytest.raises(AccessError):
        chosen_checklist_lang(501)
