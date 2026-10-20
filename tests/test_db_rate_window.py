"""F-110: общее окно частоты запросов (`src/db/rate_window.py`, миграция `0082`).

Ядро: предел считается ОДИН на все процессы. Два предела в памяти двух процессов
пропускали вдвое больше, и ничто в приложении этого не показывало. Поэтому «два
процесса» здесь — два независимых ограничителя с пустой памятью каждый и общая база.
Окно (чистая функция `admit`) проверяется арифметикой, без базы.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta

import pytest
from conftest import requires_db

pytest.importorskip("psycopg")

from src.db import rate_window
from src.mcp.ratelimit import WindowLimiter
from src.web.walk_rate import ChatRate


@pytest.fixture
def общее_окно(monkeypatch: pytest.MonkeyPatch) -> None:
    """Включает общее окно (`RATE_WINDOW_SHARED`): по умолчанию оно выключено."""
    monkeypatch.setenv(rate_window.SHARED_VAR, "1")


WINDOW = timedelta(seconds=60)
T0 = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)


def test_запрос_в_пределе_учитывается_сверх_предела_нет() -> None:
    stamps: tuple[datetime, ...] = ()
    решения = []
    for _ in range(4):
        stamps, ok = rate_window.admit(stamps, now=T0, window=WINDOW, limit=3)
        решения.append(ok)

    assert решения == [True, True, True, False]
    assert len(stamps) == 3, "отказанный запрос не должен учитываться"


def test_окно_скользит_старый_запрос_выходит_ровно_через_окно() -> None:
    stamps, _ = rate_window.admit((), now=T0, window=WINDOW, limit=1)

    _, внутри = rate_window.admit(
        stamps, now=T0 + WINDOW - timedelta(milliseconds=1), window=WINDOW, limit=1
    )
    _, на_границе = rate_window.admit(stamps, now=T0 + WINDOW, window=WINDOW, limit=1)

    assert (внутри, на_границе) == (False, True), "граница окна — как в окне процесса: `>= window`"


def test_без_базы_ограничитель_считает_в_памяти_процесса(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    окно = WindowLimiter(2, scope="test.fallback")

    решения = [окно.allow("k") for _ in range(3)]

    assert решения == [True, True, False], (
        "база молчит — предел не должен пропасть и не должен падать"
    )


def test_без_базы_чат_обхода_считает_в_памяти_процесса(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    счёт = ChatRate(shared=True)

    пропущено = [счёт.allow(1, "photo") for _ in range(121)]

    assert sum(пропущено) == 120 and not пропущено[-1]


@requires_db
@pytest.mark.usefixtures("общее_окно")
def test_предел_общий_у_двух_процессов(db_env: str) -> None:
    первый = WindowLimiter(3, scope="test.shared")
    второй = WindowLimiter(3, scope="test.shared")  # другой процесс: память пуста

    решения = [
        первый.allow("k"),
        второй.allow("k"),
        первый.allow("k"),
        второй.allow("k"),
        первый.allow("k"),
    ]

    assert решения == [True, True, True, False, False], (
        "каждый процесс пропустил бы свои три — предел удвоился бы"
    )


@requires_db
@pytest.mark.usefixtures("общее_окно")
def test_разные_ключи_и_разные_пределы_не_делят_счёт(db_env: str) -> None:
    окно = WindowLimiter(1, scope="test.keys")
    другой = WindowLimiter(1, scope="test.other")

    assert [окно.allow("a"), окно.allow("b"), другой.allow("a")] == [True, True, True]
    assert окно.allow("a") is False


@requires_db
def test_параллельные_запросы_общее_окно_не_пропускает_сверх_предела(db_env: str) -> None:
    """Без замка на ключ параллельные процессы читают одно число и пропускают все.

    Замок неблокирующий: проигравший гонку получает `None` (его решит окно процесса), —
    поэтому проверяется то, что решила именно база: «да» не больше предела.
    """
    limit, workers = 5, 24
    итог: list[bool | None] = []
    старт = threading.Barrier(workers)

    def запрос() -> None:
        старт.wait()
        итог.append(rate_window.allow(scope="test.race", key="k", limit=limit, window_sec=60))

    потоки = [threading.Thread(target=запрос) for _ in range(workers)]
    for п in потоки:
        п.start()
    for п in потоки:
        п.join()

    assert sum(1 for x in итог if x is True) <= limit, (
        f"база пропустила {итог.count(True)} при пределе {limit}"
    )
    assert any(x is True for x in итог), "никто не получил решения базы — тест ничего не проверяет"


@requires_db
def test_окно_в_базе_освобождается_со_временем(db_env: str) -> None:
    def запрос(at: datetime) -> bool:
        return rate_window.allow(scope="test.slide", key="k", limit=1, window_sec=60, now=at)

    assert [запрос(T0), запрос(T0 + timedelta(seconds=30))] == [True, False]
    assert запрос(T0 + timedelta(seconds=61)) is True


@requires_db
def test_просроченные_строки_чистятся_попутно(db_env: str) -> None:
    import psycopg

    rate_window.allow(scope="test.sweep", key="old", limit=5, window_sec=60, now=T0)

    rate_window.allow(
        scope="test.sweep", key="new", limit=5, window_sec=60, now=T0 + timedelta(minutes=5)
    )

    with psycopg.connect(db_env) as conn:
        left = conn.execute(
            "select count(*) from rate_windows where scope = 'test.sweep'"
        ).fetchone()
    assert left == (1,), "строка давно прошедшего окна осталась в таблице"


@requires_db
def test_в_базе_лежит_отпечаток_а_не_ключ(db_env: str) -> None:
    import psycopg

    rate_window.allow(scope="test.fp", key="203.0.113.7", limit=5, window_sec=60)

    with psycopg.connect(db_env) as conn:
        rows = conn.execute(
            "select key_fingerprint from rate_windows where scope = 'test.fp'"
        ).fetchall()
    assert rows == [(rate_window.key_fingerprint("203.0.113.7"),)]
    assert "203.0.113.7" not in rows[0][0]


@requires_db
@pytest.mark.usefixtures("общее_окно")
def test_ограничители_сервера_mcp_делят_окно_между_процессами(db_env: str) -> None:
    from src.mcp.ratelimit import TOKEN_PER_MINUTE, McpRate

    первый, второй = McpRate(shared=True), McpRate(shared=True)

    допущено = sum(
        (первый if i % 2 else второй).by_token.allow("tok") for i in range(TOKEN_PER_MINUTE + 10)
    )

    assert допущено == TOKEN_PER_MINUTE, "каждый процесс пропустил бы свой предел целиком"


@requires_db
@pytest.mark.usefixtures("общее_окно")
def test_предел_чата_обхода_общий_у_двух_процессов(
    db_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.web import walk_rate

    monkeypatch.setattr(walk_rate, "_LIMITS", {walk_rate.PHOTO: 3, walk_rate.OTHER: 50})
    первый, второй = ChatRate(shared=True), ChatRate(shared=True)

    решения = [(первый, 1), (второй, 1), (первый, 1), (второй, 1), (второй, 2)]
    итог = [счёт.allow(чат, walk_rate.PHOTO) for счёт, чат in решения]

    assert итог == [True, True, True, False, True], "предел чата считался в памяти процесса"


def _база_не_должна_трогаться(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    звали: list[str] = []

    def запрет(*_a: object, **_k: object) -> None:
        звали.append("база")
        raise AssertionError("горячий путь полез в базу")

    from types import SimpleNamespace

    # Строка подключения нужна, чтобы дойти до соединения: без неё обращение к базе
    # оборвалось бы раньше, на настройках, и проверка не поймала бы лишнего хода.
    monkeypatch.setattr(rate_window, "check_environment", lambda: SimpleNamespace(dsn="x"))
    monkeypatch.setattr(rate_window, "connection", запрет)
    return звали


def test_флаг_выключен_база_на_горячем_пути_не_трогается(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.mcp.ratelimit import McpRate

    monkeypatch.delenv(rate_window.SHARED_VAR, raising=False)
    звали = _база_не_должна_трогаться(monkeypatch)
    mcp, обход = McpRate(shared=True), ChatRate(shared=True)

    решения = [mcp.by_token.allow("t"), mcp.by_address.allow("a"), обход.allow(1, "photo")]

    assert решения == [True, True, True] and звали == []


def test_флаг_включён_и_локальное_окно_уже_полно_база_не_трогается(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(rate_window.SHARED_VAR, "1")
    окно = WindowLimiter(2, scope="test.precheck")
    # Локальные отметки есть: общее окно уже сказало «да» дважды.
    окно._record("k")
    окно._record("k")
    звали = _база_не_должна_трогаться(monkeypatch)

    assert окно.allow("k") is False and звали == [], "предел выбран в памяти — база не нужна"


def test_флаг_включён_база_молчит_считаем_в_памяти(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(rate_window.SHARED_VAR, "1")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    окно = WindowLimiter(2, scope="test.down")

    assert [окно.allow("k") for _ in range(3)] == [True, True, False]


@requires_db
@pytest.mark.usefixtures("общее_окно")
def test_замок_ключа_занят_не_ждём_а_считаем_в_памяти(db_env: str) -> None:
    """Чужой процесс держит замок ключа: запрос не блокируется и не получает отказ."""
    import time

    import psycopg

    scope, key = "test.busy", "k"
    fp = rate_window.key_fingerprint(key)
    окно = WindowLimiter(3, scope=scope)
    with psycopg.connect(db_env, autocommit=False) as чужой:
        чужой.execute(
            "select pg_advisory_xact_lock(%s, hashtext(%s))",
            (rate_window.ADVISORY_NAMESPACE, f"{scope}\x1f{fp}"),
        )
        rate_window.allow(scope=scope, key="прогрев", limit=1, window_sec=60)  # пул и соединение
        начало = time.monotonic()
        решения = [окно.allow(key) for _ in range(4)]
        ушло = time.monotonic() - начало

    assert решения == [True, True, True, False], "при занятом замке окно процесса обязано решать"
    assert ушло < 0.1, f"запрос ждал замок {ушло:.1f} с"


@requires_db
def test_запросы_окна_идут_под_короткими_сроками(
    db_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    видно: dict[str, str] = {}
    оригинал = rate_window._DROP_STALE_SQL

    class Курсор:
        pass

    import psycopg

    исходный = psycopg.Cursor.execute

    def execute(self: psycopg.Cursor, query: object, params: object = None, **kw: object):  # type: ignore[no-untyped-def]
        if query == оригинал:
            for имя in ("lock_timeout", "statement_timeout"):
                видно[имя] = self.connection.execute(f"show {имя}").fetchone()[0]  # type: ignore[index]
        return исходный(self, query, params, **kw)  # type: ignore[arg-type]

    monkeypatch.setattr(psycopg.Cursor, "execute", execute)

    rate_window.allow(scope="test.timeouts", key="k", limit=5, window_sec=60)

    assert видно == {"lock_timeout": "200ms", "statement_timeout": "500ms"}
