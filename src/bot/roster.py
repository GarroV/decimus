"""Связки «юзернейм → Telegram ID», собранные по приглашениям до D286 (#230).

**Совместимость до снятия (вопрос 2 волны 1, #340).** Приглашения по юзернейму
сняты: человек теперь привязывает бота к своей учётке через веб
(`src.db.bot_links`). Кого бот узнал по приглашению раньше, тот продолжает
работать как сотрудник УК — пока владелец не снимет совместимость. Поэтому
файл только читается: новых связок не появляется, и дописывать его некому.

Файл лежит в каталоге состояния, а не в Postgres, по прежней причине: отказ
базы не должен оставлять аудитора на точке без бота.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .errors import BotConfigError

#: Полка связок внутри каталога состояния. Отдельным каталогом, а не файлом в
#: корне: рядом с папками проверок (`chat-<id>`) одиночный файл читается как
#: чья-то забытая проверка.
ROSTER_DIR = "access"
ROSTER_FILE = "roster.json"


@dataclass(frozen=True)
class RosterEntry:
    """Один узнанный человек."""

    telegram_id: int
    name: str | None


class Roster:
    """Связки на диске, прочитанные при подъёме. Только чтение."""

    def __init__(self, entries: Mapping[int, RosterEntry]) -> None:
        self._entries: dict[int, RosterEntry] = dict(entries)

    @classmethod
    def load(cls, state_dir: Path) -> Roster:
        """Прочитать связки. Нет файла — пустой список, битый файл — отказ."""
        path = state_dir / ROSTER_DIR / ROSTER_FILE
        if not path.exists():
            return cls({})
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
            entries = {
                int(item["telegram_id"]): RosterEntry(
                    telegram_id=int(item["telegram_id"]),
                    name=(item.get("name") or None),
                )
                for item in stored["entries"]
            }
        except (OSError, ValueError, TypeError, KeyError) as err:
            raise BotConfigError(
                f"Файл связок доступа {path} не разобрался: {err}. Пока он битый, "
                f"аудиторы, узнанные по приглашению, войти не смогут — почините или "
                f"удалите его"
            ) from err
        return cls(entries)

    def knows(self, telegram_id: int) -> bool:
        """Узнан ли этот ID по приглашению раньше."""
        return telegram_id in self._entries

    def names(self) -> dict[int, str]:
        """Имена для шапки отчёта — только те, что назвало приглашение."""
        return {entry.telegram_id: entry.name for entry in self._entries.values() if entry.name}
