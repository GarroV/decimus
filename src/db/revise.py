"""Правка записи проверки на приёмке — вместе с пересчитанной оценкой (D200).

До подтверждения запись правится целиком: пункт, класс, зона, формулировка.
Оценку сюда приносит вызывающий, посчитанной движком (`src/report/rescore.py`)
по уже исправленным записям: этот модуль чисел не считает, он их кладёт.

Запись и оценка пишутся ОДНОЙ транзакцией. Порознь они разошлись бы при первом
же обрыве — и в истории оказалась бы исправленная запись под буквой,
посчитанной по неисправленной.

Идёт под ролью приложения: правка ждущей проверки разрешена ей политиками
`0004` ровно потому, что проверка ещё `draft`. Как только проверка принята,
те же политики запрещают правку всем — и это держит база, а не этот модуль.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.types.json import Json

from ..domain.models import Score
from .config import check_environment
from .errors import ReviseError
from .push import _INSERT_TRANSLATION_SQL, _by_zone_payload
from .queries import _require_inspection_id, _require_tenant


@dataclass(frozen=True)
class Revision:
    """Что вычитывающий хочет видеть в записи вместо записанного."""

    code: str
    level: str
    zone: str
    zone_unusual: bool
    text: str


_SELECT_HEAD_SQL = """
select i.status, i.retracted_at, i.speech_lang, f.id
from inspections i
left join findings f on f.inspection_id = i.id and f.id = %(finding)s
where i.id = %(id)s and i.tenant_code = %(tenant)s
"""
# Без `for update`: под ролью приложения блокировка строки требует права её
# править, а принятую проверку политика заморозки прячет от правки — и отказ
# «уже принята» превратился бы в «проверки нет». Гонку с подтверждением
# закрывает условие `status = 'draft'` в записи оценки и проверка числа строк.

_PAIR_TAKEN_SQL = """
select n from findings
where inspection_id = %(id)s and code = %(code)s and zone = %(zone)s and id <> %(finding)s
"""

_UPDATE_FINDING_SQL = """
update findings
set code = %(code)s, level = %(level)s, zone = %(zone)s, zone_unusual = %(zone_unusual)s
where id = %(finding)s and inspection_id = %(id)s
"""

_UPDATE_SCORE_SQL = """
update inspections
set pct = %(pct)s, grade = %(grade)s, deductions = %(deductions)s,
    counts = %(counts)s, by_zone = %(by_zone)s
where id = %(id)s and tenant_code = %(tenant)s and status = 'draft'
"""


def revise_finding(
    inspection_id: str, finding_id: str, *, tenant: str, revision: Revision, score: Score
) -> None:
    """Исправить запись ждущей проверки и положить пересчитанную оценку.

    Отказ — `ReviseError`: проверки или записи нет, проверка уже принята или
    отклонена, пара «пункт + зона» уже занята другой записью.
    """
    ident = _require_inspection_id(inspection_id)
    запись = _require_inspection_id(finding_id)
    tenant_code = _require_tenant(tenant)
    if not revision.text.strip():
        raise ReviseError("Формулировка записи пуста — запись без слов в отчёт не идёт")
    try:
        with psycopg.connect(check_environment().dsn) as conn:
            _apply(conn, ident, запись, tenant_code, revision, score)
            conn.commit()
    except ReviseError:
        raise
    except psycopg.Error as exc:
        raise ReviseError(
            f"Исправить запись не удалось ({type(exc).__name__}). Ни запись, ни оценка не "
            f"изменились — они пишутся одной транзакцией"
        ) from exc


def _apply(
    conn: psycopg.Connection[Any],
    ident: str,
    запись: str,
    tenant: str,
    revision: Revision,
    score: Score,
) -> None:
    with conn.cursor() as cur:
        cur.execute(_SELECT_HEAD_SQL, {"id": ident, "tenant": tenant, "finding": запись})
        шапка = cur.fetchone()
        if шапка is None:
            raise ReviseError(f"Проверки {ident} у арендатора {tenant} нет")
        статус, отклонена, язык_речи, есть_запись = шапка
        if отклонена is not None:
            raise ReviseError("Проверка отклонена — её записи не исправляют")
        if статус != "draft":
            raise ReviseError(
                "Проверка уже принята — записи принятой не исправляются (D200). "
                "Поправить можно только шапку, под журналом"
            )
        if есть_запись is None:
            raise ReviseError("Такой записи в этой проверке нет")
        cur.execute(
            _PAIR_TAKEN_SQL,
            {"id": ident, "code": revision.code, "zone": revision.zone, "finding": запись},
        )
        занята = cur.fetchone()
        if занята is not None:
            raise ReviseError(
                f"Пункт {revision.code} в этой зоне уже записан — запись {занята[0]}. "
                f"Одна пара «пункт + зона» — одна запись"
            )
        cur.execute(
            _UPDATE_FINDING_SQL,
            {
                "id": ident,
                "finding": запись,
                "code": revision.code,
                "level": revision.level,
                "zone": revision.zone,
                "zone_unusual": revision.zone_unusual,
            },
        )
        cur.execute(
            _INSERT_TRANSLATION_SQL,
            ("finding", запись, "text", язык_речи, revision.text.strip()),
        )
        cur.execute(
            _UPDATE_SCORE_SQL,
            {
                "id": ident,
                "tenant": tenant,
                "pct": score.pct,
                "grade": score.grade,
                "deductions": score.deductions,
                "counts": Json(dict(score.counts)),
                "by_zone": Json(_by_zone_payload(score)),
            },
        )
        if cur.rowcount != 1:
            raise ReviseError(
                "Оценку не удалось записать: проверка перестала ждать приёмки, пока её правили"
            )
        for lang, label in (("ru", score.label_ru), ("en", score.label_en)):
            if label:
                cur.execute(
                    _INSERT_TRANSLATION_SQL, ("inspection", ident, "grade_label", lang, label)
                )
