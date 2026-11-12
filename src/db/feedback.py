"""D761 п.6: отзывы из кнопки «Обратная связь» — запись, чтение для админки, отметки.

Пишет любой вошедший (в пространство, которое ставит дверь, `space.py`); читают главный
админ и админ УК, и это решает веб (`src/web/feedback.py`), а не только эта выборка: политики
базы (`0136`) дополнительно не дают партнёру читать чужие строки. Текст после записи не
меняется — правятся лишь отметка «разобрано» и итог отправки в Telegram.

Предел частоты держит сама запись: под рекомендательным замком на учётку считается число её
отзывов за последний час, и сверх предела — `FeedbackRateLimited`, строка не ложится. Окно
общее для всех процессов (считает база), а не в памяти одного.

Чат Telegram — журнал `feedback_chat`: текущий чат — последняя строка, пустой — «выключено».
Строк нет — отправки нет: миграция чат не задаёт.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from .config import check_environment
from .errors import DbError
from .pool import connection

#: Сколько отзывов в час разрешено одной учётке.
MAX_PER_HOUR = 10
#: Сколько записей читает экран админки за раз (новые сверху).
LIST_LIMIT = 200

_LOCK_SQL = "select pg_advisory_xact_lock(hashtextextended(%s, 0))"

_COUNT_RECENT_SQL = """
select count(*) from feedback
where login = %(login)s and tenant_code = %(tenant)s
  and created_at > clock_timestamp() - interval '1 hour'
"""

_INSERT_SQL = """
insert into feedback (id, tenant_code, login, role, page, lang, body)
values (%(id)s, %(tenant)s, %(login)s, %(role)s, %(page)s, %(lang)s, %(body)s)
"""

_INSERT_PHOTO_SQL = """
insert into feedback_photos (feedback_id, position, content_type, size_bytes, data)
values (%s, %s, 'image/jpeg', %s, %s)
"""

_LIST_SQL = """
select f.id, f.tenant_code, f.login, f.role, f.page, f.lang, f.body, f.created_at,
       f.reviewed_at, f.reviewed_by, f.telegram_sent_at, f.telegram_error,
       coalesce((select array_agg(p.id::text order by p.position)
                   from feedback_photos p where p.feedback_id = f.id), '{}')
from feedback f
order by f.created_at desc, f.id
limit %(limit)s
"""

_PHOTO_SQL = """
select p.content_type, p.data from feedback_photos p
join feedback f on f.id = p.feedback_id
where p.id = %s
"""

_REVIEW_SQL = """
update feedback
set reviewed_at = case when %(reviewed)s then clock_timestamp() end,
    reviewed_by = case when %(reviewed)s then %(by)s end
where id = %(id)s
"""

_DELIVERY_SQL = """
update feedback
set telegram_sent_at = case when %(sent)s then clock_timestamp() end,
    telegram_error = %(error)s
where id = %(id)s
"""

_CHAT_SQL = "select telegram_chat_id from feedback_chat order by id desc limit 1"
_SET_CHAT_SQL = "insert into feedback_chat (telegram_chat_id, changed_by) values (%s, %s)"


class FeedbackRateLimited(DbError):
    """Учётка уже отправила `MAX_PER_HOUR` отзывов за последний час."""


@dataclass(frozen=True)
class Entry:
    """Отзыв как его видит админка: кто, откуда, что написал, фото и отметки."""

    id: str
    tenant: str
    login: str
    role: str
    page: str
    lang: str
    body: str
    created_at: datetime
    reviewed_at: datetime | None
    reviewed_by: str | None
    telegram_sent_at: datetime | None
    telegram_error: str | None
    photo_ids: tuple[str, ...]


def _require_id(value: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except ValueError as exc:
        raise DbError("Неверный номер отзыва") from exc


def save(
    *,
    tenant: str,
    login: str,
    role: str,
    page: str,
    lang: str,
    body: str,
    photos: Sequence[bytes] = (),
    max_per_hour: int = MAX_PER_HOUR,
) -> str:
    """Записать отзыв с кадрами одной транзакцией и вернуть его номер.

    Кадры приходят уже проверенными и сжатыми в JPEG (`src/web/feedback.py`): сюда не
    доходит ничего, что не картинка. Предел частоты — отказ `FeedbackRateLimited`.
    """
    new_id = str(uuid.uuid4())
    params = {
        "id": new_id,
        "tenant": tenant,
        "login": login,
        "role": role,
        "page": page,
        "lang": lang,
        "body": body,
    }
    with connection(check_environment().dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(_LOCK_SQL, (f"feedback:{tenant}:{login}",))
            cur.execute(_COUNT_RECENT_SQL, params)
            row = cur.fetchone()
            if row is not None and int(row[0]) >= max_per_hour:
                raise FeedbackRateLimited("Слишком много отзывов за последний час")
            cur.execute(_INSERT_SQL, params)
            for position, data in enumerate(photos, start=1):
                cur.execute(_INSERT_PHOTO_SQL, (new_id, position, len(data), data))
        conn.commit()
    return new_id


def entries(*, limit: int = LIST_LIMIT) -> tuple[Entry, ...]:
    """Отзывы, новые сверху. Чьи строки видны, решает пространство обращения (`0136`)."""
    with connection(check_environment().dsn) as conn:
        rows = conn.execute(_LIST_SQL, {"limit": limit}).fetchall()
    return tuple(
        Entry(
            id=str(r[0]),
            tenant=str(r[1]),
            login=str(r[2]),
            role=str(r[3]),
            page=str(r[4]),
            lang=str(r[5]),
            body=str(r[6]),
            created_at=r[7],
            reviewed_at=r[8],
            reviewed_by=r[9],
            telegram_sent_at=r[10],
            telegram_error=r[11],
            photo_ids=tuple(str(x) for x in r[12]),
        )
        for r in rows
    )


def photo(photo_id: str) -> tuple[str, bytes] | None:
    """Кадр отзыва: тип и байты; `None` — нет такого или он не виден этому пространству."""
    with connection(check_environment().dsn) as conn:
        row = conn.execute(_PHOTO_SQL, (_require_id(photo_id),)).fetchone()
    return None if row is None else (str(row[0]), bytes(row[1]))


def mark_reviewed(feedback_id: str, *, reviewed: bool, by: str) -> bool:
    """Поставить или снять «разобрано». `False` — отзыва нет (или он не виден)."""
    with connection(check_environment().dsn) as conn:
        cur = conn.execute(
            _REVIEW_SQL, {"id": _require_id(feedback_id), "reviewed": reviewed, "by": by}
        )
        return cur.rowcount == 1


def record_delivery(feedback_id: str, *, sent: bool, error: str | None = None) -> None:
    """Записать итог отправки в Telegram: ушло, либо код причины (без текста ответа)."""
    with connection(check_environment().dsn) as conn:
        conn.execute(
            _DELIVERY_SQL,
            {"id": _require_id(feedback_id), "sent": sent, "error": None if sent else error},
        )


def chat_id() -> str | None:
    """Чат Telegram для отзывов; `None` — не задан или выключен, и отправки нет."""
    with connection(check_environment().dsn) as conn:
        row = conn.execute(_CHAT_SQL).fetchone()
    return None if row is None or not row[0] else str(row[0])


def set_chat_id(value: str | None, *, by: str) -> None:
    """Задать чат Telegram для отзывов (`None` — выключить). Формат проверяет база."""
    with connection(check_environment().dsn) as conn:
        conn.execute(_SET_CHAT_SQL, (value or None, by))
