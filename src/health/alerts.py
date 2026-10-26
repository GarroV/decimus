"""Оповещения владельцу о смене состояния подключений (D641).

Бот после своих проверок (ключи и службы — раз в 15 минут, входы Dodo IS — раз в час) берёт
цвета подключений у той же функции, что красит плитки (`src/health/rows.py`), сверяет их с
последним ОПОВЕЩЁННЫМ состоянием из `health.alerts` и пишет в канал FURCA
(`src/notify/furca.py`) только при смене: сломалось — `alert`, снова зелёное — `done`.
Правила — `src/domain/health_alerts.py`, тексты — `src/health/alert_texts.py`.

**Что оповещает.** Вход Dodo IS каждой страны отдельно (`dodo_is:<страна>`): красный и жёлтый.
Сборы (агрегаторы, карты, таблица контроля, обучение): красный и жёлтый. Ключи и службы
(OpenAI, бот, хранилище, iSpring): только красный. Pointer-ключ не пробуется по расписанию —
его покрывает ночной сбор карт, отдельной тревоги по нему нет.

**Адресат — только владелец** (его «да» в D641). Канала нет (`FURCA_NOTIFY_URL` или
`FURCA_SECRET` не заданы) — оповещения выключены и ничего не пишется, в том числе состояние:
когда канал включат, первый заход зафиксирует то, что уже есть, и не пришлёт пачку.
**В демо не уходит ничего никогда** (`WEB_DEMO=1`), даже если канал задан.

**Сбой отправки не роняет цикл**: строка в журнал, состояние не помечается оповещённым,
следующий заход повторит; остальные сообщения этого захода не шлются, чтобы не ждать таймаут
на каждом.

Один заход в один момент — под замком базы: два цикла бота зовут его после своих проверок.
"""

from __future__ import annotations

import logging
import os
import urllib.error
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from src.db import health_store
from src.db import ratings_read as ratings
from src.db.errors import DbError
from src.db.job_lock import HEALTH_ALERTS_LOCK_KEY, job_lock
from src.domain import health_alerts as rules
from src.domain.demo import DEMO_VAR
from src.domain.health import GREEN, GREY, Status
from src.domain.public_urls import ADMIN_PUBLIC_URL_VAR, parse_public_url
from src.notify import furca

from . import alert_texts as texts
from . import checks
from .rows import Row
from .rows import build as build_rows

logger = logging.getLogger(__name__)

#: Код строки состояния канала оповещений в `health.checks` (читает вкладка «Подключения»).
CHANNEL_CODE = "alerts_channel"
#: Язык сообщений: адресат один, владелец.
OWNER_LANG = "ru"
DODOIS_TAB_PATH = "/administration?tab=dodois"
DODOIS_PREFIX = "dodo_is:"

Send = Callable[[tuple[str, str], str, str], None]


@dataclass(frozen=True)
class Signal:
    """Состояние одного подключения для оповещений."""

    code: str
    level: str
    row: Row


def is_demo(env: Mapping[str, str]) -> bool:
    """Стенд демо: оповещения не уходят никогда, что бы ни было в канале."""
    return (env.get(DEMO_VAR) or "").strip() not in ("", "0")


def signals(found: tuple[Row, ...]) -> list[Signal]:
    """Что из строк плиток подлежит оповещению; код — `dodo_is:RS`, `aggregators`, …"""
    out: list[Signal] = []
    for row in found:
        if row.kind == checks.DODOIS:
            if not row.country:
                continue
            code = f"{DODOIS_PREFIX}{row.country}"
            red_only = False
        elif row.kind == checks.LOAD:
            code, red_only = row.code, False
        elif row.kind == checks.PROBE:
            conn = checks.connection(row.code)
            if conn is None or not conn.scheduled:
                continue  # Pointer: по кнопке; его покрывает ночной сбор карт
            code, red_only = row.code, True
        else:
            continue
        level = rules.level_of(row.status.light, red_only=red_only)
        if level is not None:
            out.append(Signal(code, level, row))
    return out


def _stamp(moment: datetime | None) -> str:
    return "—" if moment is None else moment.astimezone(UTC).strftime("%d.%m %H:%M")


def _body(signal: Signal, lang: str, url: str | None) -> str:
    """Что сказать в сообщении о поломке."""
    status = signal.row.status
    suffix = status.reason.removeprefix("health.reason.")
    row = signal.row
    if row.kind == checks.DODOIS:
        key = f"alert.dodois.{suffix}"
        if key not in texts.ALERT_TEXTS:
            key = "alert.dodois.dodois_failed"
        tail = (
            texts.text("alert.dodois_tail", lang, url=url)
            if url
            else texts.text("alert.dodois_tail_nourl", lang)
        )
        return texts.text(key, lang, **status.params) + tail
    if row.kind == checks.LOAD:
        key = (
            f"alert.load.{suffix}" if suffix in ("late", "stopped", "failed") else "alert.load.late"
        )
        return texts.text(key, lang, at=_stamp(status.checked_at))
    key = f"alert.probe.{suffix}"
    if key not in texts.ALERT_TEXTS:
        key = "alert.probe.default"
    return texts.text(key, lang)


def compose(
    signal: Signal,
    send_kind: str,
    *,
    country_names: Mapping[str, str],
    url: str | None,
    lang: str = OWNER_LANG,
) -> str:
    """Текст сообщения: «🔴 Decimus · <подключение>: <причина словами>»."""
    row = signal.row
    if row.kind == checks.DODOIS:
        name = country_names.get(row.country, row.country)
        subject = texts.text("alert.subject.dodois", lang, country=name)
    else:
        subject = texts.text(f"alert.conn.{row.code}", lang)
    if send_kind == rules.SEND_DONE:
        return texts.text("alert.done", lang, subject=subject)
    body = _body(signal, lang, url)
    frame = "alert.red" if signal.level == rules.LEVEL_RED else "alert.yellow"
    return texts.text(frame, lang, subject=subject, body=body)


def process(
    found: list[Signal],
    previous: Mapping[str, str],
    *,
    target: tuple[str, str],
    send: Send,
    country_names: Mapping[str, str],
    url: str | None,
    now: datetime,
) -> int:
    """Решить и отправить; записать оповещённые состояния. Возвращает число отправленных."""
    baseline = not previous
    saved: dict[str, str] = {}
    sent = 0
    for signal in sorted(found, key=lambda s: s.code):
        action = rules.decide(previous.get(signal.code), signal.level, baseline=baseline)
        if action is None:
            if previous.get(signal.code) != signal.level:
                saved[signal.code] = signal.level
            continue
        kind = furca.DONE if action == rules.SEND_DONE else furca.ALERT
        text = compose(signal, action, country_names=country_names, url=url)
        try:
            send(target, text, kind)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            # Состояние не помечено оповещённым — следующий заход повторит. Ключа в тексте
            # исключения нет: он только в заголовке запроса.
            logger.warning(
                "Оповещение %s не ушло (%s), повтор на следующем заходе", signal.code, exc
            )
            break
        saved[signal.code] = signal.level
        sent += 1
    health_store.save_alert_levels(saved, now)
    return sent


def channel_state(env: Mapping[str, str]) -> tuple[tuple[str, str] | None, Status]:
    """Канал, если оповещения включены, и строка о нём для вкладки «Подключения»."""
    if is_demo(env):
        return None, Status(GREY, "health.reason.alerts_demo")
    target = furca.channel(env)
    if target is None:
        return None, Status(GREY, "health.reason.alerts_off")
    return target, Status(GREEN, "health.reason.alerts_on")


def _admin_url(env: Mapping[str, str]) -> str | None:
    try:
        base = parse_public_url(env.get(ADMIN_PUBLIC_URL_VAR) or "", var=ADMIN_PUBLIC_URL_VAR)
    except ValueError:
        return None
    return None if base is None else f"{base}{DODOIS_TAB_PATH}"


def _country_names() -> dict[str, str]:
    try:
        return {c.code: c.name_ru for c in ratings.countries()}
    except DbError:
        return {}


def log_startup(env: Mapping[str, str] = os.environ) -> None:
    """Одна строка на старте бота: включены оповещения или нет."""
    target, status = channel_state(env)
    logger.info(
        "Оповещения владельцу о сбоях подключений: %s",
        "включены" if target is not None else status.reason.removeprefix("health.reason."),
    )


def run_pass(
    now: datetime | None = None,
    *,
    env: Mapping[str, str] | None = None,
    send: Send = furca.send,
) -> int:
    """Один заход оповещений; возвращает число отправленных сообщений."""
    env = os.environ if env is None else env
    moment = now or datetime.now(UTC)
    target, status = channel_state(env)
    try:
        health_store.record(CHANNEL_CODE, status.light, status.reason, moment)
    except DbError:
        logger.warning("Оповещения: состояние канала не записалось", exc_info=True)
    if target is None:
        return 0
    with job_lock(HEALTH_ALERTS_LOCK_KEY, what="оповещения о подключениях") as got:
        if not got:
            return 0
        found = build_rows(moment)
        if found is None:
            return 0
        return process(
            signals(found),
            health_store.alert_levels(),
            target=target,
            send=send,
            country_names=_country_names(),
            url=_admin_url(env),
            now=moment,
        )


def run_pass_safely() -> None:
    """Заход для циклов бота: что бы ни случилось, цикл живёт дальше."""
    try:
        run_pass()
    except Exception:
        logger.exception("Оповещения о подключениях: заход упал")
