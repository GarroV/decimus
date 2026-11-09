"""D739 (#1579): общее письмо партнёру по нескольким проверкам, зафиксированное человеком.

Тот же закон, что у одиночного письма (`letters.py`): заготовку собирает код и пересобирает,
а сюда попадает только то, что человек прочитал, поправил и подтвердил. Запись заморожена —
передумал, фиксируется НОВОЕ письмо, и обе записи видно.

Кроме текста запись помнит состав: какие проверки вошли. По нему карточка проверки говорит
«вошла в общее письмо от …», а окно письма находит зафиксированное письмо именно для этого
набора и языка (`ids_key`).

Правило выбора (одна страна, не больше семи дней, не меньше двух) проверяет вызывающий
(`src/report/batch_letter.py`); здесь стоит то, что обязана держать сама запись: все проверки
— принятые, не загруженные задним числом, не снятые, из пространства того, кто фиксирует, и из
названной страны. Чужая и несуществующая проверка дают один отказ.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from .config import check_environment
from .errors import PushError
from .pool import connection
from .queries import _require_inspection_id, _require_tenant

_COUNT_FIT_SQL = """
select count(*)
from inspections i
join units u on u.id = i.unit_id
where i.id = any(%(ids)s::uuid[])
  and i.tenant_code = %(tenant)s
  and u.country = %(country)s
  and i.status = 'finalized'
  and i.retracted_at is null
  and i.origin not in ('import', 'legacy')
"""

_INSERT_LETTER_SQL = """
insert into batch_letters (tenant_code, country, body, lang, ids_key, saved_by)
values (%(tenant)s, %(country)s, %(body)s, %(lang)s, %(key)s, %(saved_by)s)
returning id, created_at
"""

_INSERT_MEMBER_SQL = """
insert into batch_letter_inspections (batch_letter_id, inspection_id) values (%s, %s)
"""

_SELECT_COLUMNS = """
b.id, b.country, b.body, b.lang, b.saved_by, b.created_at,
(select array_agg(m.inspection_id::text order by m.inspection_id)
   from batch_letter_inspections m where m.batch_letter_id = b.id)
"""

_SELECT_LATEST_SQL = """
select __COLUMNS__
from batch_letters b
where b.tenant_code = %(tenant)s and b.ids_key = %(key)s
  and (%(lang)s::text is null or b.lang = %(lang)s)
order by b.created_at desc, b.id desc
limit 1
""".replace("__COLUMNS__", _SELECT_COLUMNS)

_SELECT_ONE_SQL = """
select __COLUMNS__
from batch_letters b
where b.tenant_code = %(tenant)s and b.id = %(id)s::uuid
""".replace("__COLUMNS__", _SELECT_COLUMNS)

_COUNT_SET_SQL = """
select count(*) from batch_letters b
where b.tenant_code = %(tenant)s and b.ids_key = %(key)s
  and (%(lang)s::text is null or b.lang = %(lang)s)
"""

_OF_INSPECTION_SQL = """
select __COLUMNS__
from batch_letters b
join batch_letter_inspections m on m.batch_letter_id = b.id
where m.inspection_id = %(inspection)s::uuid and b.tenant_code = %(tenant)s
order by b.created_at desc, b.id desc
""".replace("__COLUMNS__", _SELECT_COLUMNS)


@dataclass(frozen=True)
class SavedBatchLetter:
    """Зафиксированное общее письмо: текст, язык, страна, состав, кто и когда."""

    id: str
    country: str
    body: str
    lang: str
    saved_by: str
    created_at: datetime
    inspection_ids: tuple[str, ...]


def ids_key(inspection_ids: Sequence[str]) -> str:
    """Состав письма одной строкой: идентификаторы по возрастанию через запятую."""
    return ",".join(sorted(inspection_ids))


def _row(row: Sequence[object]) -> SavedBatchLetter:
    members = row[6] or ()
    return SavedBatchLetter(
        id=str(row[0]),
        country=str(row[1]),
        body=str(row[2]),
        lang=str(row[3]),
        saved_by=str(row[4]),
        created_at=row[5],  # type: ignore[arg-type]
        inspection_ids=tuple(str(x) for x in members),  # type: ignore[attr-defined]
    )


def _clean_ids(inspection_ids: Sequence[str]) -> tuple[str, ...]:
    return tuple(sorted({_require_inspection_id(i) for i in inspection_ids}))


def save_batch_letter(
    inspection_ids: Sequence[str],
    *,
    tenant: str,
    country: str,
    body: str,
    lang: str,
    saved_by: str,
) -> SavedBatchLetter:
    """Зафиксировать общее письмо в том виде, в каком его подтвердил человек.

    Пустой текст, язык или автор — отказ, а не пустая запись. Проверки, которые не годятся
    (чужие, неприняты, загружены задним числом, не из этой страны, несуществующие), — один
    отказ на всех: письмо не ложится ни к одной, частичной записи нет.
    """
    tenant_code = _require_tenant(tenant)
    ids = _clean_ids(inspection_ids)
    if len(ids) != len(inspection_ids):
        raise PushError("Общее письмо не сохранено: одна проверка названа дважды")
    if len(ids) < 2:
        raise PushError("Общее письмо не сохранено: в нём меньше двух проверок")
    code = country.strip().upper()
    if not code:
        raise PushError("Общее письмо не сохранено: не названа страна")
    if not body.strip():
        raise PushError("Общее письмо не сохранено: в нём нет текста")
    if not lang.strip():
        raise PushError("Общее письмо не сохранено: не назван язык, на котором оно написано")
    if not saved_by.strip():
        raise PushError("Общее письмо не сохранено: не названо, кто его зафиксировал")

    settings = check_environment()
    with connection(settings.dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(_COUNT_FIT_SQL, {"ids": list(ids), "tenant": tenant_code, "country": code})
            fit = cur.fetchone()
            if fit is None or int(fit[0]) != len(ids):
                raise PushError(
                    "Общее письмо не сохранено: не все проверки есть в истории этого "
                    "пространства по названной стране (принятые, не загруженные задним числом)"
                )
            cur.execute(
                _INSERT_LETTER_SQL,
                {
                    "tenant": tenant_code,
                    "country": code,
                    "body": body,
                    "lang": lang,
                    "key": ids_key(ids),
                    "saved_by": saved_by,
                },
            )
            row = cur.fetchone()
            if row is None:
                raise PushError("Общее письмо не сохранено: база не вернула запись")
            cur.executemany(_INSERT_MEMBER_SQL, [(row[0], ident) for ident in ids])
        conn.commit()
    return SavedBatchLetter(
        id=str(row[0]),
        country=code,
        body=body,
        lang=lang,
        saved_by=saved_by,
        created_at=row[1],
        inspection_ids=ids,
    )


def latest_for_set(
    inspection_ids: Sequence[str], *, tenant: str, lang: str | None = None
) -> SavedBatchLetter | None:
    """Последнее зафиксированное письмо ровно для этого набора проверок; `None` — не фиксировали.

    Набор должен совпасть целиком: письмо по трём проверкам не отвечает на вопрос про две из
    них. `lang` спрашивает письмо на конкретном языке — чужой язык под видом нужного не
    показывается (как у одиночного письма).
    """
    params = {
        "tenant": _require_tenant(tenant),
        "key": ids_key(_clean_ids(inspection_ids)),
        "lang": lang,
    }
    with connection(check_environment().dsn) as conn, conn.cursor() as cur:
        cur.execute(_SELECT_LATEST_SQL, params)
        row = cur.fetchone()
    return None if row is None else _row(row)


def count_for_set(inspection_ids: Sequence[str], *, tenant: str, lang: str | None = None) -> int:
    """Сколько версий письма записано для этого набора (на языке `lang`, без него — всего)."""
    params = {
        "tenant": _require_tenant(tenant),
        "key": ids_key(_clean_ids(inspection_ids)),
        "lang": lang,
    }
    with connection(check_environment().dsn) as conn, conn.cursor() as cur:
        cur.execute(_COUNT_SET_SQL, params)
        row = cur.fetchone()
    return 0 if row is None else int(row[0])


def get_batch_letter(batch_id: str, *, tenant: str) -> SavedBatchLetter | None:
    """Зафиксированное общее письмо по номеру — только своего пространства."""
    params = {"tenant": _require_tenant(tenant), "id": batch_id}
    with connection(check_environment().dsn) as conn, conn.cursor() as cur:
        cur.execute(_SELECT_ONE_SQL, params)
        row = cur.fetchone()
    return None if row is None else _row(row)


def letters_of_inspection(inspection_id: str, *, tenant: str) -> tuple[SavedBatchLetter, ...]:
    """Общие письма, в которые вошла проверка, свежие первыми (строка на карточке проверки)."""
    params = {
        "tenant": _require_tenant(tenant),
        "inspection": _require_inspection_id(inspection_id),
    }
    with connection(check_environment().dsn) as conn, conn.cursor() as cur:
        cur.execute(_OF_INSPECTION_SQL, params)
        rows = cur.fetchall()
    return tuple(_row(row) for row in rows)
