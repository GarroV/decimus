"""Доступ к Claude (MCP) в карточке человека: статус, «Дать доступ», «Снять доступ» (#583).

До этого круг доступа вёлся только в боте (`src/bot/routers/mcp.py`). Правило
круга то же, что в боте, и новых прав здесь нет:

* круг плоский — кто в нём состоит, тот приводит следующего и снимает
  поимённо (D099); вошедший «в круге», если его СВОЙ привязанный Telegram в
  круге или он основатель круга из настройки стенда;
* круг держится на Telegram ID, поэтому доступ даётся только человеку с
  привязанным ботом; привязки чужих людей видят главный админ и админ УК, и
  только им в чужой карточке видны кнопки круга;
* основателя круга называет настройка стенда (`BOT_MCP_OWNER_ID`, переменная
  бота), и снять его нельзя: при следующем обращении бот вернул бы его в круг,
  и снятие оказалось бы молча отменённой работой;
* снятие гасит живые токены одним движением (`revoke_access`).

Выпуск личного токена с командой настройки Claude Desktop остаётся в боте
(`/mcp`): команду собирает блок бота (`src/bot/mcp_setup.py`), а веб его
импортировать не может по контракту слоёв.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from src.db import mcp_access
from src.db.errors import DbError

from .db_refusal import note_target_mismatch

#: Переменная бота с основателем круга. Имя повторено, а не импортировано:
#: `src.web` и `src.bot` — пиры и друг друга не импортируют.
MCP_OWNER_ID_VAR = "BOT_MCP_OWNER_ID"


def founder_id() -> int | None:
    """Основатель круга из окружения стенда; `None` — не задан или не число."""
    сырое = (os.environ.get(MCP_OWNER_ID_VAR) or "").strip()
    return int(сырое) if сырое.isdigit() else None


@dataclass(frozen=True)
class Status:
    """Круг доступа к Claude глазами карточки: кто в нём и может ли вошедший править."""

    known: bool
    actor_in_circle: bool
    founder: int | None
    rows: dict[int, mcp_access.AdminRow] = field(default_factory=dict)

    def of(self, telegram_id: int | None) -> mcp_access.AdminRow | None:
        """Строка круга этого Telegram; `None` — в круге не был никогда."""
        return None if telegram_id is None else self.rows.get(telegram_id)

    def live(self, telegram_id: int | None) -> bool:
        строка = self.of(telegram_id)
        return строка is not None and строка.is_live


def _actor_in(rows: dict[int, mcp_access.AdminRow], own: Any, founder: int | None) -> bool:
    if own is None:
        return False
    tg = int(own.telegram_id)
    строка = rows.get(tg)
    return tg == founder or (строка is not None and строка.is_live)


def card_status(*, круг_видит: bool, own: Any, bindings: dict[str, Any]) -> Status:
    """Статус круга для карточек страницы. Без привязок спрашивать базу не о чем."""
    основатель = founder_id()
    if own is None and not (круг_видит and bindings):
        return Status(known=True, actor_in_circle=False, founder=основатель)
    try:
        строки = {r.telegram_id: r for r in mcp_access.list_admins()}
    except DbError as exc:
        note_target_mismatch(exc)
        return Status(known=False, actor_in_circle=False, founder=основатель)
    return Status(
        known=True,
        actor_in_circle=_actor_in(строки, own, основатель),
        founder=основатель,
        rows=строки,
    )


def actor_may_edit(own: Any) -> bool:
    """Может ли вошедший править круг прямо сейчас — по базе, не по странице."""
    if own is None:
        return False
    tg = int(own.telegram_id)
    return tg == founder_id() or mcp_access.is_admin(tg)
