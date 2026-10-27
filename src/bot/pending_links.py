"""Привязка по юзернейму — для людей, чей числовой Telegram ID неизвестен (27.10.2026).

Владелец даёт юзернеймы команды, а числовых ID у нас нет: бот видит их только
в первом сообщении. Файл `access/pending_usernames.json` в каталоге состояния —
`{"юзернейм": "логин учётки"}`; ведётся руками вне git (это личные данные).
Первое же обновление от такого юзернейма привязывает его ID к учётке той же
дорогой, что и ссылка из «Настроек» (`bot_links.issue_link` + `redeem`).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

PENDING_FILE = "pending_usernames.json"


class PendingUsernames:
    """Ожидающие привязки юзернеймы. Файл читается при каждом вопросе: правка без рестарта."""

    def __init__(self, path: Path) -> None:
        self._path = path

    @classmethod
    def at(cls, state_dir: Path, access_dir: str) -> PendingUsernames:
        return cls(state_dir / access_dir / PENDING_FILE)

    def login_for(self, username: str | None) -> str | None:
        """Логин учётки для юзернейма — или `None`. Битый файл — `None` и строка в журнал."""
        if not username or not self._path.exists():
            return None
        try:
            stored = json.loads(self._path.read_text(encoding="utf-8"))
            table = {str(k).lstrip("@").lower(): str(v) for k, v in stored.items()}
        except (OSError, ValueError, AttributeError):
            logger.warning("файл %s не разобрался — привязка по юзернейму выключена", self._path)
            return None
        return table.get(username.lstrip("@").lower())
