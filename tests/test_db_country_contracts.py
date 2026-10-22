"""Договор страны в базе (0088, D603): заслон почт и прав — держит БАЗА, а не экран.

Почты контактов по ДКК уходят в заголовок письма: неверный адрес и CR/LF в нём база
отказывает сама, даже если веб пропустил. Пишет только администратор истории;
роль приложения читает, но не из пространства партнёра — почты персональные.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from conftest import requires_db
from db_harness import set_retraction_env

psycopg = pytest.importorskip("psycopg")

from src.db import country_contracts as cc  # noqa: E402
from src.db.errors import CountryContractError  # noqa: E402

pytestmark = requires_db


@pytest.fixture
def admin_env(db_env: str, monkeypatch: pytest.MonkeyPatch) -> str:
    return set_retraction_env(db_env, monkeypatch)


@pytest.fixture
def база(pg_dsn: str, db_env: str, domain_env: Path, admin_env: str) -> str:
    return admin_env


def _sql(dsn: str, текст: str, параметры: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    with psycopg.connect(dsn) as conn:
        cur = conn.execute(текст, параметры)
        rows = cur.fetchall() if cur.description else []
        conn.commit()
    return rows


_ВСТАВКА = (
    "insert into country_contracts (country, legal_name, dkk_emails, updated_by)"
    " values ('GE', 'ООО Лотос', %s, 'hq')"
)


def test_строки_договора_читаются_и_контакты_сливаются_без_повторов(база: str) -> None:
    cc.save(
        "GE", cc.ContractFields(legal_name="Lotos LLC", dkk_emails="a@ge.example.com"), actor="osb"
    )
    cc.save(
        "GE",
        cc.ContractFields(legal_name="Rose LLC", dkk_emails="A@ge.example.com; b@ge.example.com"),
        actor="osb",
    )
    cc.save("AM", cc.ContractFields(dkk_emails="x@am.example.com"), actor="osb")
    assert [c.legal_name for c in cc.read("GE")] == ["Lotos LLC", "Rose LLC"]
    assert cc.dkk_recipients("GE") == "a@ge.example.com, b@ge.example.com"
    assert cc.dkk_recipients("TR") == ""


def test_правка_строки_подписывается_и_не_уводит_её_в_другую_страну(база: str) -> None:
    cc.save("GE", cc.ContractFields(legal_name="Lotos LLC"), actor="osb")
    ident = cc.read("GE")[0].id
    cc.save("GE", cc.ContractFields(legal_name="Lotos 2"), actor="admin", contract_id=ident)
    строка = cc.read("GE")[0]
    assert (строка.legal_name, строка.updated_by) == ("Lotos 2", "admin")
    with pytest.raises(CountryContractError, match="нет"):
        cc.save("AM", cc.ContractFields(legal_name="чужая"), actor="x", contract_id=ident)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        _sql(база, "update country_contracts set country = 'AM' where id = %s", (ident,))


def test_снятие_строки_только_в_своей_стране(база: str) -> None:
    cc.save("GE", cc.ContractFields(legal_name="Lotos LLC"), actor="osb")
    ident = cc.read("GE")[0].id
    with pytest.raises(CountryContractError):
        cc.remove("AM", ident)
    cc.remove("GE", ident)
    assert cc.read("GE") == ()


@pytest.mark.parametrize(
    "ввод",
    ["не-почта", "a@b", "a@ge.example.com\r\nBcc: evil@x.example.com", "a@ge.example.com\x00"],
)
def test_кривая_почта_и_подмена_заголовка_отказ_до_базы(база: str, ввод: str) -> None:
    with pytest.raises(CountryContractError):
        cc.save("GE", cc.ContractFields(dkk_emails=ввод), actor="osb")
    assert cc.read("GE") == ()


@pytest.mark.parametrize(
    "значение",
    [
        "не-почта",
        "a@ge.example.com,b@ge.example.com",
        "a@ge.example.com\r\nBcc: evil@x.example.com",
        "a@ge.example.com\nb@ge.example.com",
        "a@ge.example.com, ",
        "a@ge.example.com\x07",
        "a b@ge.example.com",
    ],
)
def test_база_сама_отказывает_неверной_почте_мимо_веба(база: str, значение: str) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        _sql(база, _ВСТАВКА, (значение,))


def test_база_принимает_несколько_адресов_через_запятую_с_пробелом(база: str) -> None:
    _sql(база, _ВСТАВКА, ("a@ge.example.com, b.c@ge.example.com",))


def test_управляющие_знаки_в_однострочных_полях_отказ_базы(база: str) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        _sql(
            база,
            "insert into country_contracts (country, address, updated_by)"
            " values ('GE', E'улица\\nвторая строка', 'hq')",
        )


def test_пустая_строка_договора_отказ(база: str) -> None:
    with pytest.raises(CountryContractError, match="хотя бы одно"):
        cc.save("GE", cc.ContractFields(legal_name="  "), actor="osb")
    with pytest.raises(psycopg.errors.CheckViolation):
        _sql(база, "insert into country_contracts (country, updated_by) values ('GE', 'hq')")


def test_без_подписи_запись_отказ(база: str) -> None:
    with pytest.raises(CountryContractError, match="подписывается"):
        cc.save("GE", cc.ContractFields(legal_name="X"), actor=" ")


def test_роль_приложения_договор_не_пишет(база: str, db_env: str) -> None:
    for текст in (
        "insert into country_contracts (country, legal_name, updated_by) values ('GE', 'x', 'bot')",
        "update country_contracts set legal_name = 'x'",
        "delete from country_contracts",
    ):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            _sql(db_env, текст)


def _читает(db_env: str, space: str) -> int:
    with psycopg.connect(db_env) as conn:
        conn.execute("select set_config('decimus.space', %s, false)", (space,))
        return int(conn.execute("select count(*) from country_contracts").fetchone()[0])  # type: ignore[index]


def test_почты_видны_пространству_ук_и_не_видны_партнёру(база: str, db_env: str) -> None:
    cc.save("GE", cc.ContractFields(dkk_emails="a@ge.example.com"), actor="osb")
    # Числа в переменных: сообщение об ошибке не должно печатать строку подключения.
    ук, служебное, партнёр = (_читает(db_env, space) for space in ("HQ", "*", "GE"))
    assert (ук, служебное, партнёр) == (1, 1, 0)
