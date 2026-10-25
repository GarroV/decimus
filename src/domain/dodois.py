"""Входы в Dodo IS по странам (D640, #951): правила без базы и сети.

Данные Dodo IS по странам берутся через вход учёткой каждой страны (OAuth2, device flow).
Здесь — чистые данные и решения: адреса контуров, права входа, состояние входа, когда пора
продлевать и как состояние превращается в цвет строки на «Подключениях». Хождение по сети —
`src/dodois/`, база — `src/db/dodois_logins.py`.

**Значений ключей здесь нет** и быть не может: вход описан только фактами (кто привязал,
когда, сколько пиццерий открыто, в каком состоянии).
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

from .health import GREEN, RED, YELLOW, Status

#: Право, под которым проверяется пара ключей приложения (ничего не подтверждается).
PROBE_SCOPE = "shared"
#: Права входа: профиль для имени и почты учётки, продажи, стопы, доставка, продление.
SCOPES = (
    "openid profile email shared sales stopsales deliverystatistics "
    "productionefficiency offline_access"
)

#: Код страны, как в `ratings.countries`.
_COUNTRY = re.compile(r"[A-Z]{2}")

INTL = "intl"
#: Контур СНГ (`.io`) пока не делаем, но поле в записи есть.
CIS = "cis"
CONTOURS = (INTL, CIS)


@dataclass(frozen=True)
class ContourHosts:
    auth: str
    api: str


#: Хосты по контурам. СНГ не заведён намеренно: вход такого контура клиент отклонит.
HOSTS: Mapping[str, ContourHosts] = {
    INTL: ContourHosts("https://auth.dodois.com", "https://api.dodois.com"),
}
#: Список работающих пиццерий страны — без ключа.
UNITINFO_URL = "https://publicapi.dodois.io/{cc}/api/v1/unitinfo/all"
USERINFO_PATH = "/connect/userinfo"
STOPSALES_PATH = "/dodopizza/{cc}/production/stop-sales-channels"
#: Сколько пиццерий в одном запросе стопов.
UNITS_PER_CALL = 30

OK = "ok"
PARTIAL = "partial"
EXPIRED = "expired"
FAILED = "failed"
STATES = (OK, PARTIAL, EXPIRED, FAILED)

#: Причины (код в базе → текст `dodois.reason.<код>`); закрытый список.
REASONS = (
    "refresh_rejected",
    "network",
    "rate_limited",
    "unauthorized",
    "no_units",
    "write_failed",
    "no_keys",
    "no_tokens",
)

#: Как часто бот проверяет «открыто X из Y».
CHECK_EVERY = timedelta(hours=1)
#: Ночное окно продления (часы UTC, включая начало и не включая конец).
NIGHT_FROM, NIGHT_TO = 1, 6
#: Продлевать не чаще: ключ доступа живёт сутки, а в окно ночь заходит раз в сутки.
REFRESH_AFTER = timedelta(hours=20)
#: Проверка, которой нет дольше трёх сроков, не может оставаться зелёной.
STALE_AFTER = 3 * CHECK_EVERY


def is_country(code: str) -> bool:
    return _COUNTRY.fullmatch(code) is not None


def vault_names(country: str) -> tuple[str, str]:
    """Имена записей ключей входа в `vault.secrets`: (доступ, продление). Страна — из реестра."""
    if not is_country(country):
        raise ValueError("Код страны не из двух заглавных латинских букв")
    low = country.lower()
    return f"dodois.access.{low}", f"dodois.refresh.{low}"


@dataclass(frozen=True)
class Login:
    """Вход страны без ключей: то, что видно на экране и в проверке."""

    country: str
    contour: str
    source: str
    issued_by: str
    account_name: str | None
    account_email: str | None
    linked_at: datetime
    scope: str
    units_total: int | None
    units_open: int | None
    refreshed_at: datetime | None
    access_expires_at: datetime | None
    checked_at: datetime | None
    state: str
    reason: str | None


def counts_state(total: int, open_: int) -> tuple[str, str | None]:
    """Состояние по счёту: все открыты — работает; не все — «открыто не всё»; пусто — сбой."""
    if total <= 0:
        return FAILED, "no_units"
    if open_ < total:
        return PARTIAL, None
    return OK, None


def refresh_due(
    refreshed_at: datetime | None, access_expires_at: datetime | None, now: datetime
) -> bool:
    """Пора ли продлевать вход: ночью раз в сутки, а истёкший ключ доступа — в любой час."""
    if access_expires_at is not None and now >= access_expires_at:
        return True
    if refreshed_at is not None and now - refreshed_at < REFRESH_AFTER:
        return False
    return NIGHT_FROM <= now.hour < NIGHT_TO or refreshed_at is None


def status_of(login: Login, now: datetime) -> Status:
    """Цвет и причина строки страны. Причины — ключи текстов `health.reason.*`."""
    if login.state == EXPIRED:
        return Status(RED, "health.reason.dodois_expired", login.checked_at)
    if login.checked_at is None or now - login.checked_at > STALE_AFTER:
        return Status(YELLOW, "health.reason.stale", login.checked_at)
    if login.state == FAILED:
        return Status(YELLOW, "health.reason.dodois_failed", login.checked_at)
    if login.state == PARTIAL:
        params = {"open": login.units_open or 0, "total": login.units_total or 0}
        return Status(YELLOW, "health.reason.dodois_partial", login.checked_at, params)
    params = {"open": login.units_open or 0, "total": login.units_total or 0}
    return Status(GREEN, "health.reason.dodois_ok", login.checked_at, params)


# --- Приглашения: одноразовая ссылка на вход страны -----------------------------------

#: Откуда вход: по ссылке или перенесён инструментом.
SOURCE_INVITE = "invite"
SOURCE_IMPORT = "import"

#: Сколько живёт ссылка.
INVITE_TTL = timedelta(hours=24)
#: Токен ссылки — 32 случайных байта (`secrets.token_urlsafe`): 43 знака base64url.
TOKEN_BYTES = 32
_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")

INVITE_ACTIVE = "active"
INVITE_USED = "used"
INVITE_EXPIRED = "expired"
INVITE_REVOKED = "revoked"


def new_token() -> str:
    """Новый токен ссылки: случайный, одноразовый; в базу уходит только `hash_token`."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def token_shape_ok(token: str) -> bool:
    """Форма токена: чужую строку в базу за хэшем не носим."""
    return _TOKEN.fullmatch(token) is not None


def hash_token(token: str) -> str:
    """SHA-256 токена в hex — то, что лежит в базе."""
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def hashes_equal(left: str, right: str) -> bool:
    """Сверка хэшей за постоянное время."""
    return hmac.compare_digest(left.encode("ascii"), right.encode("ascii"))


@dataclass(frozen=True)
class Invite:
    """Приглашение без токена: страна, кто и когда выдал, чем кончилось."""

    id: int
    country: str
    issued_by: str
    issued_at: datetime
    expires_at: datetime
    used_at: datetime | None
    revoked_at: datetime | None
    token_hash: str = ""
    issued_by_id: str = ""
    issued_by_role: str = ""
    issued_by_tenant: str = ""

    def status(self, now: datetime) -> str:
        """Погашена и отозвана — раньше срока: след важнее часов."""
        if self.used_at is not None:
            return INVITE_USED
        if self.revoked_at is not None:
            return INVITE_REVOKED
        return INVITE_EXPIRED if now >= self.expires_at else INVITE_ACTIVE

    def usable(self, now: datetime) -> bool:
        return self.status(now) == INVITE_ACTIVE
