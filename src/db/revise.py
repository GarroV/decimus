"""Правка записи проверки на приёмке — вместе с пересчитанной оценкой (D200).

До подтверждения запись правится целиком: пункт, класс, зона, формулировка.
Оценку считает движок вызывающего (`score_of`, обычно `src/report/rescore.py`):
этот модуль чисел не считает, он отдаёт движку проверку с уже применённой
правкой и кладёт то, что движок вернул.

ПРАВКИ ОДНОЙ ПРОВЕРКИ ИДУТ ПО ОЧЕРЕДИ. Первым действием транзакция берёт замок
строки проверки (`for update`), и только ПОСЛЕ него читает записи, считает
оценку и пишет. Без замка два вычитывающих, правящих разные записи, считали
бы каждый от своего снимка — и последней легла бы оценка без одной правки
(ядро: число в отчёте). Замок выбран, а не оптимистичная версия: правки
редкие и короткие, ждать соседа лучше, чем отказывать ему и заставлять
повторять; и тот же замок закрывает гонку проверки «пара пункт + зона
свободна». Подтверждение (`accept.py`) берёт тот же замок, поэтому правка и
подтверждение одной проверки тоже не перекрываются.

Запись и оценка пишутся ОДНОЙ транзакцией. Порознь они разошлись бы при первом
же обрыве — и в истории оказалась бы исправленная запись под буквой,
посчитанной по неисправленной.

Идёт под ролью приложения: правка ждущей проверки разрешена ей политиками
`0004` ровно потому, что проверка ещё `draft`. Как только проверка принята,
те же политики запрещают правку всем — и это держит база, а не этот модуль.

Правит каждый только своё пространство (D283): `tenant` — пространство
вошедшего, и проверка другого пространства отвечает тем же «нет», что
несуществующая. Условие стоит в самом запросе: роль приложения одна на все
пространства, и заслон только на маршруте веба снимался бы одной ошибкой там.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

import psycopg
from psycopg.types.json import Json

from ..domain.models import Score
from .config import check_environment
from .errors import ReviseError
from .models import ORIGIN_LEGACY, InspectionDetail
from .push import _INSERT_TRANSLATION_SQL, _by_zone_payload
from .queries import _read_detail, _require_inspection_id, _require_tenant
from .reach import own_reach


@dataclass(frozen=True)
class Revision:
    """Что вычитывающий хочет видеть в записи вместо записанного."""

    code: str
    level: str
    zone: str
    zone_unusual: bool
    text: str


# Замок строки ждущей проверки — первое действие транзакции. Под ролью
# приложения `for update` требует права править строку, а принятую проверку
# политика заморозки от правки прячет: поэтому замок берётся только у ждущей,
# а почему его не дали, объясняет второй, обычный запрос ниже.
_LOCK_SQL = """
select i.speech_lang, i.origin
from inspections i
where i.id = %(id)s and i.tenant_code = %(tenant)s
  and i.status = 'draft' and i.retracted_at is null
for update
"""

_SELECT_HEAD_SQL = """
select i.status, i.retracted_at
from inspections i
where i.id = %(id)s and i.tenant_code = %(tenant)s
"""

_PAIR_TAKEN_SQL = """
select n from findings
where inspection_id = %(id)s and code = %(code)s and zone = %(zone)s and id <> %(finding)s
  and level not in ('D0', 'R')
"""

_UPDATE_FINDING_SQL = """
update findings
set code = %(code)s, level = %(level)s, zone = %(zone)s, zone_unusual = %(zone_unusual)s
where id = %(finding)s and inspection_id = %(id)s
"""

# `origin <> 'legacy'`: оценку исторической движок не пишет никогда (D332).
# Заслон здесь второй — первый стоит в `_apply` до движка, третий в базе
# (`inspections_legacy_score_as_is`, 0042).
_UPDATE_SCORE_SQL = """
update inspections
set pct = %(pct)s, grade = %(grade)s, deductions = %(deductions)s,
    counts = %(counts)s, by_zone = %(by_zone)s
where id = %(id)s and tenant_code = %(tenant)s and status = 'draft' and origin <> 'legacy'
"""


def revise_finding(
    inspection_id: str,
    finding_id: str,
    *,
    tenant: str,
    revision: Revision,
    score_of: Callable[[InspectionDetail], Score],
) -> None:
    """Исправить запись ждущей проверки и положить оценку, посчитанную после замка.

    `score_of` получает проверку, прочитанную ПОСЛЕ замка и с уже применённой
    правкой, и возвращает оценку движка. Его исключение откатывает всё.

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
            _apply(conn, ident, запись, tenant_code, revision, score_of)
            conn.commit()
    except ReviseError:
        raise
    except psycopg.Error as exc:
        raise ReviseError(
            f"Исправить запись не удалось ({type(exc).__name__}). Ни запись, ни оценка не "
            f"изменились — они пишутся одной транзакцией"
        ) from exc


def _refuse_lock(cur: Any, ident: str, tenant: str) -> ReviseError:
    """Почему замок не дали: проверки нет, она отклонена или уже принята."""
    cur.execute(_SELECT_HEAD_SQL, {"id": ident, "tenant": tenant})
    шапка = cur.fetchone()
    if шапка is None:
        return ReviseError(f"Проверки {ident} у арендатора {tenant} нет")
    if шапка[1] is not None:
        return ReviseError("Проверка отклонена — её записи не исправляют")
    return ReviseError(
        "Проверка уже принята — записи принятой не исправляются (D200). "
        "Поправить можно только шапку, под журналом"
    )


def _revised(detail: InspectionDetail, запись: str, revision: Revision) -> InspectionDetail:
    """Проверка, какой она станет после правки, — её и считает движок."""
    прежняя = next((f for f in detail.findings if f.id == запись), None)
    if прежняя is None:
        raise ReviseError("Такой записи в этой проверке нет")
    исправленная = replace(
        прежняя,
        code=revision.code,
        level=revision.level,
        zone=revision.zone,
        zone_unusual=revision.zone_unusual,
        text=revision.text.strip(),
    )
    return replace(
        detail,
        findings=tuple(исправленная if f.id == запись else f for f in detail.findings),
    )


def _apply(
    conn: psycopg.Connection[Any],
    ident: str,
    запись: str,
    tenant: str,
    revision: Revision,
    score_of: Callable[[InspectionDetail], Score],
) -> None:
    with conn.cursor() as cur:
        cur.execute(_LOCK_SQL, {"id": ident, "tenant": tenant})
        замок = cur.fetchone()
        if замок is None:
            raise _refuse_lock(cur, ident, tenant)
        язык_речи, происхождение = замок
        if происхождение == ORIGIN_LEGACY:
            # Историческая (D332): оценка из старого отчёта, движок её не
            # пересчитывает — значит, и правки с пересчётом у неё нет. Отказ
            # ДО движка: `score_of` не зовётся.
            raise ReviseError(
                "Проверка историческая: оценка перенесена из старого отчёта как есть и "
                "движком не пересчитывается (D332). Её записи правят инструментами "
                "загрузки (import_edit_finding) до подтверждения"
            )
        # Всё ниже — после замка: соседняя правка этой проверки уже записана
        # целиком или ещё не началась.
        detail = _read_detail(cur, reach=own_reach(tenant), ident=ident, include_on_review=True)
        if detail is None:
            raise ReviseError(f"Проверки {ident} у арендатора {tenant} нет")
        score = score_of(_revised(detail, запись, revision))
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
        if cur.rowcount != 1:
            raise ReviseError(
                "Запись не исправлена: проверка уже подтверждена или записи больше нет. "
                "Ни запись, ни оценка не изменились"
            )
        cur.execute(
            _INSERT_TRANSLATION_SQL,
            ("finding", запись, "text", язык_речи, revision.text.strip()),
        )
        _write_score(cur, ident, tenant, score)


def _write_score(cur: Any, ident: str, tenant: str, score: Score) -> None:
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
            cur.execute(_INSERT_TRANSLATION_SQL, ("inspection", ident, "grade_label", lang, label))
