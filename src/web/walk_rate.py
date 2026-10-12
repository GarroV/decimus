"""Предел частоты запросов мини-аппа обхода по чату (#529, #710).

Адреса обхода открыты без учётки: подпись Telegram проверяется дёшево, но
каждый подписанный запрос дальше ходит в Postgres, а кадр ещё и пишется на
диск до 10 МБ. Предел считается по номеру чата сразу после подписи — до базы —
в памяти процесса: сервис обхода один (`src.web.walk_main`, waitress в одном
процессе), и счётчик в базе сам стоил бы того обращения, от которого бережём.

Пределы с запасом на живой обход: аудитор снимает кадры подряд, а приложение
после связи досылает накопленное пачкой. Отказ — 429 с текстом «слишком
часто»; запрос можно повторить через минуту.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable

WINDOW_SEC = 60.0
#: Кадров в минуту с одного чата: пачка досылки после связи укладывается.
PHOTO_PER_MINUTE = 120
#: Прочих запросов в минуту с одного чата: чтение, запись, показ кадров.
OTHER_PER_MINUTE = 600

#: С какого числа счётчиков чистить молчащие чаты.
SWEEP_AFTER = 256

PHOTO = "photo"
OTHER = "other"
_LIMITS = {PHOTO: PHOTO_PER_MINUTE, OTHER: OTHER_PER_MINUTE}


class ChatRate:
    """Скользящее окно по (чат, вид запроса). Потокобезопасно."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._seen: dict[tuple[int, str], deque[float]] = {}

    def allow(self, chat_id: int, kind: str = OTHER) -> bool:
        """Учесть запрос; `False` — предел за минуту уже выбран, запрос не учтён."""
        now = self._clock()
        with self._lock:
            stamps = self._seen.setdefault((chat_id, kind), deque())
            while stamps and now - stamps[0] >= WINDOW_SEC:
                stamps.popleft()
            if len(stamps) >= _LIMITS[kind]:
                return False
            stamps.append(now)
            if len(self._seen) > SWEEP_AFTER:
                self._forget_idle(now)
            return True

    def _forget_idle(self, now: float) -> None:
        # Чаты, молчащие дольше окна, не держим: память не растёт с числом чатов.
        idle = [k for k, v in self._seen.items() if not v or now - v[-1] >= WINDOW_SEC]
        for key in idle:
            del self._seen[key]


#: Общий счётчик процесса обхода.
CHAT_RATE = ChatRate()
