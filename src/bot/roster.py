"""Кого бот уже узнал: связки «юзернейм → числовой Telegram ID» (#230).

Приглашение (`src.bot.invites`) называет юзернейм, а пускает бот по ID.
Промежуток между этими двумя состояниями и живёт здесь: человек написал —
ID из апдейта записан рядом с юзернеймом, и дальше проверка идёт по числу.

**Почему файл в каталоге состояния, а не Postgres.** База у продукта есть, и
круг доступа к MCP лежит именно в ней (`src.db.mcp_access`). Но там отказ базы
означает лишь, что не объявится пункт меню, — а здесь он означал бы, что
аудитор не может работать. `src.bot.app` держит это прямо: «отказ базы не
мешает боту подняться», обход точки важнее. Каталог состояния боту обязателен
и так (`STATE_DIR`, `src.domain.config`), поэтому связки здесь не добавляют
новой точки отказа, тогда как база — добавила бы.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .errors import BotConfigError
from .invites import Invite, normalize_username

#: Полка связок внутри каталога состояния. Отдельным каталогом, а не файлом в
#: корне: рядом с папками проверок (`chat-<id>`) одиночный файл читается как
#: чья-то забытая проверка.
ROSTER_DIR = "access"
ROSTER_FILE = "roster.json"

#: Версия формата. Пишется с первого дня: молча изменившаяся раскладка файла,
#: который переживает перезапуски, — то, что потом разбирают по чужим стендам.
FORMAT_VERSION = 1


@dataclass(frozen=True)
class RosterEntry:
    """Один узнанный человек."""

    telegram_id: int
    username: str
    name: str | None
    activated_at: str


class Roster:
    """Связки на диске. Читается при подъёме, дополняется при первом контакте."""

    def __init__(self, state_dir: Path, entries: Mapping[int, RosterEntry]) -> None:
        self._state_dir = state_dir
        self._entries: dict[int, RosterEntry] = dict(entries)

    @classmethod
    def load(cls, state_dir: Path) -> Roster:
        """Прочитать связки. Нет файла — пустой список, битый файл — отказ."""
        path = _path(state_dir)
        if not path.exists():
            return cls(state_dir, {})
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
            entries = {
                int(item["telegram_id"]): RosterEntry(
                    telegram_id=int(item["telegram_id"]),
                    username=normalize_username(str(item["username"])),
                    name=(item.get("name") or None),
                    activated_at=str(item.get("activated_at") or ""),
                )
                for item in stored["entries"]
            }
        except (OSError, ValueError, TypeError, KeyError) as err:
            raise BotConfigError(
                f"Файл связок доступа {path} не разобрался: {err}. Пока он битый, "
                f"приглашённые аудиторы войти не смогут — почините или удалите его"
            ) from err
        return cls(state_dir, entries)

    def knows(self, telegram_id: int) -> bool:
        """Узнан ли этот ID раньше."""
        return telegram_id in self._entries

    def username_used(self, username: str) -> bool:
        """Сработало ли уже приглашение на этот юзернейм.

        Второй раз оно не срабатывает никогда: юзернейм владелец отпускает, а
        ID — нет.
        """
        wanted = normalize_username(username)
        return any(entry.username == wanted for entry in self._entries.values())

    def names(self) -> dict[int, str]:
        """Имена для шапки отчёта — только те, что назвало приглашение."""
        return {entry.telegram_id: entry.name for entry in self._entries.values() if entry.name}

    def activate(self, telegram_id: int, invite: Invite) -> RosterEntry:
        """Запомнить человека и сразу положить связки на диск."""
        entry = RosterEntry(
            telegram_id=telegram_id,
            username=invite.username,
            name=invite.name,
            activated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        )
        self._entries[telegram_id] = entry
        self._save()
        return entry

    def _save(self) -> None:
        """Записать через временный файл с переименованием.

        Обрыв на записи не должен оставлять обрезанный JSON: следующий подъём
        прочитал бы его как битый и отказался стартовать — то есть одна
        неудачная запись останавливала бы работу всем.
        """
        path = _path(self._state_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": FORMAT_VERSION,
            "entries": [
                {
                    "telegram_id": entry.telegram_id,
                    "username": entry.username,
                    "name": entry.name,
                    "activated_at": entry.activated_at,
                }
                for entry in sorted(self._entries.values(), key=lambda e: e.telegram_id)
            ],
        }
        tmp = path.with_name(f".{path.name}.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)


def _path(state_dir: Path) -> Path:
    return state_dir / ROSTER_DIR / ROSTER_FILE
