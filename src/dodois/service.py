"""Входы в Dodo IS по странам: записать вход, продлить, проверить «открыто X из Y» (D640).

Здесь порядок, а не сеть и не SQL: сеть — `client`, база — `src/db/dodois_logins.py`,
правила и состояния — `src/domain/dodois.py`.

**Продление не теряет вход.** Ключ продления у Dodo IS одноразовый: после удачного ответа
прежний мёртв. Поэтому новая пара пишется атомарно (`replace_tokens`) и, если запись не
легла, пробуется ещё несколько раз с той же парой в памяти; не легла совсем — состояние
«запись не легла, повторяем» (`write_failed`) и строка в журнале процесса без значений.
Незаписанная пара живёт в памяти процесса бота (`_unwritten`), и каждый следующий заход
(раз в час) сначала повторяет запись, а к Dodo IS за новой парой не ходит: ключ продления
в базе уже мёртв, ещё одно продление дало бы «вход истёк». Перезапуск бота эту пару теряет.
Отказ Dodo IS в продлении — «вход истёк»: прежняя пара остаётся в базе, ничего не стирается.

**Тревог наружу нет**: состояние видно на экране «Подключения»; письмо или сообщение людям —
только по «да» владельца (D640, правило о коммуникации).
"""

from __future__ import annotations

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
from .client import Credentials, DodoisError, RefreshRejected, TokenPair

logger = logging.getLogger(__name__)

#: Сколько раз пробуем записать новую пару ключей, прежде чем признать сбой, и пауза между ними.
WRITE_TRIES = 4
WRITE_RETRY_SECONDS = 2.0

#: Пары, которые Dodo IS уже выдал, а записать не удалось: страна → (пара, когда, `linked_at`
#: входа, которому она принадлежит). Только память процесса, значения наружу не печатаются.
_unwritten: dict[str, tuple[TokenPair, datetime, datetime]] = {}


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
    contour: str = rules.INTL,
    account: tuple[str | None, str | None] | None = None,
    access_expires_at: datetime | None = None,
    verify: bool = True,
) -> Login:
    """Записать вход страны. Имя и почту учётки Dodo IS берём у `userinfo`, если не заданы.

    `access_expires_at` — когда истекает ключ доступа, если это не «сейчас + срок из ответа»
    (перенесённый вход); `verify=False` — не проверять «открыто X из Y» сразу.
    """
    moment = now or datetime.now(UTC)
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


def _note(country: str, state: str, reason: str | None, now: datetime) -> None:
    try:
        store.record_state(country, state, reason, now=now)
    except DbError:
        logger.error("Dodo IS %s: состояние %s не записалось", country, state, exc_info=False)


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
        _note(country, rules.FAILED, "no_tokens", moment)
        return store.get_login(country)
    if tokens is None:
        _note(country, rules.FAILED, "no_tokens", moment)
        return store.get_login(country)
    try:
        units = client.working_pizzerias(country)
        opened = client.count_open(country, login.contour, tokens.access, units, moment.date())
    except DodoisError as exc:
        _note(country, rules.FAILED, exc.kind, moment)
        return store.get_login(country)
    state, reason = rules.counts_state(len(units), opened)
    try:
        store.record_state(
            country, state, reason, now=moment, units_total=len(units), units_open=opened
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
            return True
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


def refresh(
    login: Login,
    creds: Credentials,
    *,
    now: datetime | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Продлить вход. `True` — новая пара записана. Исход ошибки уходит в состояние входа."""
    moment = now or datetime.now(UTC)
    try:
        tokens = store.read_tokens(login.country)
    except DbError:
        _note(login.country, rules.FAILED, "no_tokens", moment)
        return False
    if tokens is None:
        _note(login.country, rules.FAILED, "no_tokens", moment)
        return False
    try:
        pair = client.refresh_tokens(creds, login.contour, tokens.refresh)
    except RefreshRejected:
        _note(login.country, rules.EXPIRED, "refresh_rejected", moment)
        return False
    except DodoisError as exc:
        _note(login.country, rules.FAILED, exc.kind, moment)
        return False
    if _write_pair(login, pair, moment, sleep):
        return True
    _unwritten[login.country] = (pair, moment, login.linked_at)
    _note(login.country, rules.FAILED, "write_failed", moment)
    return False


def retry_unwritten(
    login: Login,
    *,
    now: datetime | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> bool | None:
    """Повторить запись пары, которую Dodo IS выдал, а база не приняла.

    `None` — незаписанной пары нет; `True` — легла (или вход заменён — пара не нужна);
    `False` — не легла, пара остаётся в памяти, состояние «запись не легла, повторяем».
    """
    held = _unwritten.get(login.country)
    if held is None:
        return None
    pair, moment, linked_at = held
    held_login = replace(login, linked_at=linked_at)
    if _write_pair(held_login, pair, moment, sleep):
        del _unwritten[login.country]
        _note(login.country, rules.OK, None, now or datetime.now(UTC))
        return True
    _note(login.country, rules.FAILED, "write_failed", now or datetime.now(UTC))
    return False


def forget_unwritten() -> None:
    """Забыть незаписанные пары — для тестов."""
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
                _note(login.country, rules.FAILED, "no_keys", moment)
                continue
            if not refresh(login, creds, now=moment, sleep=sleep):
                continue
        if login.state == rules.EXPIRED:
            continue
        try:
            check(login.country, now=moment)
        except Exception:
            logger.exception("Dodo IS %s: проверка упала", login.country)
