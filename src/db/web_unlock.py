"""Снятие запрета на вход: дверь роли администратора истории (T328, D158).

Соседний `web_throttle` — дверь роли ПРИЛОЖЕНИЯ: он считает неудачи и решает,
пускать ли попытку к сверке пароля. Здесь — дверь ЧЕЛОВЕКА ИЗ КОМАНДЫ: она
только смотрит на счётчик и снимает запрет. Две двери потому, что роли разные
(`DATABASE_RETRACTION_URL` против `DATABASE_URL`), а одна дверь на две роли
означала бы, что подключение выбирается по параметру — и однажды выберется не
то.

**ЗАЧЕМ СНЯТИЕ ВООБЩЕ НУЖНО.** Запрет проходит по времени, но ждать приходится
и тому, кого заперли чужим упорством: посторонний, знающий логин
администратора, держит его запертым сколь угодно долго — по неудачной попытке
раз в час, и пароль для этого не нужен вовсе. До T328 ответить на это было
нечем: команда снятия отсутствовала, и живой продукт оставался без способа
вернуть человеку доступ.

**СНЯТЬ ЗАПРЕТ = ЗАБЫТЬ НЕУДАЧИ.** Срок запрета в базе не хранится, он
считается по числу неудач и времени последней (`web_throttle.verdict_of`).
Поэтому снятие — это удаление строки счётчика, а не пометка «разрешено»:
пометка была бы вторым местом, где записан тот же факт.

**ЛОГИНЫ УЗНАЮТСЯ, А НЕ РАСШИФРОВЫВАЮТСЯ.** В счётчике лежат отпечатки. Чтобы
показать человеку, кто заперт, инструмент считает отпечаток каждой заведённой
учётки и сопоставляет. Чужой отпечаток (логин, которого у нас нет, или адрес)
так и остаётся нерасшифрованным — и это правильно: показывать адрес
перебирающего незачем, а узнать его по отпечатку всё равно можно перебором за
секунды.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import psycopg

from .config import load_retraction_settings
from .errors import AccessError
from .web_throttle import (
    SCOPE_ADDRESS,
    SCOPE_LOGIN,
    Counter,
    Verdict,
    canonical_address,
    key_fingerprint,
    verdict_of,
)

_COUNTERS_SQL = """
    select scope, key_fingerprint, failures, updated_at
      from web_login_attempts
     where tenant_code = %s
     order by updated_at desc
"""

_LOGINS_SQL = "select login from web_users where tenant_code = %s and disabled_at is null"

_FORGET_SQL = """
    delete from web_login_attempts
     where tenant_code = %s and scope = %s and key_fingerprint = %s
"""


@dataclass(frozen=True)
class Key:
    """Строка счётчика глазами человека из команды.

    `login` заполнен, если отпечаток узнан среди заведённых учёток; иначе
    `None` — и это либо адрес, либо логин, которого у нас нет вовсе.
    """

    scope: str
    fingerprint: str
    counter: Counter
    verdict: Verdict
    login: str | None

    @property
    def locked(self) -> bool:
        return self.verdict.locked


@contextmanager
def _connected(зачем: str) -> Iterator[psycopg.Connection[Any]]:
    """Подключение АДМИНИСТРАТОРА ИСТОРИИ. Отказ базы — `AccessError`, а не тишина.

    Наружу уходит тип исключения драйвера, а не его текст: в тексте psycopg
    может оказаться строка подключения целиком. Тот же приём и та же причина,
    что у `web_throttle._connected` и `retract`.
    """
    settings = load_retraction_settings()
    try:
        with psycopg.connect(settings.dsn) as conn:
            yield conn
    except psycopg.Error as exc:
        raise AccessError(f"Не удалось {зачем} ({type(exc).__name__})") from exc


def counters(*, tenant: str) -> list[Key]:
    """Все счётчики арендатора — и запертые, и просто накопившие неудачи.

    Не только запертые намеренно: человеку, разбирающему жалобу «не пускает»,
    важно увидеть и счётчик, которому до запрета одна попытка. Отбор запертых
    делается по `locked` у вызывающего, а не запросом: срок запрета в базе не
    лежит, его считает `verdict_of`.
    """
    with _connected("прочитать счётчики попыток") as conn, conn.cursor() as cur:
        cur.execute(_COUNTERS_SQL, (tenant,))
        строки = cur.fetchall()
        cur.execute(_LOGINS_SQL, (tenant,))
        логины = [str(строка[0]) for строка in cur.fetchall()]
    по_отпечатку = {key_fingerprint(логин): логин for логин in логины}
    ключи = []
    for scope, отпечаток, failures, updated_at in строки:
        счётчик = Counter(failures=int(failures), updated_at=updated_at)
        ключи.append(
            Key(
                scope=str(scope),
                fingerprint=str(отпечаток),
                counter=счётчик,
                verdict=verdict_of(счётчик, scope=str(scope)),
                login=по_отпечатку.get(str(отпечаток)) if scope == SCOPE_LOGIN else None,
            )
        )
    return ключи


def _forget(*, tenant: str, scope: str, fingerprint: str) -> bool:
    with _connected("снять запрет на вход") as conn, conn.cursor() as cur:
        cur.execute(_FORGET_SQL, (tenant, scope, fingerprint))
        удалено = cur.rowcount
    return удалено > 0


def unlock_login(*, tenant: str, login: str) -> bool:
    """Снять запрет с логина. `False` — неудач за ним не числилось.

    Отличать «снял запрет» от «снимать было нечего» обязательно: иначе команда
    отвечает успехом человеку, который ошибся арендатором или логином, и тот
    уходит ждать неснятого запрета.
    """
    return _forget(tenant=tenant, scope=SCOPE_LOGIN, fingerprint=key_fingerprint(login))


def unlock_address(*, tenant: str, address: str) -> bool:
    """Снять запрет с адреса. Адрес приводится к канону тем же способом, что при счёте."""
    return _forget(
        tenant=tenant,
        scope=SCOPE_ADDRESS,
        fingerprint=key_fingerprint(canonical_address(address)),
    )
