"""Языки отчёта страны в настоящей базе (0096, D640).

Строка перекрывает файл методики: читает роль приложения, пишет администратор истории.
База сама не принимает пустой перечень, чужой формат и страну не в ISO; `reset` снимает
переопределение, повторная запись заменяет прежнюю.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import requires_db
from db_harness import set_retraction_env

psycopg = pytest.importorskip("psycopg")

from src.db import country_report_langs as crl  # noqa: E402
from src.db.errors import DbError  # noqa: E402

pytestmark = requires_db


@pytest.fixture
def база(db_env: str, domain_env: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    return set_retraction_env(db_env, monkeypatch)


def test_нет_строки_читается_как_нет_переопределения(база: str) -> None:
    assert crl.read("GE") is None


def test_сохранённый_перечень_читается_в_том_же_порядке(база: str) -> None:
    crl.save("GE", ("en", "ru"), actor="director")
    assert crl.read("GE") == ("en", "ru")


def test_повторная_запись_заменяет_прежнюю_а_сброс_снимает(база: str) -> None:
    crl.save("GE", ("en", "ru"), actor="director")
    crl.save("GE", ("ru",), actor="director")
    assert crl.read("GE") == ("ru",)
    crl.reset("GE")
    assert crl.read("GE") is None
    crl.reset("GE")  # снять нечего — не ошибка


def test_все_переопределения_читаются_одним_запросом(база: str) -> None:
    assert crl.read_all() == {}
    crl.save("GE", ("en", "ru"), actor="director")
    crl.save("AM", ("ru",), actor="director")
    assert crl.read_all() == {"GE": ("en", "ru"), "AM": ("ru",)}


def test_эффективный_перечень_берёт_базу_и_отмечает_это(база: str) -> None:
    langs, custom = crl.resolve("GE")
    assert custom is False and langs
    crl.save("GE", ("en",), actor="director")
    assert crl.resolve("GE") == (["en"], True)


@pytest.mark.parametrize(
    ("country", "langs"),
    [("GE", ()), ("GE", ("RU",)), ("GE", ("russian",)), ("geo", ("ru",)), ("G", ("ru",))],
)
def test_база_не_принимает_пустое_и_чужой_формат(
    база: str, country: str, langs: tuple[str, ...]
) -> None:
    with pytest.raises(DbError):
        crl.save(country, langs, actor="director")
    assert crl.read("GE") is None


def test_без_подписи_запись_отказана(база: str) -> None:
    with pytest.raises(DbError):
        crl.save("GE", ("ru",), actor="  ")
    assert crl.read("GE") is None
