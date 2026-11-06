"""Привязка по юзернейму — для людей, чей числовой Telegram ID неизвестен (27.10.2026).

Владелец даёт юзернеймы команды, а числовых ID у нас нет: бот видит их только
в первом сообщении. Файл `access/pending_usernames.json` в каталоге состояния —
`{"юзернейм": "логин учётки"}`; ведётся руками вне git (это личные данные).
Первое же обновление от такого юзернейма привязывает его ID к учётке той же
дорогой, что и ссылка из «Настроек» (`bot_links.issue_link` + `redeem`).

Запись одноразовая (#1300): после успешной привязки её снимает `consume`, а файл,
в котором записей не осталось, удаляется. Привязывается только учётка без живой
привязки (`bot_links.bind_by_login`): записью нельзя перепривязать уже подключённого.
"""

from __future__ import annotations

import json
import logging
import os
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

    def _read(self) -> dict[str, str] | None:
        """Таблица «юзернейм (как в файле) → логин» или `None`: файла нет либо он битый."""
        if not self._path.exists():
            return None
        try:
            stored = json.loads(self._path.read_text(encoding="utf-8"))
            return {str(k): str(v) for k, v in stored.items()}
        except (OSError, ValueError, AttributeError):
            logger.warning("файл %s не разобрался — привязка по юзернейму выключена", self._path)
            return None

    def login_for(self, username: str | None) -> str | None:
        """Логин учётки для юзернейма — или `None`. Битый файл — `None` и строка в журнал."""
        table = self._read() if username else None
        if not table or not username:
            return None
        wanted = _key(username)
        return next((login for name, login in table.items() if _key(name) == wanted), None)

    def consume(self, username: str | None) -> None:
        """Снять запись юзернейма после успешной привязки; опустевший файл удалить (#1300).

        Сбой записи не ломает привязку, уже состоявшуюся: он уходит в журнал, и запись
        остаётся до ручной уборки (бот про такого человека больше ничего не сделает —
        учётка уже привязана, `bind_by_login` вторично её не привяжет).
        """
        table = self._read()
        if not username or table is None:
            return
        wanted = _key(username)
        left = {name: login for name, login in table.items() if _key(name) != wanted}
        if len(left) == len(table):
            return
        try:
            if not left:
                self._path.unlink()
                return
            tmp = self._path.with_name(self._path.name + ".tmp")
            tmp.write_text(json.dumps(left, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.replace(tmp, self._path)
        except OSError:
            logger.warning("запись юзернейма в %s не снялась после привязки", self._path)


def _key(username: str) -> str:
    return username.lstrip("@").lower()
