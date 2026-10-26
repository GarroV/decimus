"""Реестр подключений вкладки «Подключения» (D638) и пробы тех, что пробуются.

Строки делятся на группы (`GROUPS`, порядок групп на экране): системное — ключи и
службы, без которых встаёт работа аудитора, и бэкап; рейтинги и оценки; обучение;
входы Dodo IS. Внутри группы — порядок в `CONNECTIONS`.

Проба возвращает `(цвет, причина)`; `None` — пробовать здесь нечем (в процессе нет
токена бота или доступа к хранилищу), и тогда исход не пишется: иначе веб, у
которого токена нет, затирал бы серым зелёный исход бота. Пишет исход вызывающий
(`src/bot/health_loader.py` по расписанию, веб — по кнопке «Проверить сейчас»).
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

from src.db import service_keys
from src.db.config import load_storage_settings
from src.db.errors import DbError
from src.db.storage import S3PhotoStorage
from src.domain import service_keys as registry
from src.domain.health import GREEN, GREY, RED, YELLOW

from .probes import PROBES, KeyRejected, KeyUnverified

logger = logging.getLogger(__name__)

#: Как часто фоновая задача пробует ключи и службы (#1251: «раз в 15 минут»).
PROBE_EVERY = timedelta(minutes=15)

#: Сколько может пройти между удачными заходами исправного сбора: расписание
#: загрузчика плюс запас. Карты, агрегаторы, обучение — раз в сутки (20 ч свежести
#: и час между проверками, `src/bot/*_loader.py`); таблица контроля — раз в 3 часа.
DAILY_FRESH = timedelta(hours=26)
SHEET_FRESH = timedelta(hours=4)

TELEGRAM_TOKEN_VAR = "TELEGRAM_BOT_TOKEN"  # noqa: S105 — имя переменной, а не токен
TELEGRAM_API = "https://api.telegram.org/bot{token}/getMe"
TIMEOUT_SEC = 15

PROBE = "probe"
LOAD = "load"
CONFIG = "config"
PENDING = "pending"
#: Входы в Dodo IS по странам (D640): строка на страну, цвет — из состояния входа.
DODOIS = "dodois"

#: Группы плиток на экране, по порядку (ключ текста `health.group.<код>`).
SYSTEM = "system"
RATINGS = "ratings"
LEARNING = "learning"
DODO_IS = "dodo_is"
GROUPS = (SYSTEM, RATINGS, LEARNING, DODO_IS)

Outcome = tuple[str, str]


@dataclass(frozen=True)
class Connection:
    """Строка вкладки: код (он же ключ текста `health.conn.<код>`), вид, срок свежести."""

    code: str
    kind: str
    group: str
    fresh_for: timedelta | None = None
    scheduled: bool = True


CONNECTIONS: tuple[Connection, ...] = (
    Connection("storage", PROBE, SYSTEM),
    Connection("openai", PROBE, SYSTEM),
    Connection("telegram", PROBE, SYSTEM),
    Connection("google", CONFIG, SYSTEM),
    # Бэкап делает хост (`vps-backup`, репозиторий vps-infra), приложению его не видно.
    Connection("backup", PENDING, SYSTEM),
    # Pointer пробуется только по кнопке (#1256): лимит 1 запрос в секунду, и проба по
    # расписанию попадала бы в ночной сбор карт и почасовую дозагрузку истории, роняя их.
    # Что ключ работает каждую ночь, показывает строка «maps».
    Connection("pointer", PROBE, RATINGS, scheduled=False),
    Connection("maps", LOAD, RATINGS, DAILY_FRESH),
    Connection("aggregators", LOAD, RATINGS, DAILY_FRESH),
    Connection("sheet", LOAD, RATINGS, SHEET_FRESH),
    Connection("ispring", PROBE, LEARNING),
    Connection("learning", LOAD, LEARNING, DAILY_FRESH),
    # Dodo IS по странам (D640, #951): строка на каждый вход; цвет — из `dodois.logins`,
    # которые продлевает и проверяет бот (`src/bot/dodois_loader.py`).
    Connection("dodo_is", DODOIS, DODO_IS),
)

#: Что фоновая задача пробует раз в `PROBE_EVERY`.
SCHEDULED_CODES = tuple(c.code for c in CONNECTIONS if c.kind == PROBE and c.scheduled)


def connection(code: str) -> Connection | None:
    return next((c for c in CONNECTIONS if c.code == code), None)


def _key(service_code: str) -> Outcome:
    service = registry.service(service_code)
    if service is None:
        return GREY, "health.reason.not_configured"
    try:
        values = {f.code: service_keys.resolve(service.code, f.code) for f in service.fields}
    except DbError:
        logger.warning("Проверка подключений: ключ %s не прочитался", service_code, exc_info=True)
        return YELLOW, "health.reason.unverified"
    if not all(values.values()):
        return GREY, "health.reason.no_key"
    try:
        PROBES[service.code]({k: v for k, v in values.items() if v})
    except KeyRejected:
        return RED, "health.reason.rejected"
    except KeyUnverified:
        return YELLOW, "health.reason.unverified"
    return GREEN, "health.reason.ok"


def _telegram() -> Outcome | None:
    token = (os.environ.get(TELEGRAM_TOKEN_VAR) or "").strip()
    if not token:
        return None
    request = urllib.request.Request(TELEGRAM_API.format(token=token))  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SEC) as response:  # noqa: S310
            answer = json.load(response)
    except urllib.error.HTTPError as exc:
        return (
            (RED, "health.reason.rejected")
            if exc.code in (401, 404)
            else (YELLOW, "health.reason.unverified")
        )
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return YELLOW, "health.reason.unverified"
    return (GREEN, "health.reason.ok") if answer.get("ok") else (RED, "health.reason.rejected")


def _storage() -> Outcome | None:
    try:
        settings = load_storage_settings()
    except DbError:
        return None
    try:
        S3PhotoStorage(settings, fail_fast=True).ping()
    except DbError:
        logger.warning("Проверка подключений: хранилище кадров не ответило", exc_info=True)
        return RED, "health.reason.unreachable"
    return GREEN, "health.reason.ok"


_RUNNERS: dict[str, Callable[[], Outcome | None]] = {
    "openai": lambda: _key("openai"),
    "pointer": lambda: _key("pointer"),
    "ispring": lambda: _key("ispring"),
    "telegram": _telegram,
    "storage": _storage,
}


def run_probe(code: str) -> Outcome | None:
    """Пробовать подключение сейчас. `None` — здесь пробовать нечем."""
    runner = _RUNNERS.get(code)
    return None if runner is None else runner()
