"""Предел частоты запросов мини-аппа обхода по чату (#529, #710).

Адреса обхода открыты без учётки: подпись Telegram проверяется дёшево, но
каждый подписанный запрос дальше ходит в Postgres, а кадр ещё и пишется на
диск до 10 МБ. Предел считается по номеру чата сразу после подписи — до тяжёлых
обращений. Окно в памяти процесса; при `RATE_WINDOW_SHARED=1` — ОБЩЕЕ между процессами
(F-110, `src/db/rate_window.py`), когда экземпляров больше одного. База молчит или замок
ключа занят — окно процесса, запрос не ждёт и не падает. Флаг не задан — база на горячем
пути не трогается вовсе.

Пределы с запасом на живой обход: аудитор снимает кадры подряд, а приложение
после связи досылает накопленное пачкой. Отказ — 429 с текстом «слишком
часто»; запрос можно повторить через минуту.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable

from src.db import rate_window

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
    """Скользящее окно по (чат, вид запроса). Потокобезопасно.

    `shared` и включённый `RATE_WINDOW_SHARED` — окно общее между процессами (таблица
    `rate_windows`); окно процесса остаётся пред-чеком и запасным на случай, когда
    база не отвечает или замок занят. Флаг не задан — только окно процесса.
    """

    def __init__(
        self, clock: Callable[[], float] = time.monotonic, *, shared: bool = False
    ) -> None:
        self._clock = clock
        self._shared = shared
        self._lock = threading.Lock()
        self._seen: dict[tuple[int, str], deque[float]] = {}

    def allow(self, chat_id: int, kind: str = OTHER) -> bool:
        """Учесть запрос; `False` — предел за минуту уже выбран, запрос не учтён."""
        if self._shared and rate_window.enabled():
            return self._allow_shared(chat_id, kind)
        return self._allow_local(chat_id, kind)

    def _allow_shared(self, chat_id: int, kind: str) -> bool:
        # Пред-чек в памяти: локальных отметок не больше общих, поэтому предел,
        # выбранный здесь, выбран и там — база не нужна.
        if self._is_full(chat_id, kind):
            return False
        shared = rate_window.try_allow(
            scope=f"walk.{kind}", key=str(chat_id), limit=_LIMITS[kind], window_sec=WINDOW_SEC
        )
        if shared is None:
            return self._allow_local(chat_id, kind)
        if shared:
            self._record(chat_id, kind)
        return shared

    def _is_full(self, chat_id: int, kind: str) -> bool:
        now = self._clock()
        with self._lock:
            stamps = self._seen.get((chat_id, kind))
            if stamps is None:
                return False
            while stamps and now - stamps[0] >= WINDOW_SEC:
                stamps.popleft()
            return len(stamps) >= _LIMITS[kind]

    def _record(self, chat_id: int, kind: str) -> None:
        now = self._clock()
        with self._lock:
            self._seen.setdefault((chat_id, kind), deque()).append(now)
            if len(self._seen) > SWEEP_AFTER:
                self._forget_idle(now)

    def _allow_local(self, chat_id: int, kind: str) -> bool:
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
CHAT_RATE = ChatRate(shared=True)
