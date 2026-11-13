"""Переводы свободного текста находок — рядом с исходником, а не поверх него (D744, #1619).

Слов аудитора в базе два вида строк `translations(entity_type='finding', field, lang)`:
исходник лежит строкой на языке речи проверки (`inspections.speech_lang`, пишет слив), всё
остальное — переводы на языки отчёта и письма. Исходник отсюда не правится и не
подменяется: цель — найти и поправить кривой перевод, а для этого есть с чем сверить.

Запись здесь только добавляет: уже лежащий перевод не перетирается (`on conflict do nothing`),
потому что два процесса, собравшие отчёт одновременно, переведут один и тот же текст и второй
не должен затирать первого. Заморозку сданной проверки миграция 0132 для этого снимает только
для языка, отличного от языка речи: исходник сданной проверки по-прежнему не добавить.
"""

from __future__ import annotations

from collections.abc import Mapping

import psycopg

from .config import check_environment
from .errors import DbError
from .pool import connection

#: Поля находки со свободным текстом аудитора, которые переводятся (`translations.field`).
FIELDS = ("text", "comment")

_SELECT_SQL = """
select t.entity_id, t.field, t.text
from translations t
join findings f on f.id = t.entity_id
where t.entity_type = 'finding' and f.inspection_id = %s and t.lang = %s and t.field = any(%s)
"""

_INSERT_SQL = """
insert into translations (entity_type, entity_id, field, lang, text)
values ('finding', %s, %s, %s, %s)
on conflict (entity_type, entity_id, field, lang) do nothing
"""

_IDS_SQL = "select n, id from findings where inspection_id = %s"


def stored(inspection_id: str, lang: str) -> dict[tuple[str, str], str]:
    """Лежащие в базе переводы проверки на язык `lang`: `(id находки, поле) → текст`.

    Сбой запроса — `DbError`: молчаливо пустой ответ заставил бы переводить заново и платить
    модели за то, что уже переведено.
    """
    try:
        with connection(check_environment().dsn) as conn, conn.cursor() as cur:
            cur.execute(_SELECT_SQL, (inspection_id, lang, list(FIELDS)))
            return {(str(row[0]), str(row[1])): str(row[2]) for row in cur.fetchall()}
    except psycopg.Error as exc:
        raise DbError(
            f"Переводы находок проверки {inspection_id} не прочитаны ({type(exc).__name__})"
        ) from exc


def store(inspection_id: str, lang: str, items: Mapping[tuple[str, str], str]) -> None:
    """Положить переводы на `lang`: `(id находки, поле) → текст`. Лежащие уже не трогаются."""
    rows = [
        (finding_id, field, lang, text)
        for (finding_id, field), text in items.items()
        if field in FIELDS and text.strip()
    ]
    if not rows:
        return
    try:
        with connection(check_environment().dsn) as conn, conn.cursor() as cur:
            cur.executemany(_INSERT_SQL, rows)
            conn.commit()
    except psycopg.Error as exc:
        raise DbError(
            f"Переводы находок проверки {inspection_id} не записаны ({type(exc).__name__})"
        ) from exc


def store_by_number(inspection_id: str, lang: str, items: Mapping[int, Mapping[str, str]]) -> None:
    """То же, но находки названы номерами: так их знает бот до слива."""
    try:
        with connection(check_environment().dsn) as conn, conn.cursor() as cur:
            cur.execute(_IDS_SQL, (inspection_id,))
            ids = {int(row[0]): str(row[1]) for row in cur.fetchall()}
    except psycopg.Error as exc:
        raise DbError(
            f"Находки проверки {inspection_id} не прочитаны ({type(exc).__name__})"
        ) from exc
    store(
        inspection_id,
        lang,
        {
            (ids[n], field): text
            for n, fields in items.items()
            if n in ids
            for field, text in fields.items()
        },
    )
