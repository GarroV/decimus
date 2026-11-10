"""Состояние подключений Dodo IS по странам через Claude: `dodois_status` (только чтение).

**Те же функции, что у вкладки «Dodo IS».** Входы и ссылки — `db.dodois_logins`
(`list_logins`, `list_invites`), загрузка данных — `db.dodois_metrics`; своего SQL по входам
здесь нет. Право — действие матрицы `keys.manage` (`policy.TOOL_ACTIONS`): вкладку видит один
главный админ УК, и ровно он видит инструмент.

**Секретов в ответе нет по построению**: поля собираются поимённо, а не копией записи.
Нет ключей входа, токенов и хэшей ссылок, почты учётки Dodo IS; из ссылки — только даты,
статус и логин выдавшего. Текст ошибки загрузки — вид отказа без значений ответа (0105).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta

from ..db import dodois_logins, dodois_metrics
from ..db.errors import ConfigError as DbConfigError
from ..db.errors import DbError
from ..domain import dodois as rules
from .db_target import config_refusal
from .errors import ToolError

NOT_CONNECTED = (
    "Dodo IS на этом стенде не подключён: не задана переменная окружения DATABASE_URL. "
    "Это отказ чтения, а не отсутствие подключений"
)
READ_FAILED = (
    "Подключения Dodo IS не прочитались: база отказала. Это отказ чтения, а не их отсутствие"
)
BAD_COUNTRY = "Код страны — две заглавные латинские буквы, например RS"

#: За сколько дней показываем ссылки-приглашения.
INVITES_DAYS = 7
#: Сколько последних ссылок читаем, чтобы выбрать из них недельные.
INVITES_READ = 300


@contextmanager
def _dodois() -> Iterator[None]:
    try:
        yield
    except DbConfigError as exc:
        raise config_refusal(exc, NOT_CONNECTED) from None
    except DbError as exc:
        raise ToolError(READ_FAILED) from exc


def _iso(moment: datetime | None) -> str | None:
    return None if moment is None else moment.isoformat()


def _login(login: rules.Login) -> dict[str, object]:
    return {
        "connected": True,
        "linked_at": _iso(login.linked_at),
        "source": login.source,
        "state": login.state,
        "reason": login.reason,
        "checked_at": _iso(login.checked_at),
        "refreshed_at": _iso(login.refreshed_at),
        "access_expires_at": _iso(login.access_expires_at),
        "units_total": login.units_total,
        "units_open": login.units_open,
        "account_name": login.account_name,
    }


def _invite(invite: rules.Invite, now: datetime) -> dict[str, object]:
    return {
        "status": invite.status(now),
        "issued_at": _iso(invite.issued_at),
        "expires_at": _iso(invite.expires_at),
        "used_at": _iso(invite.used_at),
        "revoked_at": _iso(invite.revoked_at),
        "issued_by": invite.issued_by,
    }


def _loads(country: str, loads: list[dodois_metrics.KindLoad]) -> list[dict[str, object]]:
    return [
        {
            "kind": item.kind,
            "last_ok_at": _iso(item.ok_at),
            "last_ok_rows": item.ok_rows,
            "last_attempt_at": _iso(item.attempt_at),
            "last_attempt_ok": item.attempt_ok,
            "last_attempt_error": None if item.attempt_ok else item.attempt_error,
        }
        for item in loads
        if item.country == country
    ]


def _data(data: dodois_metrics.CountryData | None, month: date) -> dict[str, object]:
    return {
        "month": month.isoformat(),
        "units_with_data": data.units_with_data if data else 0,
        "latest_month_with_data": _iso_date(data.latest_month) if data else None,
    }


def _iso_date(day: date | None) -> str | None:
    return None if day is None else day.isoformat()


def dodois_status(*, tenant: str, country: str | None = None) -> dict[str, object]:
    """Подключения Dodo IS: по стране — вход, ссылки за неделю и загрузка данных."""
    del tenant  # право решено до вызова матрицей (`keys.manage`); охвата по пространству нет
    code = None if country is None else country.strip().upper()
    if code is not None and not rules.is_country(code):
        raise ToolError(BAD_COUNTRY)
    now = datetime.now(UTC)
    month = date(now.year, now.month, 1)
    with _dodois():
        logins = {item.country: item for item in dodois_logins.list_logins()}
        invites = dodois_logins.list_invites(INVITES_READ)
        loads = dodois_metrics.kind_loads()
        data = {item.country: item for item in dodois_metrics.country_data(month)}
    since = now - timedelta(days=INVITES_DAYS)
    codes = sorted(
        {
            *logins,
            *(i.country for i in invites if i.issued_at >= since),
            *(x.country for x in loads),
        }
    )
    if code is not None:
        codes = [code]
    rows = []
    for c in codes:
        login = logins.get(c)
        rows.append(
            {
                "country": c,
                **(_login(login) if login else {"connected": False}),
                "invites_last_7_days": [
                    _invite(i, now) for i in invites if i.country == c and i.issued_at >= since
                ],
                "data_loads": _loads(c, loads),
                "data": _data(data.get(c), month),
            }
        )
    return {
        "status": "ok",
        "countries": rows,
        "note": (
            "Только страны со входом, ссылкой за неделю или загрузкой данных; нужную страну "
            "можно спросить кодом. data_loads — журнал часовой загрузки метрик по видам "
            "(sales, aggregators, kr, ratings); units_with_data — пиццерии страны со строками "
            "за текущий месяц"
        ),
    }
