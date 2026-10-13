"""Что и как попадает в журналы входов и действий (D462, `0067`).

Чистый Python, без базы: правила записи общие для веба, MCP и бота, а решение «что в
журнал не кладётся» должно быть одно. Журнал действий читает главный админ, и всё,
что в него попало, лежит там 365 дней, — поэтому в нём только номера и коды, а не
содержимое форм.

**Что не попадает никогда.** Значение поля, чьё имя похоже на секрет (пароль, токен,
ключ, подпись, кука) или на свободный текст и личные данные (комментарий, почта,
телефон, содержимое), в сводку не кладётся — остаётся имя поля без значения
(`password=…`): видно, что поле было, но не что в нём. Длинное значение (больше
`MAX_VALUE`) — тоже свободный текст, а не номер; вложенное (список, словарь) — только
имя. Правило по имени, а не по маршруту: новая форма покрыта с первого дня, и забыть
шаг на новом пути нельзя.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

#: Способы входа (`login_journal.method`).
METHOD_PASSWORD = "password"  # noqa: S105 — название способа входа, не пароль
METHOD_GOOGLE = "google"
METHOD_OAUTH_CLAUDE = "oauth-claude"
METHOD_MCP_TOKEN = "personal-mcp-token"  # noqa: S105 — название способа входа
METHOD_BOT_LINK = "bot-link"

#: Исходы входа (`login_journal.result`).
RESULT_OK = "ok"
RESULT_BAD_PASSWORD = "bad-password"  # noqa: S105 — название исхода
RESULT_FROZEN = "frozen"
RESULT_UNKNOWN = "unknown"
RESULT_RATE_LIMITED = "rate-limited"
#: Пароль верный, но учётке этот способ закрыт (привязана почта Google).
RESULT_REFUSED = "refused"

#: Двери журнала действий (`action_journal.door`).
DOOR_WEB = "web"
DOOR_MCP = "mcp"

#: Роли, чьи действия пишутся в журнал: админ и главный админ (D462).
JOURNALED_ROLES = frozenset({"admin", "superadmin"})

MAX_USER_AGENT = 200
MAX_TARGET = 500
MAX_VALUE = 60
MAX_ACTION = 120

#: Куски имён полей, чьё значение не пишется. Пишется имя поля без значения.
SECRET_NAME_PARTS = (
    "pass",
    "secret",
    "token",
    "key",
    "csrf",
    "auth",
    "cookie",
    "signature",
    "credential",
    "verifier",
    "nonce",
    "code_challenge",
    "comment",
    "note",
    "text",
    "message",
    "body",
    "reason",
    "description",
    "content",
    "payload",
    "json",
    "csv",
    "file",
    "email",
    "mail",
    "phone",
    "tel",
    "address",
    "name",
    "fio",
)

#: Что стоит вместо значения, которого в журнале быть не должно.
HIDDEN = "…"


def truncate_user_agent(raw: str | None) -> str | None:
    """Браузер для журнала: усечён, пустой — `None`."""
    if not raw:
        return None
    return raw[:MAX_USER_AGENT]


def is_hidden_field(name: str) -> bool:
    """Значение поля с таким именем в журнал не кладётся."""
    lowered = name.lower()
    return any(часть in lowered for часть in SECRET_NAME_PARTS)


def _shown(name: str, value: Any, *, is_id: bool = False) -> str:
    if (is_hidden_field(name) and not is_id) or not isinstance(value, (str, int, float, bool)):
        return HIDDEN
    text = str(value)
    if len(text) > MAX_VALUE or "\n" in text:
        return HIDDEN
    return text


def summarize_target(*sources: Mapping[str, Any], ids: Mapping[str, Any] | None = None) -> str:
    """Сводка цели: `поле=значение; …` из адреса, строки запроса, формы или аргументов.

    `ids` — части пути маршрута (`/people/<login>/freeze`): это номера, а не ввод
    человека, их имя под запрет не попадает (длина — попадает). Остальные источники
    идут по порядку, повтор имени первым выигрывает. Результат усечён до `MAX_TARGET`.
    """
    parts: dict[str, str] = {}
    for name, value in (ids or {}).items():
        parts[str(name)[:40]] = _shown(str(name), value, is_id=True)
    for source in sources:
        for name, value in source.items():
            key = str(name)[:40]
            if key not in parts:
                parts[key] = _shown(key, value)
    return "; ".join(f"{k}={v}" for k, v in parts.items())[:MAX_TARGET]
