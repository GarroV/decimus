"""Что и как попадает в журналы входов и действий (D462, `0067`).

Чистый Python, без базы: правила записи общие для веба, MCP и бота, а решение «что в
журнал не кладётся» должно быть одно. Журнал действий читает главный админ, и всё,
что в него попало, лежит там 365 дней, — поэтому в нём только номера и коды, а не
содержимое форм.

**Допуск, а не запрет.** Значение поля формы, строки запроса или аргумента инструмента
попадает в сводку, только если имя названо в `SHOWN_FIELD_NAMES` (или кончается на `_id`,
`_code` и подобное) и значение само похоже на номер или код (`A-Za-z0-9_.:-`, до
`MAX_VALUE` знаков, без пробелов и `@`). Всё прочее — пароль, токен, почта, комментарий,
любое поле, которое завтра добавят и не вспомнят, — остаётся именем без значения
(`password=…`): видно, что поле было, но не что в нём. Новое поле скрыто по
умолчанию. Поверх допуска стоит вето по секретным именам (`SECRET_NAME_PARTS`).
Части пути маршрута (`/people/<login>/freeze`) допуску по имени не подчиняются, но форму
значения и вето проходят. Правило по именам, а не по маршруту: новая форма покрыта с
первого дня.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

#: Способы входа (`login_journal.method`).
METHOD_PASSWORD = "password"  # noqa: S105 — название способа входа, не пароль
METHOD_GOOGLE = "google"
METHOD_OAUTH_CLAUDE = "oauth-claude"
METHOD_MCP_TOKEN = "personal-mcp-token"  # noqa: S105 — название способа входа
METHOD_BOT_LINK = "bot-link"
#: Вторая ступень входа (D463): ключ доступа, код приложения или резервный код.
METHOD_SECOND_STEP = "second-step"

#: Исходы входа (`login_journal.result`).
RESULT_OK = "ok"
RESULT_BAD_PASSWORD = "bad-password"  # noqa: S105 — название исхода
RESULT_FROZEN = "frozen"
RESULT_UNKNOWN = "unknown"
RESULT_RATE_LIMITED = "rate-limited"
#: Пароль верный, но учётке этот способ закрыт (привязана почта Google).
RESULT_REFUSED = "refused"
#: Вторая ступень (D463): код не подошёл, ключ доступа не принят, погашен резервный код.
RESULT_BAD_CODE = "bad-code"
RESULT_PASSKEY_FAIL = "passkey-fail"
RESULT_BACKUP_USED = "backup-used"

#: Двери журнала действий (`action_journal.door`).
DOOR_WEB = "web"
DOOR_MCP = "mcp"

#: Роли, чьи действия пишутся в журнал: админ и главный админ (D462).
JOURNALED_ROLES = frozenset({"admin", "superadmin"})

MAX_USER_AGENT = 200
MAX_TARGET = 500
MAX_VALUE = 60
MAX_ACTION = 120

#: ДОПУСК, а не запрет: значение попадает в сводку, только если имя поля названо здесь
#: (точно или окончанием) И само значение выглядит как номер или код. Всё остальное —
#: только имя поля без значения: пароль, токен, почта, свободный текст, поле, которого
#: завтра добавят и не вспомнят. Новое поле по умолчанию скрыто, а не раскрыто.
SHOWN_FIELD_NAMES = frozenset(
    {
        "id", "code", "role", "status", "state", "kind", "type", "mode", "action", "lang",
        "language", "tenant", "zone", "country", "city", "period", "from", "to", "date",
        "enabled", "active", "master", "scope", "level", "version", "position", "order",
        "year", "month", "week", "day", "limit", "offset", "page", "tab", "view", "format",
        "target", "decision", "answer", "login", "checklist", "checklist_version", "version_name",
        "unit", "n", "hard", "in_bot", "equal_shares", "keep_shares", "confirm_date",
        "confirm_unit", "aggregators", "d1", "d2", "start_pct", "repeat_multiplier",
    }
)  # fmt: skip
SHOWN_FIELD_SUFFIXES = ("_id", "_code", "_ids", "_codes", "_at", "_date", "_on", "_flag")

#: Вето поверх допуска: имя с таким куском скрыто, даже если оно заканчивается на `_id`.
SECRET_NAME_PARTS = (
    "pass", "secret", "token", "csrf", "auth", "cookie", "signature", "credential",
    "verifier", "nonce", "code_challenge", "email", "mail", "phone",
)  # fmt: skip

#: Значение, похожее на номер или код: буквы, цифры, `_ . : -`, без пробелов и `@`.
_CODE_LIKE = re.compile(r"[A-Za-z0-9_.:\-]{1,%d}" % MAX_VALUE)

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
    if any(часть in lowered for часть in SECRET_NAME_PARTS):
        return True
    return not (lowered in SHOWN_FIELD_NAMES or lowered.endswith(SHOWN_FIELD_SUFFIXES))


def _shown(name: str, value: Any, *, is_path: bool = False) -> str:
    """Значение для сводки: часть пути — если похожа на код; поле — если допущено по имени."""
    if isinstance(value, bool):
        return str(value).lower() if not _vetoed(name) else HIDDEN
    if not isinstance(value, (str, int, float)):
        return HIDDEN
    text = str(value)
    if not _CODE_LIKE.fullmatch(text):
        return HIDDEN
    if _vetoed(name) or (not is_path and is_hidden_field(name)):
        return HIDDEN
    return text


def _vetoed(name: str) -> bool:
    lowered = name.lower()
    return any(часть in lowered for часть in SECRET_NAME_PARTS)


def summarize_target(*sources: Mapping[str, Any], ids: Mapping[str, Any] | None = None) -> str:
    """Сводка цели: `поле=значение; …` из адреса, строки запроса, формы или аргументов.

    `ids` — части пути маршрута (`/people/<login>/freeze`): это номера, а не ввод
    человека, допуск по имени к ним не применяется (форма значения и вето по секретным
    именам — применяются). Остальные источники
    идут по порядку, повтор имени первым выигрывает. Результат усечён до `MAX_TARGET`.
    """
    parts: dict[str, str] = {}
    for name, value in (ids or {}).items():
        parts[str(name)[:40]] = _shown(str(name), value, is_path=True)
    for source in sources:
        for name, value in source.items():
            key = str(name)[:40]
            if key not in parts:
                parts[key] = _shown(key, value)
    return "; ".join(f"{k}={v}" for k, v in parts.items())[:MAX_TARGET]
