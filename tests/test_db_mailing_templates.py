"""Шаблоны писем УК с версиями в базе (0104, #977, #1130): версии и права держит БАЗА.

Строка не правится: каждое сохранение — новая версия, «вернуть встроенный» — тоже. Пишет
только администратор истории; роль приложения читает, но не из пространства партнёра.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from conftest import requires_db
from db_harness import set_retraction_env

psycopg = pytest.importorskip("psycopg")

from src.db import mailing_templates as store  # noqa: E402
from src.db.errors import MailingTemplateInputError  # noqa: E402

pytestmark = requires_db


@pytest.fixture
def admin_env(db_env: str, monkeypatch: pytest.MonkeyPatch) -> str:
    return set_retraction_env(db_env, monkeypatch)


@pytest.fixture
def база(pg_dsn: str, db_env: str, domain_env: Path, admin_env: str) -> str:
    return admin_env


def _sql(dsn: str, текст: str, параметры: tuple[Any, ...] = ()) -> None:
    with psycopg.connect(dsn) as conn:
        conn.execute(текст, параметры)
        conn.commit()


_ВСТАВКА = (
    "insert into mailing_templates (kind, slot, lang, version, body, saved_by) "
    "values ('inspection', 'plan', 'ru', 1, %s, 'hq')"
)


def test_версии_растут_и_текущая_последняя(база: str) -> None:
    assert store.save("plan", "ru", "Первый {unit}", actor="boss") == 1
    assert store.save("plan", "ru", "Второй {unit}", actor="boss") == 2
    assert store.save("plan", "en", "English {unit}", actor="boss") == 1
    сейчас = store.current()
    assert сейчас[("plan", "ru")].body == "Второй {unit}"
    assert сейчас[("plan", "en")].version == 1
    assert store.bodies() == {"ru": {"plan": "Второй {unit}"}, "en": {"plan": "English {unit}"}}


def test_история_новые_первыми_и_с_автором(база: str) -> None:
    store.save("plan", "ru", "Первый {unit}", actor="ann")
    store.save("plan", "ru", "Второй {unit}", actor="boss")
    история = store.history("plan", "ru")
    assert [(v.version, v.saved_by) for v in история] == [(2, "boss"), (1, "ann")]


def test_вернуть_встроенный_это_версия_и_слот_выпадает_из_хранимых(база: str) -> None:
    store.save("clean", "ru", "Свой {unit}", actor="boss")
    assert store.save("clean", "ru", None, actor="boss") == 2
    assert store.current()[("clean", "ru")].body is None
    assert store.bodies() == {}, "для движка слот снова встроенный"
    assert [v.body for v in store.history("clean", "ru")] == [None, "Свой {unit}"]


@pytest.mark.parametrize(
    "текст",
    [
        "",
        "   ",
        "Привет {bogus}",
        "Оценка {grade:>5}",
        "Скобка { одна",
        "x" * 6001,
        "a\x07b {unit}",
    ],
)
def test_кривой_текст_отказ_до_базы(база: str, текст: str) -> None:
    with pytest.raises(MailingTemplateInputError):
        store.save("plan", "ru", текст, actor="boss")
    assert store.current() == {}


def test_неизвестный_слот_язык_вид_и_запись_без_подписи_отказ(база: str) -> None:
    with pytest.raises(MailingTemplateInputError):
        store.save("nope", "ru", "x {unit}", actor="boss")
    with pytest.raises(MailingTemplateInputError):
        store.save("plan", "de", "x {unit}", actor="boss")
    with pytest.raises(MailingTemplateInputError):
        store.save("plan", "ru", "x {unit}", actor="boss", kind="plan")
    with pytest.raises(MailingTemplateInputError, match="подписывается"):
        store.save("plan", "ru", "x {unit}", actor=" ")


@pytest.mark.parametrize("значение", ["", "   ", "a\x07b", "x" * 6001])
def test_база_сама_отказывает_кривому_тексту_мимо_кода(база: str, значение: str) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        _sql(база, _ВСТАВКА, (значение,))


def test_версия_не_дублируется(база: str) -> None:
    _sql(база, _ВСТАВКА, ("Один {unit}",))
    with pytest.raises(psycopg.errors.UniqueViolation):
        _sql(база, _ВСТАВКА, ("Два {unit}",))


def test_роль_приложения_шаблоны_не_пишет(база: str, db_env: str) -> None:
    for текст in (
        _ВСТАВКА % "'x'",
        "delete from mailing_templates",
        "update mailing_templates set body = 'y'",
    ):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            _sql(db_env, текст)


def _читает(db_env: str, space: str) -> int:
    with psycopg.connect(db_env) as conn:
        conn.execute("select set_config('decimus.space', %s, false)", (space,))
        return int(conn.execute("select count(*) from mailing_templates").fetchone()[0])  # type: ignore[index]


def test_шаблоны_видны_пространству_ук_и_не_видны_партнёру(база: str, db_env: str) -> None:
    store.save("plan", "ru", "Свой {unit}", actor="boss")
    ук, служебное, партнёр = (_читает(db_env, space) for space in ("HQ", "*", "GE"))
    assert (ук, служебное, партнёр) == (1, 1, 0)
