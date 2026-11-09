"""Событие срока отчёта в календаре проверяющего: свести календарь с проверками (D740, #1590).

**Один проход сводит, а не реагирует.** Задача бота (`src/bot/calendar_loader.py`) раз в
несколько минут сравнивает проверки УК с тем, что записано в `calendar_events`:

* проверки нет в календаре → событие создаётся;
* дата проверки или пиццерия сменились (`move_inspection`, исправление в вебе) → событие
  сдвигается или переименовывается;
* проверка снята (отклонена) — роль приложения её больше не видит — → событие удаляется.

Так сбой Google не ломает завершение проверки (оно к календарю не обращается вовсе), перенос
и снятие подхватываются с любого входа (веб, MCP, бот) без правки каждого, а упавший вызов
повторяется на следующем проходе.

**Сбой не молчит и не бесконечен.** Код причины пишется в лог процесса и в журнал действий.
Мёртвый доступ (`invalid_grant` — человек отозвал его у Google, и т. п.) помечается на
подключении: человеку на экране «Настроек» видно «календарь отключён или не ответил —
переподключите», а задача его пропускает до переподключения. Временный сбой (сеть, 5xx) только
записывается и повторяется. Людям — ни в боте, ни в почте — ничего не отправляется.
"""

from __future__ import annotations

import logging
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from src.db import calendar_store, secret_crypto
from src.db.errors import DbError
from src.domain.report_deadline import event_title, report_due_date

from .client import (
    DEAD_GRANT_CODES,
    GONE_CODES,
    CalendarError,
    ClientKeys,
    Opener,
    access_token,
    create_event,
    delete_event,
    event_body,
    keys_from_env,
    update_event,
)

logger = logging.getLogger(__name__)

#: Сверх мёртвых кодов Google: ключ из базы не открылся (сменили `SECRETS_KEY`) — переподключение.
UNREADABLE = "secret_unreadable"
DEAD_CODES = tuple(sorted(DEAD_GRANT_CODES | {UNREADABLE}))

#: События, у которых срок прошёл больше суток назад, не заводятся: напоминать поздно.
STALE_DAYS = 1
#: Сколько вызовов Google за проход: остальное — следующим. Один проход не должен висеть часами.
MAX_CALLS_PER_PASS = 60


@dataclass
class PassResult:
    created: int = 0
    updated: int = 0
    deleted: int = 0
    failed: int = 0
    skipped_users: list[str] = field(default_factory=list)


LinkFor = Callable[[str], str | None]


class _Tokens:
    """Короткие ключи доступа на проход: по одному на человека, сбой запоминается."""

    def __init__(self, keys: ClientKeys, opener: Opener) -> None:
        self._keys, self._opener = keys, opener
        self._tokens: dict[str, str | None] = {}
        self._dead: set[str] = set()

    def get(self, user_id: str) -> str | None:
        if user_id not in self._tokens:
            self._tokens[user_id] = self._fetch(user_id)
        return self._tokens[user_id]

    def is_dead(self, user_id: str) -> bool:
        """Доступ человека мёртв насовсем (отозван, ключ не открылся); временный сбой — нет."""
        return user_id in self._dead

    def _fetch(self, user_id: str) -> str | None:
        try:
            refresh = calendar_store.refresh_token_of(user_id)
        except secret_crypto.SecretCryptoError:
            logger.warning("календарь: ключ человека %s не открылся", _short(user_id))
            self._dead.add(user_id)
            _fail(user_id, UNREADABLE, mark=True)
            return None
        if refresh is None:
            return None
        try:
            return access_token(self._keys, refresh, opener=self._opener)
        except CalendarError as сбой:
            if сбой.code in DEAD_GRANT_CODES:
                self._dead.add(user_id)
            _fail(user_id, сбой.code, mark=True)
            return None


def _short(user_id: str) -> str:
    return user_id[:8]


def _fail(user_id: str, code: str, *, inspection_id: str | None = None, mark: bool) -> None:
    """Сбой: лог, журнал и пометка на подключении (экран скажет «переподключите»)."""
    logger.warning("календарь: сбой у %s — %s", _short(user_id), code)
    calendar_store.journal_problem(user_id, code, inspection_id=inspection_id)
    if mark:
        try:
            calendar_store.mark_problem(user_id, code)
        except DbError:
            logger.warning("календарь: пометка сбоя не записана", exc_info=True)


def _description(link: str | None, lang: str) -> str:
    if link is None:
        return ""
    return ("Проверка в Decimus: " if lang == "ru" else "Inspection in Decimus: ") + link


def run_pass(
    *,
    today: date,
    keys: ClientKeys | None = None,
    link_for: LinkFor = lambda _id: None,
    opener: Opener = urllib.request.urlopen,
) -> PassResult:
    """Один проход. Без клиента Google в окружении — пропуск (законная настройка стенда)."""
    результат = PassResult()
    ключи = keys or keys_from_env()
    if ключи is None:
        logger.info("календарь: нет GOOGLE_CLIENT_ID/SECRET — проход пропущен")
        return результат
    токены = _Tokens(ключи, opener)
    вызовов = 0

    for сирота in calendar_store.orphans():
        if вызовов >= MAX_CALLS_PER_PASS:
            return результат
        токен = токены.get(сирота.user_id)
        if токен is None:
            if токены.is_dead(сирота.user_id):
                # Доступ мёртв насовсем: событие снять нечем, его уберёт сам человек.
                calendar_store.forget_event(сирота.inspection_id)
            # Временный сбой (сеть, 5xx): запись остаётся до следующего прохода.
            continue
        вызовов += 1
        try:
            delete_event(токен, сирота.event_id, opener=opener)
        except CalendarError as сбой:
            результат.failed += 1
            _fail(сирота.user_id, сбой.code, inspection_id=сирота.inspection_id, mark=False)
            continue
        calendar_store.forget_event(сирота.inspection_id)
        результат.deleted += 1

    порог = today - timedelta(days=calendar_store.WORK_WINDOW_DAYS)
    for кандидат in calendar_store.candidates(since=порог, dead=DEAD_CODES):
        срок = report_due_date(кандидат.inspection_date)
        название = event_title(кандидат.unit, кандидат.inspection_date, кандидат.ui_lang)
        if кандидат.event_id and кандидат.event_due == срок and кандидат.event_title == название:
            continue
        if not кандидат.event_id and срок < today - timedelta(days=STALE_DAYS):
            continue
        if вызовов >= MAX_CALLS_PER_PASS:
            break
        токен = токены.get(кандидат.user_id)
        if токен is None:
            if кандидат.user_id not in результат.skipped_users:
                результат.skipped_users.append(кандидат.user_id)
            continue
        вызовов += 1
        тело = event_body(
            title=название,
            description=_description(link_for(кандидат.inspection_id), кандидат.ui_lang),
            due=срок,
        )
        try:
            номер, создано = _push(токен, кандидат.event_id, тело, opener)
        except CalendarError as сбой:
            результат.failed += 1
            _fail(кандидат.user_id, сбой.code, inspection_id=кандидат.inspection_id, mark=True)
            continue
        calendar_store.remember_event(
            кандидат.inspection_id, кандидат.user_id, event_id=номер, due=срок, title=название
        )
        calendar_store.clear_problem(кандидат.user_id)
        if создано:
            результат.created += 1
        else:
            результат.updated += 1
    return результат


def _push(
    token: str, event_id: str | None, body: dict[str, Any], opener: Opener
) -> tuple[str, bool]:
    """Создать событие или сдвинуть имеющееся. Пропавшее из календаря пересоздаётся."""
    if event_id:
        try:
            update_event(token, event_id, body, opener=opener)
            return event_id, False
        except CalendarError as сбой:
            if сбой.code not in GONE_CODES:
                raise
    return create_event(token, body, opener=opener), True
