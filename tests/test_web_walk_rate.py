"""Предел частоты мини-аппа обхода по чату (#529, #710)."""

from __future__ import annotations

from pathlib import Path

import pytest
from test_web_walk import АУДИТОР, ТОКЕН, _приложение
from test_web_walk_write import Клиент

from src.db.bot_links import NEVER_BOUND
from src.domain import start_inspection
from src.web import walk, walk_access, walk_rate


@pytest.fixture
def клиент(domain_env: Path, monkeypatch: pytest.MonkeyPatch) -> Клиент:
    start_inspection(АУДИТОР, unit="Белград-1", kind="planned", report_lang="ru", ui_lang="ru")
    monkeypatch.setattr(walk.queries, "previous_findings", lambda **_: None)
    monkeypatch.setattr(walk_access.bot_links, "standing", lambda _: NEVER_BOUND)
    приложение = _приложение(
        monkeypatch, TELEGRAM_BOT_TOKEN=ТОКЕН, ALLOWED_TELEGRAM_IDS=str(АУДИТОР)
    )
    return Клиент(приложение.test_client())


class Часы:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def test_окно_пропускает_предел_и_отпускает_через_минуту() -> None:
    часы = Часы()
    счёт = walk_rate.ChatRate(clock=часы)

    пропущено = [счёт.allow(1, walk_rate.PHOTO) for _ in range(walk_rate.PHOTO_PER_MINUTE)]
    сверх = счёт.allow(1, walk_rate.PHOTO)
    другой_чат = счёт.allow(2, walk_rate.PHOTO)
    другой_вид = счёт.allow(1, walk_rate.OTHER)
    часы.t += walk_rate.WINDOW_SEC
    после = счёт.allow(1, walk_rate.PHOTO)

    assert all(пропущено) and not сверх
    assert другой_чат and другой_вид and после


def test_молчащие_чаты_забываются() -> None:
    часы = Часы()
    счёт = walk_rate.ChatRate(clock=часы)
    for chat in range(walk_rate.SWEEP_AFTER + 1):
        счёт.allow(chat)
    часы.t += walk_rate.WINDOW_SEC
    счёт.allow(10_000)

    assert len(счёт._seen) == 1


def test_кадры_сверх_предела_получают_429_словами(
    клиент: Клиент,
    domain_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(walk_rate, "_LIMITS", {walk_rate.PHOTO: 2, walk_rate.OTHER: 50})
    первые = [клиент.кадр().status_code for _ in range(2)]
    сверх = клиент.кадр()
    показ = клиент.показ("walk:" + "0" * 32)

    assert первые == [201, 201]
    assert сверх.status_code == 429
    assert "Слишком много запросов" in сверх.get_json()["message"]
    assert показ.status_code != 429  # прочие запросы считаются отдельно


def test_прочие_сверх_предела_получают_429(
    клиент: Клиент,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(walk_rate, "_LIMITS", {walk_rate.PHOTO: 50, walk_rate.OTHER: 1})
    первый = клиент.показ("walk:" + "0" * 32)
    второй = клиент.показ("walk:" + "0" * 32)

    assert первый.status_code != 429 and второй.status_code == 429
