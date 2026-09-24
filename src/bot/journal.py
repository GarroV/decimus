"""Журнал разбора проверки: что система увидела, предложила и что сделал человек (#367, D179).

Нужен тому, кто разбирает боевой случай и донастраивает распознавание. Повод —
проверка 24.09.2026: аудитор удалил предложенную запись и завёл другим пунктом,
а восстановить, что ушло в модель и что она ответила, было не по чему. Журнал
контейнера говорит только «модель вызывалась», предложения живут в памяти
процесса, а удалённая запись уносит с собой и слова, и предложение.

Строка на событие, JSON, в папке проверки рядом с `inspection.json`. Начало
новой проверки закрывает журнал прошлой (`close`): он переименовывается с
отметкой времени и остаётся лежать — текста там мало, а разбор бывает нужен
через неделю.

**Журнал не останавливает проверку.** Не записалась строка — это потеря
сведений для разбора, а не повод уронить хендлер посреди обхода точки. Отказ
уходит в журнал контейнера с трассой (`logger.exception`), молча он не
проглатывается.

Голос сюда попадает только расшифровкой (D179): аудио не сохраняется нигде.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.domain import check_environment
from src.domain.engine import chat_dir
from src.domain.errors import DomainError

logger = logging.getLogger(__name__)

JOURNAL_FILE_NAME = "journal.jsonl"
#: Закрытый журнал прошлой проверки: `journal-20260924T113749Z.jsonl`.
CLOSED_PREFIX = "journal-"


def journal_path(chat_id: int) -> Path:
    """Журнал идущей проверки этого чата."""
    return chat_dir(chat_id, check_environment()) / JOURNAL_FILE_NAME


def _now() -> datetime:
    return datetime.now(UTC)


def note(chat_id: int, event: str, **fields: Any) -> None:
    """Дописать событие. Отказ — в журнал контейнера, наружу не поднимается."""
    line = {"at": _now().isoformat(timespec="seconds"), "event": event, **fields}
    try:
        path = journal_path(chat_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Одна запись `write` в режиме дописывания: строка не перемешается с
        # соседней, даже если два события придут подряд.
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")
    except (OSError, DomainError, TypeError, ValueError):
        logger.exception("журнал разбора: событие %s в чате %s не записалось", event, chat_id)


def close(chat_id: int) -> Path | None:
    """Закрыть журнал прошлой проверки: переименовать с отметкой времени.

    Журнала не было — нечего закрывать, это законно. Отказ переименования —
    в журнал контейнера: новая проверка из-за него не встаёт, но строки новой
    тогда допишутся к старой, и разбирающий это увидит по событию `started`.
    """
    try:
        path = journal_path(chat_id)
        if not path.exists():
            return None
        target = path.with_name(f"{CLOSED_PREFIX}{_now():%Y%m%dT%H%M%SZ}.jsonl")
        path.rename(target)
        return target
    except (OSError, DomainError):
        logger.exception("журнал разбора в чате %s не закрылся", chat_id)
        return None


def candidates(items: Iterable[Any]) -> list[dict[str, Any]]:
    """Кандидаты модели в виде строк журнала — всё, что она про них сказала."""
    return [
        {
            "code": c.code,
            "level": c.level,
            "zone": c.zone,
            "wording": c.wording,
            "confidence": c.confidence,
            "reason": c.reason,
            "flags": list(c.flags),
        }
        for c in items
    ]


def finding(item: Any) -> dict[str, Any]:
    """Запись проверки так, как она стояла в момент события."""
    return {
        "n": item.n,
        "code": item.code,
        "level": item.level,
        "zone": item.zone,
        "text": item.text,
        "photos": len(item.photos),
    }
