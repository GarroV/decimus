"""Предел частоты запросов к MCP: по токену и по адресу клиента.

Окно скользящее, в памяти процесса: сервер один (`ThreadingHTTPServer`), и
счётчик в базе стоил бы тех обращений, от которых он бережёт. Свой модуль, а не
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

WINDOW_SEC = 60.0
#: Запросов в минуту с одного токена: живой диалог с Claude — единицы в минуту.
TOKEN_PER_MINUTE = 120
#: Запросов в минуту с одного адреса, включая запросы с неверным токеном.
#: Выше токенного: за одним адресом (прокси, офис) бывает несколько токенов.
ADDRESS_PER_MINUTE = 600
#: С какого числа счётчиков чистить молчащие ключи.
SWEEP_AFTER = 1024

#: Код ошибки JSON-RPC в диапазоне серверных ошибок; по смыслу HTTP 429.
CODE_RATE_LIMITED = -32029
RATE_LIMITED = "Слишком много запросов: подождите минуту и повторите"


class WindowLimiter:
    """Скользящее окно по ключу. Потокобезопасно."""

    def __init__(
        self,
        limit: int,
        clock: Callable[[], float] = time.monotonic,
        window: float = WINDOW_SEC,
    ) -> None:
        self._limit = limit
        self._clock = clock
        self._window = window
        self._lock = threading.Lock()
        self._seen: dict[str, deque[float]] = {}

    def allow(self, key: str) -> bool:
        """Учесть запрос; `False` — предел за окно выбран, запрос не учтён."""
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
    """Два счётчика сервера: по адресу и по токену."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.by_address = WindowLimiter(ADDRESS_PER_MINUTE, clock)
        self.by_token = WindowLimiter(TOKEN_PER_MINUTE, clock)
