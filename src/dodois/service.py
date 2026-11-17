"""Входы в Dodo IS по странам: записать вход, продлить, проверить «открыто X из Y» (D640b).

Здесь порядок, а не сеть и не SQL: сеть — `client`, база — `src/db/dodois_logins.py`,
правила и состояния — `src/domain/dodois.py`.

**Продление не теряет вход.** Ключ продления у Dodo IS одноразовый: после удачного ответа
прежний мёртв. Поэтому новая пара пишется атомарно (`replace_tokens`) и, если запись не
легла, пробуется ещё несколько раз с той же парой в памяти; не легла совсем — состояние
«запись не легла, повторяем» (`write_failed`) и строка в журнале процесса без значений.
Незаписанная пара зашифрована в STATE_DIR; каждый следующий заход
(раз в час) сначала повторяет запись, а к Dodo IS за новой парой не ходит: ключ продления
в базе уже мёртв, ещё одно продление дало бы «вход истёк». Очередь переживает перезапуск.
Отказ Dodo IS в продлении — «вход истёк»: прежняя пара остаётся в базе, ничего не стирается.

**Оповещения** о сбое входа шлёт не этот модуль, а `src/health/alerts.py` после захода
(D641): здесь только состояние, которое видно на вкладке «Dodo IS».
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from src.db import dodois_logins as store
from src.db import service_keys
from src.db.errors import DbError
from src.domain import dodois as rules
from src.domain.dodois import Login

from . import client
from . import refresh_outbox as outbox
from .client import Credentials, DodoisError, RefreshRejected, TokenPair

logger = logging.getLogger(__name__)

#: Сколько раз пробуем записать новую пару ключей, прежде чем признать сбой, и пауза между ними.
WRITE_TRIES = 4
WRITE_RETRY_SECONDS = 2.0

#: Аварийная копия ответа, пока его запись на диск не удалась. Диск — источник истины;
#: кеш используется только вместе с собственным точным inflight marker.
_unwritten: dict[str, outbox.Pending] = {}


def credentials() -> Credentials | None:
    """Пара ключей приложения: экран «Ключи сервисов», затем окружение; нет — `None`."""
    ident = service_keys.resolve("dodois", "client_id")
    secret = service_keys.resolve("dodois", "client_secret")
    return Credentials(ident, secret) if ident and secret else None


def _expires_at(pair: TokenPair, now: datetime) -> datetime:
    return now + timedelta(seconds=pair.expires_in)


def attach(
    *,
    country: str,
    pair: TokenPair,
    issued_by: str,
    source: str,
    invite_id: int | None,
    now: datetime | None = None,
    contour: str | None = None,
    account: tuple[str | None, str | None] | None = None,
    access_expires_at: datetime | None = None,
    verify: bool = True,
) -> Login:
    """Записать вход страны. Имя и почту учётки Dodo IS берём у `userinfo`, если не заданы.

    `access_expires_at` — когда истекает ключ доступа, если это не «сейчас + срок из ответа»
    (перенесённый вход); `verify=False` — не проверять «открыто X из Y» сразу.
    """
    moment = now or datetime.now(UTC)
    contour = contour or rules.contour_for(country)
    name, email = account if account is not None else client.userinfo(contour, pair.access)
    login = store.save_login(
        country=country,
        contour=contour,
        source=source,
        issued_by=issued_by,
        account_name=name,
        account_email=email,
        scope=pair.scope or rules.SCOPES,
        tokens=store.Tokens(pair.access, pair.refresh),
        access_expires_at=access_expires_at or _expires_at(pair, moment),
        now=moment,
        invite_id=invite_id,
    )
    if not verify:
        return login
    return check(country, now=moment) or login


def _note(
    country: str,
    state: str,
    reason: str | None,
    now: datetime,
    *,
    linked_at: datetime | None = None,
) -> None:
    try:
        store.record_state(country, state, reason, now=now, expect_linked_at=linked_at)
    except DbError:
        logger.error("Dodo IS %s: состояние %s не записалось", country, state, exc_info=False)


def _fill_account(login: Login, access: str) -> None:
    """Перенесённый вход пришёл без имени и почты: спросить учётку у Dodo IS и дописать.

    Сбой не ломает проверку: плитка остаётся «учётка неизвестна», значения в журнал не идут.
    """
    if login.account_name or login.account_email:
        return
    try:
        name, email = client.userinfo(login.contour, access)
        store.set_account(login.country, name, email, expect_linked_at=login.linked_at)
    except DbError:
        logger.warning("Dodo IS %s: учётка входа не записалась", login.country, exc_info=False)


def check(country: str, *, now: datetime | None = None) -> Login | None:
    """Проверить вход: сколько пиццерий открыто. Записывает исход и возвращает вход."""
    moment = now or datetime.now(UTC)
    login = store.get_login(country)
    if login is None:
        return None
    if login.state == rules.EXPIRED:
        # Ключ продления уже отвергнут: ходить с мёртвым ключом доступа незачем.
        return login
    try:
        tokens = store.read_tokens(country)
    except DbError:
        logger.warning("Dodo IS %s: ключи входа не прочитались", country, exc_info=False)
        _note(country, rules.FAILED, "no_tokens", moment, linked_at=login.linked_at)
        return store.get_login(country)
    if tokens is None:
        _note(country, rules.FAILED, "no_tokens", moment, linked_at=login.linked_at)
        return store.get_login(country)
    try:
        units = client.working_pizzerias(country)
        opened = client.count_open(country, login.contour, tokens.access, units, moment.date())
    except DodoisError as exc:
        _note(country, rules.FAILED, exc.kind, moment, linked_at=login.linked_at)
        return store.get_login(country)
    _fill_account(login, tokens.access)
    state, reason = rules.counts_state(len(units), opened)
    try:
        store.record_state(
            country,
            state,
            reason,
            now=moment,
            units_total=len(units),
            units_open=opened,
            expect_linked_at=login.linked_at,
        )
    except DbError:
        logger.error("Dodo IS %s: итог проверки не записался", country)
    return store.get_login(country)


def _write_pair(
    login: Login, pair: TokenPair, moment: datetime, sleep: Callable[[float], None]
) -> bool:
    for attempt in range(WRITE_TRIES):
        try:
            store.replace_tokens(
                country=login.country,
                tokens=store.Tokens(pair.access, pair.refresh),
                access_expires_at=_expires_at(pair, moment),
                scope=pair.scope,
                now=moment,
                expect_linked_at=login.linked_at,
            )
        except store.LoginSuperseded:
            logger.info("Dodo IS %s: вход заменён за время продления", login.country)
            raise
        except DbError:
            logger.error(
                "Dodo IS %s: новая пара ключей не легла (попытка %d из %d)",
                login.country,
                attempt + 1,
                WRITE_TRIES,
            )
            if attempt + 1 < WRITE_TRIES:
                sleep(WRITE_RETRY_SECONDS)
        else:
            return True
    return False


def _source_hash(refresh_token: str) -> str:
    return hashlib.sha256(refresh_token.encode()).hexdigest()


def _pending(journal: outbox.Journal, country: str) -> outbox.Pending | None:
    """Disk wins over another process's stale cache; cache only fills its own marker."""
    saved = journal.read()
    cached = _unwritten.get(country)
    if (
        saved is not None
        and saved.pair is None
        and cached is not None
        and (
            cached.linked_at == saved.linked_at
            and cached.contour == saved.contour
            and cached.source_hash == saved.source_hash
            and cached.moment == saved.moment
        )
    ):
        return cached
    _unwritten.pop(country, None)
    return saved


def _retry_locked(
    login: Login,
    journal: outbox.Journal,
    held: outbox.Pending,
    now: datetime,
    sleep: Callable[[float], None],
) -> bool:
    if held.linked_at != login.linked_at or held.contour != login.contour:
        journal.clear()
        _unwritten.pop(login.country, None)
        return True
    if held.pair is None:
        # A request may have rotated the token before its response was lost.
        # Never send that token again merely because this process restarted.
        logger.error(
            "Dodo IS %s: исход продления неизвестен; прежний refresh не повторяется", login.country
        )
        _note(login.country, rules.FAILED, "network", now, linked_at=held.linked_at)
        return False
    journal.write(held)
    held_login = replace(login, linked_at=held.linked_at)
    try:
        written = _write_pair(held_login, held.pair, held.moment, sleep)
    except store.LoginSuperseded:
        journal.clear()
        _unwritten.pop(login.country, None)
        return True
    if written:
        journal.clear()
        _unwritten.pop(login.country, None)
        _note(login.country, rules.OK, None, now, linked_at=held.linked_at)
        return True
    _note(login.country, rules.FAILED, "write_failed", now, linked_at=held.linked_at)
    return False


def refresh(
    login: Login,
    creds: Credentials,
    *,
    now: datetime | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Rotate under the country lock; commit the encrypted pair before DB retries."""
    moment = now or datetime.now(UTC)
    try:
        with outbox.locked(login.country) as journal:
            journal.preflight()
            current = store.get_login(login.country)
            if current is None or current.linked_at != login.linked_at:
                return True
            held = _pending(journal, login.country)
            if held is not None:
                return _retry_locked(current, journal, held, moment, sleep)
            if current.refreshed_at != login.refreshed_at:
                return True
            tokens = store.read_tokens(login.country)
            if tokens is None:
                _note(login.country, rules.FAILED, "no_tokens", moment, linked_at=login.linked_at)
                return False
            held = outbox.Pending(
                login.country, login.contour, login.linked_at, moment, _source_hash(tokens.refresh)
            )
            journal.write(held)
            try:
                pair = client.refresh_tokens(creds, login.contour, tokens.refresh)
            except RefreshRejected:
                journal.clear()
                _note(
                    login.country,
                    rules.EXPIRED,
                    "refresh_rejected",
                    moment,
                    linked_at=login.linked_at,
                )
                return False
            except DodoisError as exc:
                _note(login.country, rules.FAILED, exc.kind, moment, linked_at=login.linked_at)
                return False
            held = replace(held, pair=pair)
            _unwritten[login.country] = held  # emergency retry if FS fails after provider replied
            journal.write(held)
            return _retry_locked(current, journal, held, moment, sleep)
    except outbox.OutboxError:
        logger.error(
            "Dodo IS %s: очередь продления недоступна; запрос не повторяется", login.country
        )
        _note(login.country, rules.FAILED, "write_failed", moment, linked_at=login.linked_at)
        return False
    except DbError:
        _note(login.country, rules.FAILED, "no_tokens", moment, linked_at=login.linked_at)
        return False


def retry_unwritten(
    login: Login,
    *,
    now: datetime | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> bool | None:
    """Recover durable pairs before any new refresh, including after a restart."""
    moment = now or datetime.now(UTC)
    try:
        with outbox.locked(login.country) as journal:
            held = _pending(journal, login.country)
            if held is None:
                return None
            current = store.get_login(login.country)
            if current is None:
                journal.clear()
                _unwritten.pop(login.country, None)
                return True
            return _retry_locked(current, journal, held, moment, sleep)
    except (outbox.OutboxError, DbError):
        logger.error(
            "Dodo IS %s: отложенная пара не восстановлена; запрос не повторяется", login.country
        )
        _note(login.country, rules.FAILED, "write_failed", moment, linked_at=login.linked_at)
        return False


def forget_unwritten() -> None:
    """Сбросить только аварийный RAM-кеш; устойчивую очередь не трогать."""
    _unwritten.clear()


def run_pass(
    *,
    now: datetime | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Один заход бота: продлить то, что пора (ночью), затем проверить каждый вход."""
    moment = now or datetime.now(UTC)
    logins = store.list_logins()
    creds: Credentials | None = None
    for login in logins:
        retried = retry_unwritten(login, now=moment, sleep=sleep)
        if retried is False:
            continue  # пара ещё не легла: к Dodo IS за новой не ходим, ключ продления мёртв
        if (
            retried is None
            and login.state != rules.EXPIRED
            and rules.refresh_due(login.refreshed_at, login.access_expires_at, moment)
        ):
            creds = creds or credentials()
            if creds is None:
                _note(login.country, rules.FAILED, "no_keys", moment, linked_at=login.linked_at)
                continue
            if not refresh(login, creds, now=moment, sleep=sleep):
                continue
        if login.state == rules.EXPIRED:
            continue
        try:
            check(login.country, now=moment)
        except Exception:
            logger.exception("Dodo IS %s: проверка упала", login.country)
