"""Кому открыт мини-апп обхода (#418): все проверяющие или только тестеры.

Одна переменная на бота и веб — они читают один `.env`, и разъехаться кнопка
и страница не могут: кнопку видит ровно тот, кого пустит страница. Так мини-апп
пробуется на боевом боте, не меняя ничего остальным: у них нет ни кнопки, ни
адреса, а чат работает как раньше.

Пусто — мини-апп открыт всем, у кого есть доступ к боту (стенд и будущее
«включено для всех»). Задано — только этим Telegram ID.
"""

from __future__ import annotations

from collections.abc import Mapping

WALK_USERS_VAR = "WALK_USERS"


def parse_walk_users(env: Mapping[str, str]) -> frozenset[int] | None:
    """Круг тестеров из окружения. `None` — круга нет, открыто всем с доступом.

    Кривой номер — `ValueError` на старте: молча выброшенный ID оставил бы
    тестера без кнопки, а заданный, но пустой после разбора круг — открыл бы
    мини-апп всем, хотя хотели ровно обратного.
    """
    raw = (env.get(WALK_USERS_VAR) or "").strip()
    if not raw:
        return None
    ids: set[int] = set()
    for chunk in raw.split(","):
        piece = chunk.strip()
        if not piece:
            continue
        if not piece.isdigit():
            raise ValueError(
                f"{WALK_USERS_VAR}: «{piece}» — не Telegram ID. Нужны номера через запятую"
            )
        ids.add(int(piece))
    if not ids:
        raise ValueError(f"{WALK_USERS_VAR} задан, но номеров в нём нет")
    return frozenset(ids)


def walk_open_to(users: frozenset[int] | None, user_id: int) -> bool:
    """Открыт ли мини-апп этому человеку."""
    return users is None or user_id in users
