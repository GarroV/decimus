"""Вход по ссылке: сервер начинает device flow, сам опрашивает Dodo IS и пишет вход (D640).

Коллега открыл ссылку-приглашение и нажал «Войти в Dodo IS» — ТОЛЬКО это начинает вход
(`start`); открытие страницы (в том числе ботом-превью мессенджера) ничего не запускает и
кода Dodo IS не тратит. Дальше всё на сервере: поток раз в `interval` секунд спрашивает
`connect/token`, браузер лишь опрашивает наш `status` и о коде устройства не знает.

**Состояние в памяти процесса веба**, по номеру приглашения: код Dodo IS живёт пять минут,
перезапуск процесса значит «нажмите ещё раз», пока жива ссылка. Один вход на приглашение:
повторное нажатие при идущем входе показывает идущий, а не заводит второй.

**Ссылка гасится только записью входа** (`dodois_logins.save_login`, одна транзакция); если
её за это время отозвали, вход не пишется (`InviteUnusable`) — состояние `revoked`.

Значения ключей и код устройства не пишутся ни в журнал, ни в исключения.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from src.db import dodois_logins as store
from src.db import journals
from src.db.errors import DbError
from src.db.space import SYSTEM_SPACE, acting_space
from src.domain import dodois as rules
from src.domain.dodois import Invite
from src.domain.journal import DOOR_WEB

from . import client, service
from .client import Credentials, DeviceStart, DodoisError, TokenPair

logger = logging.getLogger(__name__)

#: Состояния входа по ссылке, как их видит страница.
IDLE = "idle"
PENDING = "pending"
DONE = "done"
EXPIRED = "expired"
DENIED = "denied"
REVOKED = "revoked"
FAILED = "failed"
#: Состояния, после которых на той же ссылке можно начать заново.
RESTARTABLE = frozenset({EXPIRED, DENIED, FAILED})

#: Сколько хранить итог завершённого входа.
KEEP_DONE_SEC = 600
#: Сколько входов держим одновременно: страна одна, приглашений мало; предел — от забивания.
MAX_FLOWS = 64
#: Надбавка к паузе опроса при `slow_down` (требует стандарт).
SLOW_DOWN_SEC = 5
#: Хосты, на которые ведёт ссылка подтверждения: страница ссылки не должна уводить куда попало.
TRUSTED_SUFFIXES = (".dodois.com", ".dodois.io")

#: Код записи в журнале действий — имя публичного маршрута начала входа: подписи журнала
#: сверяются с маршрутами (`tests/test_web_journal_labels.py`), а вход по ссылке пишется без
#: сессии, от имени выдавшего.
ACTION_USED = "dodois_connect_start"


@dataclass
class Flow:
    """Идущий или недавно законченный вход по одному приглашению."""

    invite: Invite
    ip: str | None
    started: float
    state: str = PENDING
    user_code: str = ""
    link: str = ""
    deadline: float = 0.0
    finished: float = 0.0
    reason: str = ""
    # Код устройства живёт ТОЛЬКО здесь, в памяти потока; наружу не отдаётся.
    _device_code: str = field(default="", repr=False)


_lock = threading.Lock()
_flows: dict[int, Flow] = {}


def _sweep(now: float) -> None:
    for key in [k for k, f in _flows.items() if f.finished and now - f.finished > KEEP_DONE_SEC]:
        del _flows[key]


def current(invite_id: int) -> Flow | None:
    """Вход по приглашению: идущий или недавно законченный."""
    with _lock:
        _sweep(time.monotonic())
        return _flows.get(invite_id)


def trusted_link(link: str) -> bool:
    """Ссылка подтверждения — https на хост Dodo IS: чужой адрес на страницу не выводим."""
    parts = urlsplit(link)
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and any(host.endswith(s) for s in TRUSTED_SUFFIXES)


def start(
    invite: Invite,
    *,
    creds: Credentials,
    ip: str | None,
    spawn: bool = True,
) -> Flow:
    """Начать вход по приглашению; идущий вход возвращается как есть.

    Нет связи с Dodo IS или ключи приложения не приняты — `DodoisError`, вход не заведён.
    `spawn=False` — без потока (тесты опрашивают сами через `poll_once`).
    """
    with _lock:
        _sweep(time.monotonic())
        have = _flows.get(invite.id)
        if have is not None and have.state == PENDING:
            return have
        if len([f for f in _flows.values() if f.state == PENDING]) >= MAX_FLOWS:
            raise DodoisError(client.RATE_LIMITED)
    device = client.start_device(creds, rules.INTL)
    if not trusted_link(device.verification_uri):
        raise DodoisError(client.NETWORK)
    flow = _new_flow(invite, device, ip)
    with _lock:
        _flows[invite.id] = flow
    if spawn:
        thread = threading.Thread(
            target=_run, args=(flow, creds, device), daemon=True, name="dodois-flow"
        )
        thread.start()
    return flow


def _new_flow(invite: Invite, device: DeviceStart, ip: str | None) -> Flow:
    now = time.monotonic()
    flow = Flow(
        invite=invite,
        ip=ip,
        started=now,
        user_code=device.user_code,
        link=device.verification_uri,
        deadline=now + device.expires_in,
    )
    flow._device_code = device.device_code
    return flow


def _finish(flow: Flow, state: str, reason: str = "") -> None:
    with _lock:
        flow.state, flow.reason, flow.finished = state, reason, time.monotonic()
        flow._device_code = ""


def poll_once(
    flow: Flow,
    creds: Credentials,
    *,
    interval: float,
) -> tuple[bool, float]:
    """Один опрос Dodo IS. Возвращает (закончено ли, пауза до следующего опроса)."""
    if time.monotonic() >= flow.deadline:
        _finish(flow, EXPIRED)
        return True, interval
    try:
        answer = client.poll_device(creds, rules.INTL, flow._device_code)
    except DodoisError as exc:
        _finish(flow, FAILED, exc.kind)
        return True, interval
    if answer == client.PENDING:
        return False, interval
    if answer == client.SLOW_DOWN:
        return False, interval + SLOW_DOWN_SEC
    if answer == client.EXPIRED:
        _finish(flow, EXPIRED)
    elif answer == client.DENIED:
        _finish(flow, DENIED)
    elif isinstance(answer, TokenPair):
        _complete(flow, answer)
    else:  # неизвестный ответ — как сбой, а не как успех
        _finish(flow, FAILED, client.NETWORK)
    return True, interval


def _complete(flow: Flow, pair: TokenPair) -> None:
    invite = flow.invite
    try:
        replaced = store.get_login(invite.country) is not None
        service.attach(
            country=invite.country,
            pair=pair,
            issued_by=invite.issued_by,
            source=rules.SOURCE_INVITE,
            invite_id=invite.id,
        )
    except store.InviteUnusable:
        _finish(flow, REVOKED)
        return
    except DbError:
        logger.error("Dodo IS %s: вход по ссылке не записался", invite.country)
        _finish(flow, FAILED, "write_failed")
        return
    _finish(flow, DONE)
    record_used(invite, flow.ip, replaced)


def record_used(invite: Invite, ip: str | None, replaced: bool) -> None:
    """Погашение ссылки — в журнал действий от имени выдавшего, без токена и без ключей."""
    journals.record_action(
        user_id=invite.issued_by_id,
        role=invite.issued_by_role,
        tenant=invite.issued_by_tenant,
        action=ACTION_USED,
        target=(
            f"country={invite.country}; invite={invite.id}; replaced={'yes' if replaced else 'no'}"
        ),
        outcome="ok",
        ip=ip,
        credential=f"invite:{invite.id}",
        door=DOOR_WEB,
    )


def _run(flow: Flow, creds: Credentials, device: DeviceStart) -> None:
    interval = float(device.interval)
    try:
        with acting_space(SYSTEM_SPACE):
            while True:
                time.sleep(interval)
                done, interval = poll_once(flow, creds, interval=interval)
                if done:
                    return
    except Exception:
        logger.exception("Dodo IS %s: вход по ссылке упал", flow.invite.country)
        _finish(flow, FAILED, "network")


def forget_all() -> None:
    """Забыть все входы — для тестов."""
    with _lock:
        _flows.clear()
