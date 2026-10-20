"""F-110 и F-125: замки базы между процессами — «уже выполняется» и плановые загрузчики.

Замок сессионный, поэтому «другой процесс» здесь — другое соединение той же базы:
этого достаточно, чтобы база, а не память теста, решала, кто первый.
"""

from __future__ import annotations

import pytest
from conftest import requires_db

pytest.importorskip("psycopg")

from src.db import busy_lock, job_lock

pytestmark = requires_db


def test_вторая_операция_на_тот_же_ключ_не_занимается(db_env: str) -> None:
    первая = busy_lock.try_hold(busy_lock.WALK_TRANSLATE, "42")
    try:
        вторая = busy_lock.try_hold(busy_lock.WALK_TRANSLATE, "42")
        assert первая.acquired and первая.shared
        assert вторая.acquired is False, "две одинаковые операции идут одновременно"
    finally:
        первая.release()


def test_другой_ключ_и_другая_операция_не_мешают(db_env: str) -> None:
    holds = [
        busy_lock.try_hold(busy_lock.WALK_TRANSLATE, "42"),
        busy_lock.try_hold(busy_lock.WALK_TRANSLATE, "43"),
        busy_lock.try_hold(busy_lock.WALK_SUGGEST, "42"),
    ]
    try:
        assert [h.acquired for h in holds] == [True, True, True]
    finally:
        for h in holds:
            h.release()


def test_замок_отпускается_и_повторный_релиз_безвреден(db_env: str) -> None:
    первая = busy_lock.try_hold(busy_lock.WALK_REPORT, "7")
    первая.release()
    первая.release()

    снова = busy_lock.try_hold(busy_lock.WALK_REPORT, "7")
    try:
        assert снова.acquired and снова.shared, "замок остался висеть после операции"
    finally:
        снова.release()


def test_замок_отпускается_из_другого_потока(db_env: str) -> None:
    """Сборка отчёта берёт замок в запросе, а отпускает в фоновом потоке."""
    import threading

    первая = busy_lock.try_hold(busy_lock.WALK_REPORT, "8")
    поток = threading.Thread(target=первая.release)
    поток.start()
    поток.join()

    снова = busy_lock.try_hold(busy_lock.WALK_REPORT, "8")
    try:
        assert снова.acquired and снова.shared
    finally:
        снова.release()


def test_без_базы_занятость_держится_в_памяти_процесса(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    hold = busy_lock.try_hold(busy_lock.WALK_SUGGEST, "1")

    assert hold.acquired is True and hold.shared is False
    hold.release()


def test_второй_загрузчик_замок_не_получает(db_env: str) -> None:
    with job_lock.job_lock(job_lock.MAPS_LOADER_LOCK_KEY, what="карты") as первый:
        assert первый is True
        with job_lock.job_lock(job_lock.MAPS_LOADER_LOCK_KEY, what="карты") as второй:
            assert второй is False, "два загрузчика карт идут одновременно"


def test_замки_разных_загрузчиков_независимы_и_отпускаются(db_env: str) -> None:
    with job_lock.job_lock(job_lock.MAPS_LOADER_LOCK_KEY, what="карты") as карты:
        with job_lock.job_lock(job_lock.SHEET_LOADER_LOCK_KEY, what="таблица") as таблица:
            assert (карты, таблица) == (True, True)
    with job_lock.job_lock(job_lock.MAPS_LOADER_LOCK_KEY, what="карты") as снова:
        assert снова is True, "замок остался висеть после загрузки"
