"""Выбор языка бота хранится за человеком (D303, миграция `0035`).

Под ролью приложения — так, как ходит бот: заодно это проверка, что выданных
ей прав хватает на запись и перезапись выбора.
"""

from __future__ import annotations

import pytest
from conftest import requires_db

psycopg = pytest.importorskip("psycopg")

from src.db.bot_langs import choose_lang, chosen_lang  # noqa: E402
from src.db.errors import AccessError  # noqa: E402

pytestmark = requires_db


def test_выбора_нет_пока_человек_не_выбирал(db_env: str) -> None:
    assert chosen_lang(501) is None


def test_выбор_сохраняется_и_перезаписывается(db_env: str) -> None:
    choose_lang(501, "en")
    assert chosen_lang(501) == "en"

    choose_lang(501, "ru")
    assert chosen_lang(501) == "ru"
    assert chosen_lang(502) is None, "выбор одного достался другому"


def test_строка_одна_на_человека(db_env: str, pg_dsn: str) -> None:
    choose_lang(501, "en")
    choose_lang(501, "ru")
    with psycopg.connect(pg_dsn) as conn:
        строк = conn.execute("select count(*) from bot_ui_langs").fetchone()
    assert строк == (1,)


def test_база_не_принимает_не_код_языка(db_env: str) -> None:
    """Форму кода держит база: в строку не уедет ни надпись кнопки, ни мусор."""
    with pytest.raises(AccessError, match="CheckViolation"):
        choose_lang(501, "Русский")


def test_удалить_выбор_роль_приложения_не_может(db_env: str) -> None:
    choose_lang(501, "en")
    with psycopg.connect(db_env) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("delete from bot_ui_langs where telegram_id = 501")


@pytest.mark.parametrize("код", ["pt-BR", "zh-Hans"])
def test_база_принимает_код_с_регионом_и_письмом(db_env: str, код: str) -> None:
    """Третий язык добавляется словарём — миграция под него не нужна (ревью #492, п.3)."""
    choose_lang(501, код)
    assert chosen_lang(501) == код
