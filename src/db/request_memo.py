"""Память одного HTTP-запроса для чтений, которые страница просит из разных блоков.

Страница собирается из независимых блоков, и каждый читает справочник сам:
`/ratings` дважды спрашивала страны и периоды, `/country` трижды — географию
точек. Блоки не знают друг о друге, поэтому передавать прочитанное явно значило
бы перекроить половину модулей; вместо этого чтение, которое от запроса не
зависит, запоминается на время ОДНОГО запроса и забывается вместе с ним.

Границы, ради которых это безопасно:

- Память существует только внутри `scope()` — веб открывает её на запросе
  (`src/web/app.py`). Вне запроса (бот, MCP, тесты, консольные команды)
  `memoized` просто зовёт загрузчик: поведение прежнее.
- Ключ включает ВСЕ параметры чтения, в первую очередь охват читающего
  (`Reach`: пространство, чьи проверки, какие страны). Читающий другого охвата
  в тот же ключ не попадёт; а память к тому же не переживает запрос, так что
  между людьми и запросами утечь нечему.
- Веб открывает её только на `GET`/`HEAD`: запрос, который пишет, читает как
  раньше — после записи в том же запросе прочитанное не может оказаться
  устаревшим.
- Отказ загрузчика не запоминается.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Any, TypeVar

T = TypeVar("T")

_MEMO: ContextVar[dict[Hashable, Any] | None] = ContextVar("db_request_memo", default=None)


def begin(*, enabled: bool = True) -> Token[dict[Hashable, Any] | None]:
    """Начать запрос; вернуть метку, по которой `end` его закроет.

    `enabled=False` — память явно выключена (`None`), а не просто не открыта:
    запрос начинается в известном состоянии, даже если закрытие прошлого не
    дошло и в контексте осталась чужая память.
    """
    return _MEMO.set({} if enabled else None)


def end(token: Token[dict[Hashable, Any] | None]) -> None:
    """Закрыть память, открытую `begin`: всё запомненное забывается."""
    _MEMO.reset(token)


@contextmanager
def scope() -> Iterator[None]:
    """Память на время блока. Вложенный вызов получает свою, чистую."""
    token = begin()
    try:
        yield
    finally:
        end(token)


def memoized(key: Hashable, load: Callable[[], T]) -> T:
    """Прочитанное под `key` — один раз за открытую память; вне её — просто `load()`."""
    memo = _MEMO.get()
    if memo is None:
        return load()
    if key in memo:
        return memo[key]  # type: ignore[no-any-return]
    value = load()
    memo[key] = value
    return value
