"""Лимит частоты API `/api/v1` (#567, D336): скользящее окно в памяти процесса.

**Почему в памяти, а не в базе.** Ограничитель входа (`src/db/web_throttle.py`)
считает НЕУДАЧИ пароля и запирает ключ надолго — другая задача. Здесь нужен
потолок частоты удачных запросов сервиса, и запись в базу на каждый запрос
превратила бы чтение в поток записей. Админка работает одним процессом
(`waitress`, потоки), поэтому счётчик в памяти видит все запросы; перезапуск
его обнуляет — для потолка частоты это приемлемо. Станет процессов несколько —
потолок умножится на их число, и счётчик придётся вынести в базу.

Ключей два: токен (потолок потребителя) и адрес для НЕУДАЧНЫХ предъявлений
(перебор токенов бесполезен — 256 бит, — но каждая попытка стоит похода в базу).
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

#: Запросов в минуту на токен. Swarm кэширует ответы на 5 минут (#567), и ему
#: хватает единиц запросов в минуту; 60 — запас на прогрев кэша всех виджетов.
PER_TOKEN_PER_MINUTE = 60
#: Неудачных предъявлений в минуту с одного адреса.
FAILURES_PER_MINUTE = 20
WINDOW_SECONDS = 60.0
#: Больше ключей не держим: снаружи ключи адресов плодит кто угодно.
MAX_KEYS = 10_000


@dataclass
class Window:
    """Скользящее окно: «можно ли ещё» и «сколько ждать». Потокобезопасно."""

    limit: int
    seconds: float = WINDOW_SECONDS
    clock: Callable[[], float] = time.monotonic
    _hits: dict[str, deque[float]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _fresh(self, key: str, now: float) -> deque[float]:
        hits = self._hits.get(key)
        if hits is None:
            if len(self._hits) >= MAX_KEYS:
                self._drop_stale(now)
            hits = deque()
            self._hits[key] = hits
        while hits and hits[0] <= now - self.seconds:
            hits.popleft()
        return hits

    def _drop_stale(self, now: float) -> None:
        for key in [k for k, v in self._hits.items() if not v or v[-1] <= now - self.seconds]:
            del self._hits[key]
        if len(self._hits) >= MAX_KEYS:
            # Все ключи живые — снаружи идёт поток с разных адресов. Сброс всех
            # счётчиков лучше, чем рост памяти без предела.
            self._hits.clear()

    def hit(self, key: str) -> int:
        """Записать обращение. 0 — пропущено; иначе — через сколько секунд можно."""
        now = self.clock()
        with self._lock:
            hits = self._fresh(key, now)
            if len(hits) >= self.limit:
                return max(1, int(hits[0] + self.seconds - now) + 1)
            hits.append(now)
            return 0

    def blocked(self, key: str) -> int:
        """Сколько ждать, не записывая обращение. 0 — не заперт."""
        now = self.clock()
        with self._lock:
            hits = self._fresh(key, now)
            if len(hits) >= self.limit:
                return max(1, int(hits[0] + self.seconds - now) + 1)
            return 0
