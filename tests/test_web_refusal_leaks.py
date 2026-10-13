# ruff: noqa: F811 — фикстура стенда приходит импортом из test_web_acceptance
"""GHSA-9rhx-cqgm-wvvp, F-012: текст ошибки не доходит до человека.

`RetractionError` и ошибки драйвера и хранилища несли в тексте хост, роль и
ответ корзины, а карточка проверки подставляла `str(exc)` в сообщение отказа.
Теперь экран берёт причину по коду из белого списка (`texts_refusals.py`), а
текст исключения остаётся оператору — в журнале.

Базы набор не требует: двери подменены, исключения бросаются с ВЫДУМАННЫМИ
хостом и ролью. Набор ПАДАЕТ, если текст исключения снова дойдёт до страницы.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest
from flask.testing import FlaskClient
from test_web_acceptance import ORIGIN, _приёмка, админ, стенд  # noqa: F401

from src.db import retract as retract_module
from src.db.errors import AcceptError, MoveError, RetractionError, ReviseError, StorageError
from src.web import inspections as data
from src.web.db_refusal import domain_reason

FAKE_HOST = "db-host.example.invalid"
FAKE_ROLE = "fake_history_role"
ПРОБА = f'connection to "{FAKE_HOST}" failed: password authentication failed for "{FAKE_ROLE}"'


def _не_течёт(текст: str) -> None:
    assert FAKE_HOST not in текст
    assert FAKE_ROLE not in текст


@админ
def test_текст_отказа_снятия_не_доходит_до_страницы(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _приёмка(monkeypatch)

    def отказать(*_a: Any, **_k: Any) -> None:
        raise RetractionError(f"Хранилище не убрало кадр: {ПРОБА}")

    monkeypatch.setattr(data, "retract_card", отказать)

    ответ = стенд.post("/inspections/x/retract", data={"reason": "ошибка"}, headers=ORIGIN)
    страница = ответ.get_data(as_text=True)

    _не_течёт(страница)
    assert "Действие не выполнено" in страница, "вместо причины нет общего текста"


@админ
def test_известный_код_показан_словами_без_текста_исключения(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _приёмка(monkeypatch)

    def отказать(*_a: Any, **_k: Any) -> None:
        raise RetractionError(f"{ПРОБА} служебная подробность", code="retract_storage")

    monkeypatch.setattr(data, "retract_card", отказать)

    страница = стенд.post(
        "/inspections/x/retract", data={"reason": "ошибка"}, headers=ORIGIN
    ).get_data(as_text=True)

    _не_течёт(страница)
    assert "служебная подробность" not in страница
    assert "часть кадров убрать не удалось" in страница


@админ
@pytest.mark.parametrize(
    ("путь", "дверь", "ошибка"),
    [
        ("/inspections/x/accept", "accept_card", AcceptError),
        ("/inspections/x/move", "move_card", MoveError),
    ],
)
def test_отказы_подтверждения_и_переноса_не_текут(
    стенд: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
    путь: str,
    дверь: str,
    ошибка: type[Exception],
) -> None:
    _приёмка(monkeypatch)

    def отказать(*_a: Any, **_k: Any) -> None:
        raise ошибка(ПРОБА)

    monkeypatch.setattr(data, дверь, отказать)

    страница = стенд.post(путь, headers=ORIGIN).get_data(as_text=True)

    _не_течёт(страница)
    assert "Действие не выполнено" in страница


def test_переводчик_берёт_текст_по_коду_на_обоих_языках() -> None:
    отказ = ReviseError(ПРОБА, code="revise_text_long", params={"max": 500})

    ru, en = domain_reason(отказ, "ru"), domain_reason(отказ, "en")

    assert "500" in ru and "500" in en and ru != en
    _не_течёт(ru + en)


def test_переводчик_вложенный_отказ_кадра_переводит_причину() -> None:
    причина = ReviseError(ПРОБА, code="photo_storage")
    внешний = ReviseError(ПРОБА, code="add_photo_failed", params={"reason": причина})

    текст = domain_reason(внешний, "en")

    _не_течёт(текст)
    assert "photo storage" in текст


def test_переводчик_неизвестный_код_и_без_кода_даёт_общий_текст_и_журнал(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.ERROR, logger="src.web.db_refusal"):
        без_кода = domain_reason(ReviseError(ПРОБА), "ru")
        чужой = domain_reason(ReviseError(ПРОБА, code="нет_такого"), "en")

    _не_течёт(без_кода + чужой)
    assert "Действие не выполнено" in без_кода
    assert "was not completed" in чужой
    assert FAKE_HOST in caplog.text, "подробность должна уйти оператору в журнал"


def test_отказ_хранилища_при_снятии_кадров_не_несёт_текст_хранилища() -> None:
    """`_purge_photos`: текст `StorageError` (корзина, адрес) не входит в отказ."""

    class Курсор:
        def __enter__(self) -> "Курсор":
            return self

        def __exit__(self, *_a: object) -> None:
            return None

        def execute(self, *_a: object) -> None:
            return None

        def fetchall(self) -> list[tuple[str, str, str | None]]:
            return [("p1", "s3://корзина/ключ", None)]

    class Соединение:
        def cursor(self) -> Курсор:
            return Курсор()

        def commit(self) -> None:
            return None

    class Склад:
        def delete(self, _key: str) -> None:
            raise StorageError(ПРОБА)

    with pytest.raises(RetractionError) as отказ:
        retract_module._purge_photos(Соединение(), "i1", storage=Склад())  # type: ignore[arg-type]

    _не_течёт(str(отказ.value))
    assert отказ.value.code == "retract_storage"
