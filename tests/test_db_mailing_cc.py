"""Списки копий писем УК в базе (0103, D608): почты и права держит БАЗА, а не экран.

Адрес уходит в заголовок `Cc:`: неверный адрес и CR/LF в нём база отказывает сама, даже
если веб пропустил. Пишет только администратор истории; роль приложения читает, но не из
пространства партнёра — почты персональные.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from conftest import requires_db
from db_harness import set_retraction_env

psycopg = pytest.importorskip("psycopg")

from src.db import mailing_cc  # noqa: E402
from src.db.errors import MailingCcError, MailingCcInputError  # noqa: E402

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


_ВСТАВКА = "insert into mailing_cc (kind, email, added_by) values ('inspection', %s, 'hq')"


def test_список_читается_в_порядке_заведения_и_по_видам(база: str) -> None:
    mailing_cc.add("inspection", "A@Dodobrands.io", actor="boss")
    mailing_cc.add("inspection", "b@dodobrands.io", actor="boss")
    mailing_cc.add("plan", "c@dodobrands.io", actor="boss")
    assert mailing_cc.read("inspection") == ("a@dodobrands.io", "b@dodobrands.io")
    assert mailing_cc.read("prescription") == ()
    assert mailing_cc.counts() == {"inspection": 2, "prescription": 0, "plan": 1}


def test_повтор_адреса_не_дублирует_и_говорит_об_этом(база: str) -> None:
    assert mailing_cc.add("inspection", "a@dodobrands.io", actor="boss") is True
    assert mailing_cc.add("inspection", "A@DODOBRANDS.IO", actor="boss") is False
    assert mailing_cc.read("inspection") == ("a@dodobrands.io",)


def test_убрать_адрес_и_отказ_если_его_нет(база: str) -> None:
    mailing_cc.add("inspection", "a@dodobrands.io", actor="boss")
    mailing_cc.remove("inspection", "A@dodobrands.io")
    assert mailing_cc.read("inspection") == ()
    with pytest.raises(MailingCcError, match="нет"):
        mailing_cc.remove("inspection", "a@dodobrands.io")


@pytest.mark.parametrize(
    "ввод",
    ["", "не почта", "a@x.io, b@x.io", "a@x.io\r\nBcc: evil@x.io", "a@x.io\x07"],
)
def test_кривой_ввод_отказ_до_базы(база: str, ввод: str) -> None:
    with pytest.raises(MailingCcInputError):
        mailing_cc.add("inspection", ввод, actor="boss")
    assert mailing_cc.read("inspection") == ()


def test_неизвестный_вид_и_запись_без_подписи_отказ(база: str) -> None:
    with pytest.raises(MailingCcInputError):
        mailing_cc.add("nope", "a@x.io", actor="boss")
    with pytest.raises(MailingCcError, match="подписывается"):
        mailing_cc.add("inspection", "a@x.io", actor=" ")


@pytest.mark.parametrize(
    "значение",
    ["A@x.io", "a@x.io\r\nBcc: e@x.io", "a b@x.io", "a@x.io, b@x.io", "a@@x.io", "a@x"],
)
def test_база_сама_отказывает_неверной_почте_мимо_веба(база: str, значение: str) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        _sql(база, _ВСТАВКА, (значение,))


def test_база_отказывает_чужому_виду(база: str) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        _sql(база, "insert into mailing_cc (kind, email, added_by) values ('x', 'a@x.io', 'hq')")


def test_роль_приложения_список_не_пишет(база: str, db_env: str) -> None:
    for текст in (
        "insert into mailing_cc (kind, email, added_by) values ('plan', 'a@x.io', 'bot')",
        "delete from mailing_cc",
    ):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            _sql(db_env, текст)


def _читает(db_env: str, space: str) -> int:
    with psycopg.connect(db_env) as conn:
        conn.execute("select set_config('decimus.space', %s, false)", (space,))
        return int(conn.execute("select count(*) from mailing_cc").fetchone()[0])  # type: ignore[index]


def test_почты_видны_пространству_ук_и_не_видны_партнёру(база: str, db_env: str) -> None:
    mailing_cc.add("inspection", "a@dodobrands.io", actor="boss")
    # Числа в переменных: сообщение об ошибке не должно печатать строку подключения.
    ук, служебное, партнёр = (_читает(db_env, space) for space in ("HQ", "*", "GE"))
    assert (ук, служебное, партнёр) == (1, 1, 0)
