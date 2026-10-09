"""T333 (#310): письмо партнёру, зафиксированное человеком.

Движок собирает ЗАГОТОВКУ письма и продолжает это делать. Сюда попадает
только то, что человек прочитал, поправил и подтвердил как отправляемое —
«модель предлагает, фиксирует человек» (`CLAUDE.md`).

Разница между заготовкой и записью здесь принципиальная, а не стилистическая.
Заготовка пересобирается каждый раз и от пересборки меняется: правка методики,
новый шаблон, другая версия движка. Запись не меняется ничем — иначе ответ на
вопрос «что именно мы отправили партнёру» зависел бы от дня, когда его задали,
а у партнёра на руках лежит один-единственный текст.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import psycopg

from .config import check_environment
from .cross_space import Entry, record
from .errors import PushError
from .queries import _require_inspection_id, _require_tenant

# Письмо ложится только к проверке пространства, которое его фиксирует: сверка
# `tenant_code` стоит в самом запросе, а не только в вызывающем (ревью #340,
# п.7). Чужая проверка и несуществующая дают один ответ — пустой `returning`.
_INSERT_LETTER_SQL = """
insert into partner_letters (inspection_id, body, lang, saved_by)
select i.id, %(body)s, %(lang)s, %(saved_by)s
  from inspections i
 where i.id = %(inspection_id)s and i.tenant_code = %(tenant)s
returning id, created_at
"""

_SELECT_LATEST_SQL = """
select id, body, lang, saved_by, created_at
from partner_letters
where inspection_id = %s and (%s::text is null or lang = %s)
order by created_at desc, id desc
limit 1
"""


@dataclass(frozen=True)
class SavedLetter:
    """Зафиксированное письмо: что отправили, на каком языке, кто и когда."""

    id: str
    body: str
    lang: str
    saved_by: str
    created_at: datetime


def save_letter(
    inspection_id: str,
    *,
    tenant: str,
    body: str,
    lang: str,
    saved_by: str,
    journal: Entry | None = None,
) -> SavedLetter:
    """Зафиксировать письмо партнёру в том виде, в каком его подтвердил человек.

    Пустой текст — отказ, а не пустая запись: письмо из пробелов выглядит в
    истории как отправленное и обнаруживается ровно тогда, когда кто-то
    спрашивает, что получил партнёр.

    Прежние записи не трогаются. Передумал — фиксируется НОВОЕ письмо, и обе
    записи видно: из истории нельзя вынуть отправленное, иначе она перестаёт
    быть историей.

    `tenant` — пространство того, кто фиксирует: письмо к проверке другого
    пространства не ложится, и отказ тот же, что у несуществующей проверки.
    """
    tenant_code = _require_tenant(tenant)
    ident = _require_inspection_id(inspection_id)
    if not body.strip():
        raise PushError("Письмо не сохранено: в нём нет текста")
    if not lang.strip():
        raise PushError("Письмо не сохранено: не назван язык, на котором оно написано")
    if not saved_by.strip():
        raise PushError("Письмо не сохранено: не названо, кто его зафиксировал")

    settings = check_environment()
    with psycopg.connect(settings.dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                _INSERT_LETTER_SQL,
                {
                    "inspection_id": ident,
                    "tenant": tenant_code,
                    "body": body,
                    "lang": lang,
                    "saved_by": saved_by,
                },
            )
            row = cur.fetchone()
            if row is None:
                raise PushError(
                    f"Проверки {ident} нет в истории пространства — письму не к чему лечь"
                )
        record(conn, journal)  # той же транзакцией, что письмо
        conn.commit()

    return SavedLetter(id=str(row[0]), body=body, lang=lang, saved_by=saved_by, created_at=row[1])


def latest_letter(inspection_id: str, *, lang: str | None = None) -> SavedLetter | None:
    """Последнее зафиксированное письмо проверки — или `None`, если его нет.

    `None` означает ровно «никто ничего не фиксировал», а не «письма не
    существует»: заготовку по-прежнему соберёт движок. Различать эти два случая
    обязан тот, кто показывает письмо человеку, — иначе экран выдаст заготовку
    за отправленное.

    `lang` спрашивает письмо НА КОНКРЕТНОМ языке, и это не удобство. Письмо
    партнёру другой страны пишется на его языке, и зафиксированное русское для
    сербского партнёра — не «то же письмо, но переведут потом», а чужой текст.
    Без этого отбора переключатель языка на экране показывал бы сохранённое
    русское под видом сербского.
    """
    settings = check_environment()
    with psycopg.connect(settings.dsn) as conn, conn.cursor() as cur:
        cur.execute(_SELECT_LATEST_SQL, (inspection_id, lang, lang))
        row = cur.fetchone()

    if row is None:
        return None
    return SavedLetter(
        id=str(row[0]), body=str(row[1]), lang=str(row[2]), saved_by=str(row[3]), created_at=row[4]
    )
