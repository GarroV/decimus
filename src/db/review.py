"""D199: приёмка проверки — вычитка человеком между обходом и историей сети.

До этого этапа слив бота был последним словом: проверка попадала в историю в ту
же секунду, когда аудитор дошёл до последнего пункта. Теперь она ждёт вычитки в
статусе `review`: записи правятся (ошибка «грязный пол в горячем цехе вместо
зала» чинится здесь, а не снятием всей проверки), а историей сети проверка
становится только после подтверждения.

Почему приёмка — отдельный модуль, а не функция в `push.py`: слив пишет
проверку, приёмка её принимает, и это разные права. Слив идёт из бота, приёмка
— из админки рукой человека, и подпись этой руки остаётся в строке.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg

from .config import check_environment
from .errors import ReviewError
from .queries import _require_inspection_id, _require_tenant

#: Принять можно только то, что вычитывают. Условие `status = 'review'` не
#: украшение: без него повторное подтверждение молча переписало бы подпись и
#: время у уже принятой проверки, а «принято дважды» — это либо двойной клик,
#: либо спор о том, кто именно пустил проверку в историю.
_ACCEPT_SQL = """
update inspections
   set status = 'finalized', accepted_at = now(), accepted_by = %(author)s
 where id = %(id)s
   and tenant_code = %(tenant)s
   and status = 'review'
returning accepted_at
"""


@dataclass(frozen=True)
class Acceptance:
    """Принятая проверка: что именно приняли, кто и когда."""

    inspection_id: str
    author: str
    accepted_at: datetime


@contextmanager
def _accepting() -> Iterator[psycopg.Connection[Any]]:
    """Подключение приложения на время приёмки; отказ базы — `ReviewError`.

    Наружу уходит тип исключения, а не его текст: в тексте драйвера может
    оказаться строка подключения.
    """
    try:
        with psycopg.connect(check_environment().dsn) as conn:
            yield conn
    except psycopg.Error as exc:
        raise ReviewError(f"Не удалось принять проверку ({type(exc).__name__})") from exc


def _require_author(author: str) -> str:
    """Подпись принявшего — или отказ.

    Пустая подпись превратила бы приёмку в анонимную: строка выглядела бы
    принятой, а на вопрос «кем» ответа не было бы вовсе.
    """
    подпись = (author or "").strip()
    if not подпись:
        raise ReviewError("Не удалось принять проверку: не названа учётка принимающего")
    return подпись


def accept_inspection(inspection_id: str, *, tenant: str, author: str) -> Acceptance:
    """Принять вычитанную проверку — и тем сделать её историей сети.

    Отказ, а не тихий успех, если проверки нет или она уже принята: «принято»
    в ответ на второе нажатие означало бы, что подпись и время в строке
    относятся неизвестно к какому из двух действий.
    """
    ид = _require_inspection_id(inspection_id)
    код = _require_tenant(tenant)
    подпись = _require_author(author)

    with _accepting() as conn, conn.cursor() as cur:
        cur.execute(_ACCEPT_SQL, {"id": ид, "tenant": код, "author": подпись})
        строка = cur.fetchone()

    if строка is None:
        raise ReviewError(
            f"Не удалось принять проверку {ид}: она не ждёт вычитки — "
            f"либо принята раньше, либо её нет у этого арендатора"
        )
    return Acceptance(inspection_id=ид, author=подпись, accepted_at=строка[0])
