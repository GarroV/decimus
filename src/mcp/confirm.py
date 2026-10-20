"""Двухшаговое подтверждение опасных инструментов MCP (F-130, #1006).

Инструмент, помеченный в каталоге (`ToolSpec.confirm_effect`), с первого вызова
не выполняется: сервер отвечает описанием эффекта и токеном, а действие
происходит вторым вызовом с теми же аргументами и этим токеном. Так внешняя
модель, которую увели непрямой инъекцией, не может сделать опасное одним
вызовом: между «хочу» и «сделано» стоит ответ, который обязан прочесть человек.

Честный предел: токен не доказывает, что человек прочёл ответ, — клиент может
повторить вызов сам. Он гарантирует другое: действие совершается только по
ТОЧНЫМ аргументам, которые были названы в ответе-подтверждении, и только в
пределах срока. Ролевая политика (`policy.py`) стоит раньше и не ослаблена.

**Токен** — `<срок>.<hmac>`: HMAC-SHA256 от арендатора, автора, имени
инструмента, канонического JSON аргументов и срока. Подтверждение одного
действия не подходит ни к другому инструменту, ни к изменённым аргументам, ни
к другому арендатору или автору. Срок — `TOKEN_TTL_SECONDS`.

**Секрет** — переменная `MCP_CONFIRM_SECRET`; не задана — на старте процесса
рождается случайный и живёт в памяти. Тогда токен действует только в жизни
процесса (рестарт или второй воркер его не примут) — строже, а для двух
вызовов подряд этого достаточно. В коде секретов нет.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any

#: Имя аргумента-токена. Объявляется в схеме каждого помеченного инструмента и
#: снимается в диспетчере до обработчика: сам обработчик о нём не знает.
TOKEN_ARGUMENT = "confirmation_token"  # noqa: S105 - имя аргумента, не секрет

#: Срок жизни токена: достаточно, чтобы человек прочёл и ответил, и мало,
#: чтобы выданный токен лежал и ждал случая.
TOKEN_TTL_SECONDS = 300

#: Переменная окружения с секретом подписи токенов.
SECRET_ENV = "MCP_CONFIRM_SECRET"  # noqa: S105 - имя переменной, не секрет

_PROCESS_SECRET = secrets.token_bytes(32)


def _secret() -> bytes:
    configured = os.environ.get(SECRET_ENV, "")
    return configured.encode("utf-8") if configured else _PROCESS_SECRET


def _now() -> int:
    return int(time.time())


def _canonical(arguments: dict[str, Any]) -> str:
    return json.dumps(arguments, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _sign(tool: str, tenant: str, actor: str, arguments: dict[str, Any], expires: int) -> str:
    message = "\x00".join((tenant, actor, tool, _canonical(arguments), str(expires)))
    return hmac.new(_secret(), message.encode("utf-8"), hashlib.sha256).hexdigest()


def issue(tool: str, *, tenant: str, actor: str, arguments: dict[str, Any]) -> str:
    """Токен на ровно этот вызов: инструмент, арендатор, автор, аргументы."""
    expires = _now() + TOKEN_TTL_SECONDS
    return f"{expires}.{_sign(tool, tenant, actor, arguments, expires)}"


def verify(token: str, tool: str, *, tenant: str, actor: str, arguments: dict[str, Any]) -> bool:
    """Токен верен для ЭТОГО вызова и не истёк. Любая порча формы — `False`."""
    head, dot, signature = token.partition(".")
    if not dot or not head.isdigit():
        return False
    expires = int(head)
    if expires < _now():
        return False
    expected = _sign(tool, tenant, actor, arguments, expires)
    return hmac.compare_digest(expected, signature)


def challenge(
    tool: str, effect: str, *, tenant: str, actor: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    """Ответ первого шага: что изменится и токен для второго. Не отказ."""
    token = issue(tool, tenant=tenant, actor=actor, arguments=arguments)
    shown = json.dumps(arguments, ensure_ascii=False, sort_keys=True)
    text = (
        f"Требуется подтверждение. Действие НЕ выполнено.\n"
        f"Инструмент: {tool}\n"
        f"Эффект: {effect}\n"
        f"Аргументы: {shown}\n"
        f"Покажите это человеку. Только если он согласен — повторите ТОЧНО этот же "
        f'вызов с дополнительным аргументом {TOKEN_ARGUMENT}="{token}". '
        f"Токен действует {TOKEN_TTL_SECONDS // 60} мин и подходит только к этим аргументам."
    )
    return {
        "content": [{"type": "text", "text": text}],
        "structuredContent": {
            "status": "confirmation_required",
            "executed": False,
            "tool": tool,
            "effect": effect,
            "arguments": arguments,
            "confirmation_token_argument": TOKEN_ARGUMENT,
            "confirmation_token": token,
            "expires_in_seconds": TOKEN_TTL_SECONDS,
        },
    }
