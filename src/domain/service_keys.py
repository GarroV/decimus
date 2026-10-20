"""Реестр ключей внешних сервисов, которые главный админ ставит на экране (D576, #906).

**Список закрытый.** Имена секретов в `vault.secrets` и коды сервисов и полей — только
отсюда: из формы или адреса приходит код, по нему ищется запись реестра, неизвестный —
404. Свободного имени нет нигде, а `check` в таблице (`0084`) дублирует этот список:
ни код, ни база не примут чужое имя.

Здесь нет ни значений, ни обращений к базе и сети: реестр — чистые данные. Чтение
значения (база, затем окружение) — `src/db/service_keys.py`, проверка у провайдера —
`src/web/service_probes.py`.

В реестре только секреты, чьё неверное значение ломает одну функцию. Токен бота,
Google OAuth, S3, `WEB_SECRET_KEY`, токены MCP и сам `SECRETS_KEY` остаются в окружении
сервера: неверное значение там ломает вход или бота целиком, а `SECRETS_KEY` — ключ,
которым шифруется остальное (`docs/12-web-admin.md`).
"""

from __future__ import annotations

from dataclasses import dataclass

#: Хост iSpring Learn API — постоянная, не секрет.
ISPRING_HOST = "https://api-learn.ispring.com"


@dataclass(frozen=True)
class KeyField:
    """Одно секретное поле сервиса: код в форме и имя записи в `vault.secrets`."""

    code: str
    vault_name: str
    env_var: str


@dataclass(frozen=True)
class Service:
    """Сервис и его поля. `code` же пишется в `vault.secrets.provider`."""

    code: str
    fields: tuple[KeyField, ...]

    def field(self, code: str) -> KeyField | None:
        return next((f for f in self.fields if f.code == code), None)


SERVICES: tuple[Service, ...] = (
    # Ключ модели (D491): запись называется `model_key` с первого дня — не переименовывается.
    Service("openai", (KeyField("api_key", "model_key", "OPENAI_API_KEY"),)),
    Service("pointer", (KeyField("api_key", "pointer.api_key", "POINTER_API_KEY"),)),
    Service(
        "ispring",
        (
            KeyField("client_id", "ispring.client_id", "ISPRING_CLIENT_ID"),
            KeyField("client_secret", "ispring.client_secret", "ISPRING_CLIENT_SECRET"),
        ),
    ),
)

_BY_CODE = {s.code: s for s in SERVICES}

#: Все допустимые имена записей; ровно этот список стоит в `check` таблицы (`0084`).
VAULT_NAMES: frozenset[str] = frozenset(f.vault_name for s in SERVICES for f in s.fields)

#: Предел длины значения: настоящие ключи — десятки знаков; больше — вставили не то.
MAX_LENGTH = 400
#: Сколько последних знаков видно на экране.
LAST_CHARS = 4
#: Свежесть подтверждения для сохранения и удаления (минуты).
STEP_UP_MINUTES = 10


def service(code: str) -> Service | None:
    """Сервис по коду из адреса; неизвестный — `None`."""
    return _BY_CODE.get(code)


def field_of(service_code: str, field_code: str) -> KeyField | None:
    found = service(service_code)
    return None if found is None else found.field(field_code)


def form_name(field_code: str) -> str:
    """Имя поля формы. Содержит `secret`: журнал действий значение такого поля не берёт."""
    return f"secret_{field_code}"


def is_acceptable(value: str) -> bool:
    """Форма значения: непустое, без пробелов и непечатаемых, не длиннее предела."""
    return (
        bool(value)
        and len(value) <= MAX_LENGTH
        and all(c.isprintable() and not c.isspace() for c in value)
    )
