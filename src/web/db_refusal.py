"""Отказ базы словами для вошедшего — без устройства стенда (#515, F-012 аудита 12.10).

Слой `db` пишет отказ так, чтобы его понял оператор: расхождение подключений
(`DatabaseTargetError`) называет каждую базу, хост, порт и роль, а часть модулей
вкладывает в текст отказа строку драйвера целиком — с хостом, адресом и ролью.
Командам в терминале это нужно; вошедшему в админку, в том числе партнёру, — нет.

**Поэтому экран показывает только известные причины — белым списком.** Отказ,
которого в списке нет, получает общий текст, а подробности уходят в журнал
сервера на уровне ERROR, где их найдёт тот, кто чинит. Чёрный список («прятать
расхождение, остальное как есть») пропускал на экран всё, о чём не подумали:
новый модуль с `{exc}` в тексте открывал карту стенда первым же сбоем.

Узнать расхождение и записать его в журнал — общее правило веба и MCP, оно
живёт в `src/db/target_refusal.py`; здесь только текст экрана.
"""

from __future__ import annotations

import logging

from src.db.errors import DomainRefusal
from src.db.target_refusal import note_target_mismatch

from .texts import TEXTS, t

#: Ключ общего текста в каталоге (`texts_refusals.py`). Тот же ключ — код отказа
#: MCP `db_target` (`src/mcp/db_target.py`): текст один на обе поверхности.
DB_TARGET_KEY = "refusal.db_target"

#: Текст на всё, чего нет в белом списке: база не ответила, без подробностей.
DB_GENERIC_KEY = "refusal.db_generic"

#: Общий текст на отказ действия над проверкой без кода или с неизвестным.
DOMAIN_GENERIC_KEY = "refusal.domain_generic"

#: Белый список отказов действий над проверкой (F-012): код отказа → ключ
#: текста. Код ставит тот, кто пишет `raise`; текст исключения экран не видит.
#: Своего ключа нет — берётся `refusal.domain.<код>`; здесь только те, у кого
#: фраза уже живёт в каталоге экрана.
_DOMAIN_KEYS: dict[str, str] = {
    "revise_legacy": "revise.legacy",
    "photo_unreadable": "photo.unreadable",
    "add_photo_failed": "add.photo_failed",
}

__all__ = [
    "DB_GENERIC_KEY",
    "DB_TARGET_KEY",
    "DOMAIN_GENERIC_KEY",
    "domain_reason",
    "note_target_mismatch",
    "public_reason",
]

logger = logging.getLogger(__name__)


def public_reason(exc: BaseException, lang: str) -> str:
    """Текст отказа для экрана: известная причина — своими словами, прочее — общим текстом.

    Текст самого исключения на экран не уходит никогда: он пишется оператору и
    может нести хост, роль и кусок запроса. Он уходит в журнал.
    """
    if note_target_mismatch(exc):  # пишет в журнал сам
        return t(DB_TARGET_KEY, lang)
    logger.error("отказ базы показан общим текстом: %s: %s", type(exc).__name__, exc)
    return t(DB_GENERIC_KEY, lang)


def domain_reason(exc: DomainRefusal, lang: str) -> str:
    """Причина отказа действия над проверкой для экрана: по коду, не по тексту.

    Текст исключения (`str(exc)`) пишется оператору: в нём счётчики строк, роль
    базы, ответ хранилища. На экран он не уходит никогда — ни в карточку, ни в
    JSON. Известный код даёт фразу на языке интерфейса; отказ без кода или с
    неизвестным кодом — общий текст, а подробности (с причиной-драйвером, если
    она есть) — в журнал сервера. Параметр-отказ (кадр не приложен: причина)
    переводится тем же правилом.
    """
    ключ = _DOMAIN_KEYS.get(exc.code or "", f"refusal.domain.{exc.code}")
    if exc.code is None or ключ not in TEXTS:
        logger.error(
            "отказ показан общим текстом: %s: %s",
            type(exc).__name__,
            exc,
            exc_info=exc.__cause__ is not None,
        )
        return t(DOMAIN_GENERIC_KEY, lang)
    параметры = {
        имя: domain_reason(значение, lang) if isinstance(значение, DomainRefusal) else значение
        for имя, значение in exc.params.items()
    }
    return t(ключ, lang, **параметры)
