"""Предел частоты запросов к MCP: по токену и по адресу клиента.

Окно скользящее, в памяти процесса. При `RATE_WINDOW_SHARED=1` (нужно, когда
процессов больше одного: второй контейнер или перекрытие при выкатке удваивали бы
предел, F-110) оно ОБЩЕЕ — в базе (`src/db/rate_window.py`); тогда окно процесса
остаётся пред-чеком и запасным: база молчит или замок ключа занят — считаем в
памяти, запрос не ждёт и не падает. Флаг не задан — база на горячем пути не
трогается вовсе. Свой модуль, а не
`src/web/walk_rate.py`: блоки `mcp` и `web` друг друга не импортируют, а тот
счётчик заточен под номер чата и свои виды запросов.

Ключ токена — отпечаток (SHA-256), а не он сам: счётчик живёт в памяти процесса,
и дамп памяти не должен приносить готовые токены. Превышение — HTTP 429 и ошибка
JSON-RPC `CODE_RATE_LIMITED`; запрос можно повторить, когда окно освободится.
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections import deque
from collections.abc import Callable

from src.db import rate_window

WINDOW_SEC = 60.0
#: Запросов в минуту с одного токена: живой диалог с Claude — единицы в минуту.
TOKEN_PER_MINUTE = 120
#: Запросов в минуту с одного адреса, включая запросы с неверным токеном.
#: Выше токенного: за одним адресом (прокси, офис) бывает несколько токенов.
ADDRESS_PER_MINUTE = 600
#: Пределы в общей таблице (`rate_windows.scope`).
SCOPE_ADDRESS = "mcp.address"
SCOPE_TOKEN = "mcp.token"  # noqa: S105 — имя предела, не секрет
#: С какого числа счётчиков чистить молчащие ключи.
SWEEP_AFTER = 1024

#: Код ошибки JSON-RPC в диапазоне серверных ошибок; по смыслу HTTP 429.
CODE_RATE_LIMITED = -32029
RATE_LIMITED = "Слишком много запросов: подождите минуту и повторите"


class WindowLimiter:
    """Скользящее окно по ключу. Потокобезопасно.

    `scope` задан И включён флаг `RATE_WINDOW_SHARED` — окно общее между процессами
    (таблица `rate_windows`), а окно процесса остаётся и пред-чеком (в памяти уже
    предел — отказ без базы: локальных отметок не больше общих), и запасным, когда
    база не отвечает или замок ключа занят. Иначе — только окно процесса, база на
    горячем пути не трогается.
    """

    def __init__(
        self,
        limit: int,
        clock: Callable[[], float] = time.monotonic,
        window: float = WINDOW_SEC,
        scope: str | None = None,
    ) -> None:
        self._limit = limit
        self._clock = clock
        self._window = window
        self._scope = scope
        self._lock = threading.Lock()
        self._seen: dict[str, deque[float]] = {}

    def allow(self, key: str) -> bool:
        """Учесть запрос; `False` — предел за окно выбран, запрос не учтён."""
        if self._scope is not None and rate_window.enabled():
            return self._allow_shared(self._scope, key)
        return self._allow_local(key)

    def _allow_shared(self, scope: str, key: str) -> bool:
        if self._is_full(key):
            return False
        shared = rate_window.try_allow(
            scope=scope, key=key, limit=self._limit, window_sec=self._window
        )
        if shared is None:
            return self._allow_local(key)
        if shared:
            self._record(key)
        return shared

    def _is_full(self, key: str) -> bool:
        now = self._clock()
        with self._lock:
            stamps = self._seen.get(key)
            if stamps is None:
                return False
            while stamps and now - stamps[0] >= self._window:
                stamps.popleft()
            return len(stamps) >= self._limit

    def _record(self, key: str) -> None:
        now = self._clock()
        with self._lock:
            self._seen.setdefault(key, deque()).append(now)
            if len(self._seen) > SWEEP_AFTER:
                self._forget_idle(now)

    def _allow_local(self, key: str) -> bool:
        now = self._clock()
        with self._lock:
            stamps = self._seen.setdefault(key, deque())
            while stamps and now - stamps[0] >= self._window:
                stamps.popleft()
            if len(stamps) >= self._limit:
                return False
            stamps.append(now)
            if len(self._seen) > SWEEP_AFTER:
                self._forget_idle(now)
            return True

    def _forget_idle(self, now: float) -> None:
        idle = [k for k, v in self._seen.items() if not v or now - v[-1] >= self._window]
        for key in idle:
            del self._seen[key]


def token_key(token: str) -> str:
    """Ключ счётчика для токена: отпечаток, не сам токен."""
    return hashlib.sha256(token.encode("utf-8", "surrogateescape")).hexdigest()


class McpRate:
    """Два счётчика сервера: по адресу и по токену.

    `shared` — общие между процессами (сервер); без него только окно процесса.
    """

    def __init__(
        self, clock: Callable[[], float] = time.monotonic, *, shared: bool = False
    ) -> None:
        self.by_address = WindowLimiter(
            ADDRESS_PER_MINUTE, clock, scope=SCOPE_ADDRESS if shared else None
        )
        self.by_token = WindowLimiter(
            TOKEN_PER_MINUTE, clock, scope=SCOPE_TOKEN if shared else None
        )
