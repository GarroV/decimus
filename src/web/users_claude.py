"""Плитка «Нейросети» в «Настройках» (D417, D695): адрес MCP и подключения через сайт.

Рядом с личным токеном (`users_mcp.py`), а не вместо него: тот — токен Claude
Desktop, этот — вход в нейросеть (ChatGPT, Claude, GLM, Kimi) своей учёткой
сайта (OAuth). Виден только в
«Настройках» самого человека, любой роли и любого пространства:
подключение — дело самого человека, и чужие подключения не видны никому.

Список и отзыв — `src/db/oauth_store.py`; отзыв действует на следующем же
вызове MCP, потому что сервер сверяет подключение на каждом запросе.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.db import oauth_store
from src.db.errors import DbError

from .db_refusal import note_target_mismatch

#: Где приложение держит внешний адрес MCP для блока (`MCP_PUBLIC_URL`).
MCP_URL_KEY = "DECIMUS_MCP_PUBLIC_URL"


#: Нейросети плитки по порядку в списке выбора (D695). Ключ — значение `?ai=`.
ASSISTANTS = ("chatgpt", "claude", "glm", "kimi")

#: Показанная по умолчанию: Claude — к ней привязаны токен Desktop и прежние ссылки.
DEFAULT_ASSISTANT = "claude"


def selected_assistant(requested: str | None) -> str:
    """Какая нейросеть раскрыта: из `?ai=`, а неизвестное значение — не ошибка, а по умолчанию."""
    return requested if requested in ASSISTANTS else DEFAULT_ASSISTANT


def claude_code_command(mcp_url: str) -> str:
    """Строка для Claude Code: добавить decimus как удалённый MCP-сервер."""
    return f"claude mcp add --transport http decimus {mcp_url}"


def codex_add_command(mcp_url: str) -> str:
    """Строка для Codex (приложение ChatGPT на компьютере): добавить decimus удалённым MCP."""
    return f"codex mcp add decimus --url {mcp_url}"


#: Вторая строка для Codex: войти (OAuth) — адрес не нужен.
CODEX_LOGIN_COMMAND = "codex mcp login decimus"


@dataclass(frozen=True)
class ClaudeConnect:
    """Что показать в блоке: включено ли, адрес, команда, подключения."""

    enabled: bool
    mcp_url: str = ""
    connections: tuple[oauth_store.Connection, ...] = ()
    #: Удалось ли прочитать подключения. Ложь — база не ответила, и пустой
    #: список был бы враньём «подключений нет».
    known: bool = True

    @property
    def command(self) -> str:
        return claude_code_command(self.mcp_url)


def claude_connect(user_id: str | None, mcp_url: str | None) -> ClaudeConnect:
    """Блок для своей карточки. Без OAuth (`MCP_PUBLIC_URL` не задан) — выключен."""
    if not mcp_url or user_id is None:
        return ClaudeConnect(enabled=False)
    try:
        подключения = oauth_store.list_connections(user_id)
    except DbError as exc:
        note_target_mismatch(exc)
        return ClaudeConnect(enabled=True, mcp_url=mcp_url, known=False)
    return ClaudeConnect(enabled=True, mcp_url=mcp_url, connections=подключения)
