"""T325: правило ограничителя перебора — арифметика, без базы и без экрана.

Здесь проверяется то, чья ошибка молчит. Ограничитель не падает и не кричит:
ошибка в шаге или в сроке забвения оставляет форму входа открытой для перебора,
а выглядит она при этом ровно так же, как рабочая. Поэтому правило вынесено в
чистые функции (`src/db/web_throttle.py`) и проверяется свойствами, а не
пересказом констант: пересказ покраснел бы при любой настройке порога, ничего
при этом не поймав.

Живой путь до Postgres проверяет `tests/test_db_web_throttle.py`, а путь через
форму входа — `tests/test_web_login_limit.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.db.web_throttle import (
    FAILURES_BEFORE_LOCK,
    FORGET_AFTER,
    LOCK_STEPS,
    SCOPES,
    Counter,
    key_fingerprint,
    lock_for,
    verdict_of,
)

СЕЙЧАС = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)


def строка(failures: int, *, назад: timedelta = timedelta(0)) -> Counter:
    return Counter(failures=failures, updated_at=СЕЙЧАС - назад)


# --- сколько неудач терпится ------------------------------------------------


@pytest.mark.parametrize("scope", SCOPES)
def test_ниже_порога_ключ_не_заперт(scope: str) -> None:
    """Последняя попытка перед порогом обязана проходить: человек ошибается."""
    порог = FAILURES_BEFORE_LOCK[scope]
    assert lock_for(порог - 1, scope=scope) == timedelta(0)


@pytest.mark.parametrize("scope", SCOPES)
def test_на_пороге_запрет_наступает(scope: str) -> None:
    assert lock_for(FAILURES_BEFORE_LOCK[scope], scope=scope) > timedelta(0)


@pytest.mark.parametrize("scope", SCOPES)
def test_каждая_следующая_неудача_не_укорачивает_запрет(scope: str) -> None:
    """Срок растёт или стоит, но не убывает.

    Убывающий шаг — это дыра, которую видно только арифметикой: перебор
    дождался бы длинного запрета, а дальше шёл бы по коротким.
    """
    порог = FAILURES_BEFORE_LOCK[scope]
    сроки = [lock_for(n, scope=scope) for n in range(порог, порог + len(LOCK_STEPS) + 5)]
    assert сроки == sorted(сроки)


@pytest.mark.parametrize("scope", SCOPES)
def test_запрет_не_растёт_бесконечно(scope: str) -> None:
    """Потолок есть, и он не запирает человека на сутки за чужой перебор."""
    порог = FAILURES_BEFORE_LOCK[scope]
    assert lock_for(порог + 10_000, scope=scope) == max(LOCK_STEPS)
    assert max(LOCK_STEPS) <= timedelta(hours=1)


@pytest.mark.parametrize("scope", SCOPES)
def test_счётчик_не_забывается_раньше_чем_кончится_запрет(scope: str) -> None:
    """Главный инвариант двух констант, которые правятся рядом.

    Забвение раньше запрета означало бы, что ключ открывается ДОСРОЧНО и сам,
    причём тем раньше, чем злее был перебор: строка исчезает, счётчик обнуляется,
    посчитанный по нему запрет исчезает вместе с ним.
    """
    assert FORGET_AFTER > lock_for(FAILURES_BEFORE_LOCK[scope] + 10_000, scope=scope)


# --- приговор по строке счётчика --------------------------------------------


def test_пустой_счётчик_никого_не_запирает() -> None:
    assert not verdict_of(None, scope="login", now=СЕЙЧАС).locked


def test_свежая_строка_за_порогом_запирает() -> None:
    приговор = verdict_of(строка(FAILURES_BEFORE_LOCK["login"]), scope="login", now=СЕЙЧАС)
    assert приговор.locked
    assert приговор.retry_after > timedelta(0)


def test_запрет_кончается_временем_а_не_попытками() -> None:
    """Прошёл срок — дверь открыта снова, хотя счётчик не тронут."""
    давняя = строка(FAILURES_BEFORE_LOCK["login"], назад=max(LOCK_STEPS) + timedelta(seconds=1))
    assert not verdict_of(давняя, scope="login", now=СЕЙЧАС).locked


def test_оставшийся_срок_уменьшается_со_временем() -> None:
    свежая = verdict_of(строка(FAILURES_BEFORE_LOCK["login"]), scope="login", now=СЕЙЧАС)
    полежавшая = verdict_of(
        строка(FAILURES_BEFORE_LOCK["login"], назад=timedelta(seconds=30)),
        scope="login",
        now=СЕЙЧАС,
    )
    assert полежавшая.retry_after < свежая.retry_after


def test_срок_человеку_округляется_вверх() -> None:
    """«Приходите через 0 минут» — это приглашение долбиться в закрытую дверь."""
    почти = строка(FAILURES_BEFORE_LOCK["login"], назад=min(LOCK_STEPS) - timedelta(seconds=1))
    приговор = verdict_of(почти, scope="login", now=СЕЙЧАС)
    assert приговор.locked
    assert приговор.retry_after_minutes >= 1
    assert приговор.retry_after_seconds >= 1


# --- ключ счётчика ----------------------------------------------------------


def test_введённое_человеком_в_ключ_не_попадает() -> None:
    """В базу уезжает отпечаток, а не то, что напечатали в поле «логин».

    Туда печатают, среди прочего, пароль от соседней системы — и он оставался
    бы в базе дословно.
    """
    отпечаток = key_fingerprint("director")
    assert "director" not in отпечаток
    assert len(отпечаток) == 64
    assert set(отпечаток) <= set("0123456789abcdef")


def test_один_и_тот_же_логин_считается_одним_ключом() -> None:
    """Иначе счётчик обходится сменой регистра и пробелом."""
    assert key_fingerprint(" Director ") == key_fingerprint("director")


def test_разные_ключи_не_складываются_в_один() -> None:
    assert key_fingerprint("director") != key_fingerprint("manager")
